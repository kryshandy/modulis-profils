"""Huey tasks for search-engine notifications (ADR-0002, docs/etudes/kliz.md)."""

import logging

from huey import crontab
from huey.contrib.djhuey import db_periodic_task, db_task

from . import notifier

logger = logging.getLogger(__name__)


def _indexing_enabled() -> bool:
    """Control-center switch "notifications d'indexation": off = URLs stay queued until it is back on."""
    from apps.platform.services import feature

    return feature("indexing")


@db_periodic_task(crontab(minute="*/10"))
def flush_indexing_queue() -> int:
    """Debounced batch: every 10 minutes, notify all queued URLs at once (Retry-After honoured)."""
    if not _indexing_enabled():
        logger.info("indexing notifications switched off: queue kept")
        return 0
    return notifier.flush_queue()


@db_task()
def flush_indexing_queue_now() -> int:
    """Same notifier path as the periodic flush, run as soon as a worker picks it up."""
    if not _indexing_enabled():
        return 0
    return notifier.flush_queue()


def flush_now():
    """Instant publication (themes "Valider et publier"): enqueue a flush right now instead of
    waiting for the next 10-minute batch. Call it from transaction.on_commit, after queue_urls()."""
    return flush_indexing_queue_now()


@db_periodic_task(crontab(hour="3", minute="30"))
def indexing_daily_catch_up() -> int:
    """Re-queue the notifications that failed in the last 24 h and resubmit the sitemap to Google once a day."""
    return notifier.catch_up()
