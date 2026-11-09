"""Search-engine notification with kliz (docs/etudes/kliz.md).

Public interface used by other apps:  queue_urls(urls)
The queue is flushed in one batch by a periodic Huey task (apps.seo.tasks).
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import IndexingQueue


def queue_urls(urls: Iterable[str]) -> None:
    """Add URLs to the debounced notification queue (idempotent)."""
    for url in {u for u in urls if u}:
        IndexingQueue.objects.update_or_create(url=url)
