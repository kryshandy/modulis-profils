from datetime import timedelta

from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from . import services


@db_periodic_task(crontab(minute="5", hour="0"))  # 00:05 UTC = 01:05 in Douala
def aggregate_daily_stats() -> dict:
    """Aggregate yesterday's events (bots excluded) into DailyStat, then purge raw events > 13 months."""
    yesterday = timezone.localdate() - timedelta(days=1)
    rows = services.aggregate_day(yesterday)
    purged = services.purge_old_events()
    return {"day": yesterday.isoformat(), "rows": rows, "purged": purged}
