"""Periodic Huey tasks for search-engine notifications (ADR-0002, docs/etudes/kliz.md)."""

from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from . import notifier


@db_periodic_task(crontab(minute="*/10"))
def flush_indexing_queue() -> int:
    """Debounced batch: every 10 minutes, notify all queued URLs at once (Retry-After honoured)."""
    return notifier.flush_queue()


@db_periodic_task(crontab(hour="3", minute="30"))
def indexing_daily_catch_up() -> int:
    """Re-queue the notifications that failed in the last 24 h and resubmit the sitemap to Google once a day."""
    return notifier.catch_up()
