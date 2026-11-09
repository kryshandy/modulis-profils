from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import services, tasks
from apps.billing.models import Plan, PlanPrice, Subscription
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db


def test_plans_seeded_with_cameroon_prices():
    expected = {"free": 0, "essentiel": 12000, "pro": 30000, "team": 15000}
    for code, amount in expected.items():
        plan = Plan.objects.get(code=code)
        price = PlanPrice.objects.get(plan=plan, country_id="CM")
        assert price.amount == amount and price.currency == "XAF"
    assert Plan.objects.get(code="essentiel").entitlements["verified_badge"] is True
    assert Plan.objects.get(code="free").entitlements["hide_branding"] is False
    assert Plan.objects.get(code="pro").entitlements["max_profiles"] == 3


def test_grant_essentiel_gives_entitlements():
    profile = ProfileFactory()
    services.grant_plan(profile, Plan.objects.get(code="essentiel"))
    assert services.current_plan_code(profile) == "essentiel"
    assert services.has(profile, "advanced_stats")


def _sub(profile, plan_code, ends_in: timedelta, status=Subscription.Status.ACTIVE):
    now = timezone.now()
    return Subscription.objects.create(
        profile=profile,
        plan=Plan.objects.get(code=plan_code),
        starts_at=now - timedelta(days=300),
        ends_at=now + ends_in,
        status=status,
    )


class TestReminders:
    def test_milestones_send_once(self, sms_outbox):
        p30, p7, p0, p10 = (ProfileFactory() for _ in range(4))
        _sub(p30, "essentiel", timedelta(days=30))
        _sub(p7, "pro", timedelta(days=7))
        _sub(p0, "essentiel", timedelta(minutes=1))
        _sub(p10, "essentiel", timedelta(days=10))  # no milestone today
        assert tasks.send_renewal_reminders() == 3
        recipients = {m.to for m in sms_outbox}
        assert recipients == {p30.user.phone, p7.user.phone, p0.user.phone}
        assert any("30 jours" in m.body for m in sms_outbox)
        assert any("aujourd'hui" in m.body for m in sms_outbox)
        # A second run the same day sends nothing.
        assert tasks.send_renewal_reminders() == 0
        assert len(sms_outbox) == 3

    def test_renewed_subscription_not_reminded(self, sms_outbox):
        profile = ProfileFactory()
        _sub(profile, "essentiel", timedelta(days=7))
        _sub(profile, "essentiel", timedelta(days=372))
        assert tasks.send_renewal_reminders() == 0

    def test_daily_task_expires_after_reminders(self, sms_outbox):
        profile = ProfileFactory()
        ended = _sub(profile, "essentiel", timedelta(days=-1))
        result = tasks.daily_billing.call_local()
        assert result["expired"] == 1
        ended.refresh_from_db()
        assert ended.status == Subscription.Status.EXPIRED
        assert services.current_plan_code(profile) == "free"
