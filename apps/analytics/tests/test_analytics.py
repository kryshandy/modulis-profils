from datetime import datetime, time, timedelta

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.analytics import services, tasks
from apps.analytics.models import DailyStat, Event
from apps.profiles.models import Profile
from tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
IPAD = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
ANDROID_TABLET = "Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 Chrome/120 Safari/537.36"


class TestDetection:
    @pytest.mark.parametrize(
        "ua",
        [
            "Googlebot/2.1 (+http://www.google.com/bot.html)",
            "Mozilla/5.0 (compatible; bingbot/2.0)",
            "facebookexternalhit/1.1",
            "WhatsApp/2.23.20.0 A",
            "Mozilla/5.0 (compatible; Yahoo! Slurp)",
            "Baiduspider",
            "curl/8.0",
            "",
        ],
    )
    def test_bots(self, ua):
        assert services.is_bot(ua)

    @pytest.mark.parametrize("ua", [IPHONE, DESKTOP, IPAD])
    def test_humans(self, ua):
        assert not services.is_bot(ua)

    def test_devices(self):
        assert services.detect_device(IPHONE) == "mobile"
        assert services.detect_device(DESKTOP) == "desktop"
        assert services.detect_device(IPAD) == "tablet"
        assert services.detect_device(ANDROID_TABLET) == "tablet"
        assert services.detect_device("") == ""

    def test_referer_domain(self):
        rf = RequestFactory()
        assert services.referer_domain(rf.get("/", HTTP_REFERER="https://www.facebook.com/x?y=1")) == "facebook.com"
        assert services.referer_domain(rf.get("/", HTTP_REFERER="http://testserver/autre")) == ""
        assert services.referer_domain(rf.get("/")) == ""

    def test_record_event_hashes_ip(self):
        profile = ProfileFactory()
        request = RequestFactory().get("/", HTTP_USER_AGENT=IPHONE, REMOTE_ADDR="41.202.1.2")
        event = services.record_event(profile, Event.Kind.VISIT, request)
        assert event.device == "mobile" and not event.is_bot
        assert len(event.visitor_hash) == 32 and "41.202" not in event.visitor_hash


class TestPixel:
    def test_records_visit_for_public_profile(self, client):
        profile = ProfileFactory()
        response = client.get(reverse("analytics:pixel", args=[profile.pk]), HTTP_USER_AGENT=IPHONE)
        assert response.status_code == 200
        assert response["Content-Type"] == "image/gif"
        assert response.content.startswith(b"GIF89a")
        assert "no-store" in response["Cache-Control"]
        assert Event.objects.get().kind == Event.Kind.VISIT

    def test_url_format(self):
        assert reverse("analytics:pixel", args=[12]) == "/p/12.gif"

    def test_unknown_private_suspended_ignored(self, client):
        private = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
        suspended = ProfileFactory(status=Profile.Status.SUSPENDED)
        for pk in (999999, private.pk, suspended.pk):
            response = client.get(reverse("analytics:pixel", args=[pk]), HTTP_USER_AGENT=IPHONE)
            assert response.status_code == 200
        assert not Event.objects.exists()

    def test_owner_visits_not_counted(self, client):
        profile = ProfileFactory()
        client.force_login(profile.user)
        client.get(reverse("analytics:pixel", args=[profile.pk]), HTTP_USER_AGENT=IPHONE)
        assert not Event.objects.exists()

    def test_bot_recorded_but_flagged(self, client):
        profile = ProfileFactory()
        client.get(reverse("analytics:pixel", args=[profile.pk]), HTTP_USER_AGENT="Googlebot/2.1")
        assert Event.objects.get().is_bot


class TestClick:
    def test_valid_click_returns_204(self, client):
        profile = ProfileFactory()
        response = client.post(reverse("analytics:click", args=[profile.pk, "whatsapp"]), HTTP_USER_AGENT=IPHONE)
        assert response.status_code == 204
        assert Event.objects.get().kind == Event.Kind.CLICK_WHATSAPP

    def test_csrf_exempt(self, settings):
        from django.test import Client

        profile = ProfileFactory()
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(reverse("analytics:click", args=[profile.pk, "call"]), HTTP_USER_AGENT=IPHONE)
        assert response.status_code == 204

    def test_invalid_kind_and_method(self, client):
        profile = ProfileFactory()
        assert client.post(f"/a/{profile.pk}/visit").status_code == 400  # not a click kind
        assert client.post(f"/a/{profile.pk}/hack").status_code == 400
        assert client.get(f"/a/{profile.pk}/call").status_code == 405
        assert not Event.objects.exists()

    def test_unknown_profile_silent(self, client):
        assert client.post("/a/999999/call").status_code == 204
        assert not Event.objects.exists()

    def test_rate_limited(self, client):
        profile = ProfileFactory()
        url = reverse("analytics:click", args=[profile.pk, "call"])
        statuses = [client.post(url, HTTP_USER_AGENT=IPHONE).status_code for _ in range(61)]
        assert statuses[-1] == 429
        assert Event.objects.count() == 60


def _event(profile, kind, when, *, bot=False, visitor="v1"):
    event = Event.objects.create(profile=profile, kind=kind, is_bot=bot, visitor_hash=visitor)
    Event.objects.filter(pk=event.pk).update(created_at=when)
    return event


class TestAggregation:
    def test_aggregate_day_excludes_bots_and_counts_uniques(self):
        profile = ProfileFactory()
        yesterday = timezone.localdate() - timedelta(days=1)
        noon = timezone.make_aware(datetime.combine(yesterday, time.min)) + timedelta(hours=12)
        _event(profile, "visit", noon, visitor="a")
        _event(profile, "visit", noon, visitor="a")
        _event(profile, "visit", noon, visitor="b")
        _event(profile, "visit", noon, bot=True, visitor="c")
        _event(profile, "call", noon, visitor="a")
        _event(profile, "visit", noon - timedelta(days=1), visitor="z")  # another day
        assert services.aggregate_day(yesterday) == 2
        visit = DailyStat.objects.get(profile=profile, day=yesterday, kind="visit")
        assert visit.total == 3 and visit.unique_visitors == 2
        assert DailyStat.objects.get(profile=profile, day=yesterday, kind="call").total == 1
        # Idempotent.
        services.aggregate_day(yesterday)
        assert DailyStat.objects.filter(day=yesterday).count() == 2

    def test_purge_after_13_months(self):
        profile = ProfileFactory()
        old = _event(profile, "visit", timezone.now() - timedelta(days=400))
        recent = _event(profile, "visit", timezone.now() - timedelta(days=300))
        assert services.purge_old_events() == 1
        assert not Event.objects.filter(pk=old.pk).exists()
        assert Event.objects.filter(pk=recent.pk).exists()

    def test_periodic_task(self):
        profile = ProfileFactory()
        _event(profile, "visit", timezone.now() - timedelta(days=1))
        result = tasks.aggregate_daily_stats.call_local()
        assert result["rows"] >= 1
        assert DailyStat.objects.filter(profile=profile, kind="visit").exists()


class TestStatsForProfile:
    def test_totals_and_series(self):
        profile = ProfileFactory()
        today = timezone.localdate()
        DailyStat.objects.create(
            profile=profile, day=today - timedelta(days=2), kind="visit", total=5, unique_visitors=4
        )
        DailyStat.objects.create(profile=profile, day=today - timedelta(days=2), kind="call", total=2)
        DailyStat.objects.create(profile=profile, day=today - timedelta(days=40), kind="visit", total=99)  # too old
        _event(profile, "visit", timezone.now(), visitor="x")
        _event(profile, "visit", timezone.now(), bot=True)
        stats = services.stats_for_profile(profile, days=30)
        assert stats["totals"]["visit"] == 6
        assert stats["totals"]["call"] == 2
        assert stats["contacts"] == 2
        assert stats["unique_visitors"] == 5
        assert len(stats["series"]) == 30
        assert stats["series"][-1]["day"] == today and stats["series"][-1]["visit"] == 1
        assert stats["series"][-3]["visit"] == 5
        assert set(stats["totals"]) == {k.value for k in Event.Kind}
