"""Daily billing jobs: expiry (back to free, never deletion) and renewal reminders J-30 / J-7 / J0."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from apps.accounts.tasks import send_sms_task

from . import services
from .models import Subscription

REMINDER_DAYS = (30, 7, 0)
REMINDER_CACHE_TTL = 3 * 24 * 3600


def _day_window(day: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def subscriptions_due(days_before: int, today: date | None = None):
    """Active subscriptions whose end falls exactly on today + `days_before` (local time),
    excluding profiles that already renewed (another active subscription ends later)."""
    today = today or timezone.localdate()
    start, end = _day_window(today + timedelta(days=days_before))
    due = Subscription.objects.select_related("profile__user", "plan").filter(
        status=Subscription.Status.ACTIVE, ends_at__gte=start, ends_at__lt=end
    )
    return [
        sub
        for sub in due
        if not Subscription.objects.filter(
            profile=sub.profile, status=Subscription.Status.ACTIVE, ends_at__gt=sub.ends_at
        ).exists()
    ]


def reminder_text(sub: Subscription, days_before: int) -> str:
    end = date_format(timezone.localtime(sub.ends_at), "j F Y")
    params = {"site": settings.SITE_NAME, "plan": sub.plan.name, "date": end, "n": days_before}
    if days_before == 0:
        return _(
            "{site} : ton offre {plan} se termine aujourd'hui. Ta page reste en ligne en version gratuite. "
            "Renouvelle-la depuis ton espace pour garder tes avantages."
        ).format(**params)
    return _(
        "{site} : ton offre {plan} se termine dans {n} jours ({date}). Renouvelle-la depuis ton espace pour "
        "garder ton badge et tes statistiques."
    ).format(**params)


def send_renewal_reminders(today: date | None = None) -> int:
    sent = 0
    for days_before in REMINDER_DAYS:
        for sub in subscriptions_due(days_before, today):
            # Exact-day windows already make each milestone unique; the cache key guards against a
            # second run on the same day (manual re-run, retry).
            if not cache.add(f"billing:reminder:{sub.pk}:{days_before}", 1, REMINDER_CACHE_TTL):
                continue
            phone = sub.profile.user.phone
            if phone:
                send_sms_task(phone, reminder_text(sub, days_before))
                sent += 1
    return sent


@db_periodic_task(crontab(minute="0", hour="8"))  # 08:00 UTC = 09:00 in Douala: SMS at a decent hour
def daily_billing() -> dict:
    reminders = send_renewal_reminders()  # before expiry, so J0 reminders still see "active" rows
    expired = services.expire_subscriptions()
    return {"reminders": reminders, "expired": expired}
