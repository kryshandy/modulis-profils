from datetime import timedelta

from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, task

from . import sms


@task(retries=2, retry_delay=10)
def send_sms_task(to: str, body: str) -> None:
    sms.send_sms(to, body)


@db_periodic_task(crontab(minute="17", hour="3"))
def purge_old_otp_challenges() -> int:
    """Keep 30 days of OTP history (abuse investigation), then delete."""
    from .models import OTPChallenge

    deleted, _ = OTPChallenge.objects.filter(created_at__lt=timezone.now() - timedelta(days=30)).delete()
    return deleted
