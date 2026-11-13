"""Retention periods announced in the privacy policy (apps/legal/templates/legal/confidentialite.html)."""

from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from .services import purge_expired_records


@db_periodic_task(crontab(minute="41", hour="2"))  # 03:41 in Douala, outside the backup window
def purge_expired_records_task() -> dict:
    return purge_expired_records()
