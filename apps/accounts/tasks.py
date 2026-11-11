from datetime import timedelta

from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, task

from . import sms


@task(retries=2, retry_delay=10)
def send_sms_task(to: str, body: str) -> None:
    sms.send_sms(to, body)


@task(retries=2, retry_delay=10, context=True)
def send_otp_task(channel_code: str, phone: str, code: str, challenge_id: int, task=None) -> None:
    """Deliver a one-time code (WhatsApp, SMS gateway, dev console). Retries transient failures only.

    Never log `code`: Huey logs the task id, not its arguments.
    """
    from .services import deliver_otp

    retries_left = getattr(task, "retries", 0) or 0
    deliver_otp(channel_code, phone, code, challenge_id, final=retries_left <= 0)


@db_periodic_task(crontab(minute="17", hour="3"))
def purge_old_otp_challenges() -> int:
    """Keep 30 days of OTP history (abuse investigation), then delete."""
    from .models import OTPChallenge

    deleted, _ = OTPChallenge.objects.filter(created_at__lt=timezone.now() - timedelta(days=30)).delete()
    return deleted
