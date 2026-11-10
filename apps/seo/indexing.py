"""Search-engine notification with kliz (docs/etudes/kliz.md).

Public interface used by other apps:
- queue_urls(urls)
- related_urls(profile) / queue_profile_related(profile): the city page and the trade×city page whose
  content changes when a profile becomes (non-)indexable.
The queue is flushed in one batch by a periodic Huey task (apps.seo.tasks).
"""

from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.urls import reverse

from .models import IndexingQueue


def queue_urls(urls: Iterable[str]) -> None:
    """Add URLs to the debounced notification queue (idempotent, race-free upsert).

    Called from on_commit callbacks: it must never raise IntegrityError after the data is committed.
    """
    rows = [IndexingQueue(url=url) for url in {u for u in urls if u}]
    if rows:
        IndexingQueue.objects.bulk_create(rows, ignore_conflicts=True)


def related_urls(profile) -> list[str]:
    """Absolute URLs of the listing pages that show `profile`: /villes/<city> and /<trades>/<city>.

    Computed eagerly (call it before the transaction commits if city/trade may change afterwards).
    Below the directory threshold these pages are noindex, and at 0 profiles they answer 404: search
    engines must hear about both transitions, so the URLs are returned whatever the current count.
    """
    city = getattr(profile, "city", None)
    if city is None:
        return []
    urls = [settings.SITE_URL + reverse("public:city", kwargs={"city": city.slug})]
    trade = getattr(profile, "trade", None)
    if trade is not None and trade.plural_slug:
        urls.append(
            settings.SITE_URL
            + reverse("public:directory", kwargs={"trade_plural": trade.plural_slug, "city": city.slug})
        )
    return urls


def queue_profile_related(profile) -> None:
    queue_urls(related_urls(profile))
