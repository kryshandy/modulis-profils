"""Flush the IndexingQueue to search engines with kliz (docs/etudes/kliz.md §4).

Synchronous network calls: only ever run from Huey tasks or management commands, never in a request.

Retries (SEO audit 2026-11-10 #2):
- inside one flush, kliz retries a retryable failure (429, 5xx, network) up to MAX_ATTEMPTS times within DEADLINE;
- a result that is still a retryable failure puts its URLs back in the queue, not before its Retry-After;
- a non-retryable failure (400, 403, 422…) is only logged;
- the daily catch-up re-queues the URLs whose last notification of the past 24 h failed
  (removals answering 404/410 included) and resubmits the sitemap to Google once.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from kliz import BaseProvider, GoogleSearchConsoleProvider, IndexNowProvider, Kliz, NotificationResult

from .models import IndexingLog, IndexingQueue

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000  # IndexNow accepts up to 10 000 URLs per request
MAX_ATTEMPTS = 3
DEADLINE_SECONDS = 120
DEFAULT_RETRY_DELAY = timedelta(minutes=30)  # when the engine gives no Retry-After
MAX_RETRY_DELAY = timedelta(days=1)
LOGGED_URLS_MAX = BATCH_SIZE
GOOGLE_PROVIDER = "GoogleSearchConsoleProvider"  # resubmits the sitemap: its URLs never go back in the queue


def _sleep(seconds: float) -> None:
    """Indirection so tests never really sleep between kliz attempts."""
    time.sleep(seconds)


def key_location() -> str:
    return f"{settings.SITE_URL}/{settings.KLIZ_INDEXNOW_KEY}.txt"


def indexnow_provider() -> IndexNowProvider:
    return IndexNowProvider(api_key=settings.KLIZ_INDEXNOW_KEY, key_location=key_location())


def google_provider() -> BaseProvider | None:
    if settings.KLIZ_GSC_SITE and settings.KLIZ_GSC_SERVICE_ACCOUNT_FILE:
        return GoogleSearchConsoleProvider(
            service_account_file=settings.KLIZ_GSC_SERVICE_ACCOUNT_FILE,
            site_url=settings.KLIZ_GSC_SITE,
            sitemap_url=f"{settings.SITE_URL}/sitemap.xml",
        )
    return None


def default_providers(*, include_google: bool = False) -> list[BaseProvider]:
    """IndexNow always; Search Console (sitemap resubmission) only if configured and asked for.

    Google is limited to the daily catch-up: one sitemap resubmission per day at most.
    """
    providers: list[BaseProvider] = []
    if settings.KLIZ_INDEXNOW_KEY:
        providers.append(indexnow_provider())
    if include_google:
        google = google_provider()
        if google is not None:
            providers.append(google)
    return providers


def _retry_at(result: NotificationResult):
    delay = DEFAULT_RETRY_DELAY
    if result.retry_after is not None and result.retry_after > 0:
        delay = min(timedelta(seconds=result.retry_after), MAX_RETRY_DELAY)
    return timezone.now() + delay


def requeue(urls: Sequence[str], not_before=None) -> int:
    """Put URLs back in the queue; a URL already queued (newer change) keeps its own row."""
    rows = [IndexingQueue(url=url[:300], not_before=not_before) for url in dict.fromkeys(u for u in urls if u)]
    if rows:
        IndexingQueue.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def log_result(result: NotificationResult) -> None:
    """kliz `on_result` hook: one IndexingLog row per final result, retryable failures re-queued."""
    urls = list(result.urls)
    IndexingLog.objects.create(
        provider=result.provider[:60],
        success=result.success,
        url_count=len(urls),
        sample_url=(urls[0] if urls else "")[:300],
        urls=urls[:LOGGED_URLS_MAX],
        status_code=result.status_code,
        error=(result.error or "")[:2000],
        attempts=result.attempts,
    )
    if not result.success and result.retryable and result.provider != GOOGLE_PROVIDER:
        count = requeue(urls, not_before=_retry_at(result))
        logger.warning("%s: retryable failure, %d URL(s) re-queued", result.provider, count)


def notify(urls: Sequence[str], providers: Sequence[BaseProvider]) -> dict[str, list[NotificationResult]]:
    if not urls or not providers:
        return {}
    with Kliz(
        providers, max_attempts=MAX_ATTEMPTS, deadline=DEADLINE_SECONDS, sleep=_sleep, on_result=log_result
    ) as client:
        return client.notify_many_detailed(list(urls))


def pop_queue(limit: int = BATCH_SIZE) -> list[str]:
    """Take a batch out of the queue.

    A URL re-queued meanwhile (newer queued_at) stays queued; a URL waiting for its Retry-After too.
    """
    cutoff = timezone.now()
    ready = Q(queued_at__lte=cutoff) & (Q(not_before__isnull=True) | Q(not_before__lte=cutoff))
    rows = list(IndexingQueue.objects.filter(ready).order_by("queued_at").values_list("pk", "url")[:limit])
    if not rows:
        return []
    IndexingQueue.objects.filter(ready, pk__in=[pk for pk, _url in rows]).delete()
    return [url for _pk, url in rows]


def flush_queue(providers: Sequence[BaseProvider] | None = None) -> int:
    """Notify every queued URL in one batch. Returns the number of URLs taken out of the queue."""
    urls = pop_queue()
    if not urls:
        return 0
    if providers is None:
        if not settings.KLIZ_ENABLED:
            logger.info("KLIZ_ENABLED is off: dropping %d queued URL(s) without notifying", len(urls))
            return len(urls)
        providers = default_providers()
    if not providers:
        logger.warning("No indexing provider configured: %d URL(s) dropped", len(urls))
        return len(urls)
    notify(urls, providers)
    return len(urls)


def _log_urls(log: IndexingLog) -> list[str]:
    return list(log.urls) if log.urls else ([log.sample_url] if log.sample_url else [])


def _window_logs(hours: int):
    since = timezone.now() - timedelta(hours=hours)
    return (
        IndexingLog.objects.filter(created_at__gte=since)
        .exclude(provider=GOOGLE_PROVIDER)
        .order_by("created_at", "pk")
        .only("success", "urls", "sample_url")
    )


def failed_urls(hours: int = 24) -> list[str]:
    """URLs whose LAST push notification of the window failed (Google sitemap resubmissions excluded)."""
    state: dict[str, bool] = {}
    for log in _window_logs(hours).iterator(chunk_size=200):
        for url in _log_urls(log):
            state[url] = log.success
    return [url for url, success in state.items() if not success]


def notified_urls(hours: int = 24) -> list[str]:
    """Every URL pushed during the window (successful or not): what Google should hear about once a day."""
    seen: dict[str, None] = {}
    for log in _window_logs(hours).iterator(chunk_size=200):
        seen.update(dict.fromkeys(_log_urls(log)))
    return list(seen)


def catch_up(providers: Sequence[BaseProvider] | None = None, hours: int = 24) -> int:
    """Daily catch-up: re-queue the failures of the last `hours`, resubmit the sitemap to Google.

    `providers` defaults to Google Search Console only (IndexNow gets the re-queued URLs at the next
    flush). Returns the number of URLs re-queued.
    """
    if providers is None:
        if not settings.KLIZ_ENABLED:
            logger.info("KLIZ_ENABLED is off: catch-up skipped")
            return 0
        google = google_provider()
        providers = [google] if google is not None else []
    retry = failed_urls(hours)
    requeue(retry)
    changed = notified_urls(hours)
    if changed and providers:
        notify(changed[:BATCH_SIZE], providers)
    return len(retry)
