"""Periodic Huey tasks of the platform app."""

from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from . import services


@db_periodic_task(crontab(minute="*"))
def huey_heartbeat() -> float:
    """Every minute: proves the worker is alive (the control center shows "en retard" after 3 min)."""
    return services.record_heartbeat()
