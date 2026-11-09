"""Flush the IndexingQueue to search engines with kliz (docs/etudes/kliz.md §4).

Synchronous network calls: only ever run from Huey tasks or management commands, never in a request.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from kliz import BaseProvider, GoogleSearchConsoleProvider, IndexNowProvider, Kliz, NotificationResult

from .models import IndexingLog, IndexingQueue

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000  # IndexNow accepts up to 10 000 URLs per request
MAX_ATTEMPTS = 3


def key_location() -> str:
    return f"{settings.SITE_URL}/{settings.KLIZ_INDEXNOW_KEY}.txt"


def indexnow_provider() -> IndexNowProvider:
    return IndexNowProvider(api_key=settings.KLIZ_INDEXNOW_KEY, key_location=key_location())


def default_providers(*, include_google: bool = False) -> list[BaseProvider]:
    """IndexNow always; Search Console (sitemap resubmission) only if configured and asked for.

    Google is limited to the daily catch-up: one sitemap resubmission per day at most.
    """
    providers: list[BaseProvider] = []
    if settings.KLIZ_INDEXNOW_KEY:
        providers.append(indexnow_provider())
    if include_google and settings.KLIZ_GSC_SITE and settings.KLIZ_GSC_SERVICE_ACCOUNT_FILE:
        providers.append(
            GoogleSearchConsoleProvider(
                service_account_file=settings.KLIZ_GSC_SERVICE_ACCOUNT_FILE,
                site_url=settings.KLIZ_GSC_SITE,
                sitemap_url=f"{settings.SITE_URL}/sitemap.xml",
            )
        )
    return providers


def log_result(result: NotificationResult) -> None:
    """kliz `on_result` hook: one IndexingLog row per final result."""
    IndexingLog.objects.create(
        provider=result.provider[:60],
        success=result.success,
        url_count=len(result.urls),
        sample_url=(result.urls[0] if result.urls else "")[:300],
        status_code=result.status_code,
        error=(result.error or "")[:2000],
        attempts=result.attempts,
    )


def notify(urls: Sequence[str], providers: Sequence[BaseProvider]) -> dict[str, list[NotificationResult]]:
    if not urls or not providers:
        return {}
    with Kliz(providers, max_attempts=MAX_ATTEMPTS, on_result=log_result) as client:
        return client.notify_many_detailed(list(urls))


def pop_queue(limit: int = BATCH_SIZE) -> list[str]:
    """Take a batch out of the queue. A URL re-queued meanwhile (newer queued_at) stays queued."""
    cutoff = timezone.now()
    rows = list(
        IndexingQueue.objects.filter(queued_at__lte=cutoff).order_by("queued_at").values_list("pk", "url")[:limit]
    )
    if not rows:
        return []
    IndexingQueue.objects.filter(pk__in=[pk for pk, _url in rows], queued_at__lte=cutoff).delete()
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


def recent_urls(hours: int = 24) -> list[str]:
    """Indexable pages changed recently (daily catch-up, in case a notification failed)."""
    from . import selectors

    since = timezone.now() - timedelta(hours=hours)
    profiles = selectors.indexable_profiles().filter(content_updated_at__gte=since).select_related(None).only("slug")
    return [f"{settings.SITE_URL}{p.get_absolute_url()}" for p in profiles]


def catch_up(providers: Sequence[BaseProvider] | None = None, hours: int = 24) -> int:
    urls = recent_urls(hours)
    if not urls:
        return 0
    if providers is None:
        if not settings.KLIZ_ENABLED:
            logger.info("KLIZ_ENABLED is off: catch-up of %d URL(s) skipped", len(urls))
            return 0
        providers = default_providers(include_google=True)
    notify(urls[:BATCH_SIZE], providers)
    return len(urls)
