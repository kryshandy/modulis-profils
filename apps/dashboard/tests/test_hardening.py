"""Security review fixes in the pro space: IP hashes, Turnstile, refused accounts, suspended pages,
stats contract, editor writes through services, local SEO fields and query budgets."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OTPChallenge, User
from apps.analytics.models import DailyStat, Event
from apps.cards.models import Card, CardActivationAttempt
from apps.core.utils import hash_ip, rate_key_ip
from apps.dashboard import services as dash_services
from apps.profiles.models import Profile, ProfileService
from tests.factories import CardFactory, ProfileFactory, UserFactory

from .helpers import code_from, make_image

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}
STABLE_LOCAL_HASH = hash_ip(rate_key_ip("127.0.0.1"), daily=False)


def edit(section):
    return reverse("dashboard:edit", kwargs={"section": section})


def _fake_turnstile(monkeypatch, settings):
    settings.TURNSTILE_SITE_KEY = "site-key"
    settings.TURNSTILE_SECRET_KEY = "secret"

    class FakeResponse:
        def __init__(self, ok):
            self.ok = ok

        def json(self):
            return {"success": self.ok}

    monkeypatch.setattr("requests.post", lambda url, data, timeout: FakeResponse(data["response"] == "good"))


# --- 1. Stable security hash -----------------------------------------------------------------


def test_login_otp_uses_stable_security_hash(client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("dashboard:login"), {"phone": "690000011"})
    assert OTPChallenge.objects.get().ip_hash == STABLE_LOCAL_HASH


def test_card_link_uses_stable_security_hash(logged_client):
    card = CardFactory()
    logged_client.post(reverse("dashboard:card_link"), {"public_code": card.public_code, "activation_code": "X"})
    assert CardActivationAttempt.objects.get().ip_hash == STABLE_LOCAL_HASH


def test_report_uses_stable_security_hash(client):
    from apps.moderation.models import Report

    profile = ProfileFactory()
    client.post(reverse("moderation:report", args=[profile.slug]), {"reason": "spam"})
    assert Report.objects.get().reporter_ip_hash == STABLE_LOCAL_HASH


# --- 2. Turnstile ----------------------------------------------------------------------------


class TestTurnstile:
    def test_login_widget_and_check_before_sms(self, client, settings, monkeypatch, sms_outbox):
        _fake_turnstile(monkeypatch, settings)
        page = client.get(reverse("dashboard:login")).content.decode()
        assert 'data-sitekey="site-key"' in page and "challenges.cloudflare.com/turnstile" in page
        response = client.post(reverse("dashboard:login"), {"phone": "690000011", "cf-turnstile-response": "bad"})
        assert response.status_code == 200 and "anti-robot" in response.content.decode()
        assert not OTPChallenge.objects.exists() and sms_outbox == []
        response = client.post(reverse("dashboard:login"), {"phone": "690000011", "cf-turnstile-response": "good"})
        assert response.status_code == 302 and OTPChallenge.objects.count() == 1

    def test_login_without_site_key_has_no_widget(self, client):
        assert "cf-turnstile" not in client.get(reverse("dashboard:login")).content.decode()

    def test_card_link_requires_turnstile(self, logged_client, settings, monkeypatch):
        _fake_turnstile(monkeypatch, settings)
        assert 'data-sitekey="site-key"' in logged_client.get(reverse("dashboard:cards")).content.decode()
        card = CardFactory()
        data = {"public_code": card.public_code, "activation_code": "ABCD2345"}
        response = logged_client.post(reverse("dashboard:card_link"), {**data, "cf-turnstile-response": "bad"})
        assert "anti-robot" in response.content.decode()
        assert not CardActivationAttempt.objects.exists()
        response = logged_client.post(reverse("dashboard:card_link"), {**data, "cf-turnstile-response": "good"})
        assert response.status_code == 302
        card.refresh_from_db()
        assert card.status == Card.Status.ACTIVE


# --- 3. Refused accounts ---------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["is_staff", "inactive"])
def test_refused_account_gets_a_message_not_a_500(client, sms_outbox, django_capture_on_commit_callbacks, flag):
    phone = "+237690000011"
    UserFactory(phone=phone)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("dashboard:login"), {"phone": "690000011"})
    code = code_from(sms_outbox)
    # The account changes after the SMS was sent (made staff / disabled by an admin).
    User.objects.filter(phone=phone).update(**({"is_staff": True} if flag == "is_staff" else {"is_active": False}))
    response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": code})
    assert response.status_code == 200
    assert "support" in response.content.decode()
    assert "_auth_user_id" not in client.session


# --- 6. Suspended page -----------------------------------------------------------------------


@pytest.fixture
def suspended(client):
    profile = ProfileFactory(status=Profile.Status.SUSPENDED, suspended_reason="Arnaque (signalement #3)")
    client.force_login(profile.user)
    return profile


class TestSuspended:
    def test_can_view_with_banner(self, client, suspended):
        response = client.get(reverse("dashboard:home"))
        assert response.status_code == 200
        assert "Ta page est suspendue" in response.content.decode()
        assert client.get(edit("identite")).status_code == 200

    def test_every_change_is_refused_with_explanation(self, client, suspended, settings):
        settings.SUPPORT_WHATSAPP = "+237690000999"
        response = client.post(edit("identite"), {"display_name": "Nouveau nom", "kind": "person"})
        assert response.status_code == 403
        body = response.content.decode()
        assert "Arnaque (signalement #3)" in body and "wa.me/237690000999" in body
        suspended.refresh_from_db()
        assert suspended.display_name != "Nouveau nom"
        for name, kwargs, data in [
            ("dashboard:service_add", {}, {"title": "X"}),
            ("dashboard:link_add", {}, {"kind": "website", "url": "https://a.test"}),
            ("dashboard:tour_done", {}, {}),
            ("dashboard:settings", {}, {"action": "language", "language": "en"}),
            ("dashboard:settings", {}, {"action": "delete", "confirm": suspended.slug}),
        ]:
            assert client.post(reverse(name, kwargs=kwargs), data).status_code == 403, name
        assert not ProfileService.objects.exists()
        suspended.refresh_from_db()
        assert suspended.status == Profile.Status.SUSPENDED and suspended.language == "fr"

    def test_htmx_change_gets_403_and_error_toast(self, client, suspended):
        response = client.post(edit("presentation"), {"bio": "x"}, **HX)
        assert response.status_code == 403
        assert json.loads(response["HX-Trigger"])["toast"]["kind"] == "error"

    def test_card_linking_refused(self, client, suspended):
        card = CardFactory()
        response = client.post(
            reverse("dashboard:card_link"), {"public_code": card.public_code, "activation_code": "ABCD2345"}
        )
        assert response.status_code == 403
        card.refresh_from_db()
        assert card.status == Card.Status.STOCK
        assert not CardActivationAttempt.objects.exists()

    def test_switching_to_another_page_is_allowed(self, client, suspended):
        other = ProfileFactory(user=suspended.user)
        response = client.post(reverse("dashboard:switch_profile"), {"profile_id": other.pk})
        assert response.status_code == 302
        assert client.session["dashboard_profile_id"] == other.pk

    def test_onboarding_never_creates_a_second_page(self, client, suspended):
        response = client.post(
            reverse("dashboard:onboarding", kwargs={"step": "nom"}), {"display_name": "Autre", "kind": "person"}
        )
        assert response.status_code == 403
        assert Profile.objects.filter(user=suspended.user).count() == 1
        assert client.get(reverse("dashboard:onboarding", kwargs={"step": "fin"})).status_code == 403


# --- 7 & 14. Stats contract ------------------------------------------------------------------


def _real_stats(profile):
    today = timezone.localdate()
    DailyStat.objects.create(profile=profile, day=today - timedelta(days=1), kind="visit", total=7, unique_visitors=5)
    DailyStat.objects.create(profile=profile, day=today - timedelta(days=1), kind="whatsapp", total=3)
    DailyStat.objects.create(profile=profile, day=today - timedelta(days=2), kind="call", total=2)
    Event.objects.create(profile=profile, kind="scan", visitor_hash="v", device="mobile")


class TestStatsContract:
    def test_adapter_returns_analytics_output_unchanged(self, profile):
        from apps.analytics.services import stats_for_profile

        _real_stats(profile)
        assert dash_services.stats_30_days(profile) == stats_for_profile(profile, days=30)

    def test_stats_page_with_real_output(self, logged_client, profile):
        _real_stats(profile)
        response = logged_client.get(reverse("dashboard:stats"))
        assert response.status_code == 200
        rows = {row["kind"]: row for row in response.context["rows"]}
        assert rows["visit"]["value"] == 7 and rows["visit"]["pct"] == 100
        assert rows["whatsapp"]["value"] == 3 and rows["scan"]["value"] == 1
        assert response.context["stats"]["contacts"] == 5
        assert response.context["stats"]["unique_visitors"] == 5
        assert len(response.context["daily"]) == 30
        body = response.content.decode()
        assert "visiteurs différents" in body

    def test_paid_plan_sees_daily_chart(self, logged_client, profile):
        from apps.billing.models import Plan
        from apps.billing.services import grant_plan

        _real_stats(profile)
        grant_plan(profile, Plan.objects.get(code="pro"))
        body = logged_client.get(reverse("dashboard:stats")).content.decode()
        assert 'class="daily"' in body and body.count('class="daily__bar"') == 30

    def test_home_with_real_output(self, logged_client, profile):
        _real_stats(profile)
        response = logged_client.get(reverse("dashboard:home"))
        stats = response.context["stats"]
        assert stats["totals"]["visit"] == 7 and stats["contacts"] == 5
        body = response.content.decode()
        assert ">7<" in body and ">5<" in body

    def test_database_error_degrades_gracefully(self, logged_client, profile, monkeypatch):
        def broken(*args, **kwargs):
            raise DatabaseError("boom")

        monkeypatch.setattr("apps.analytics.services.stats_for_profile", broken)
        response = logged_client.get(reverse("dashboard:stats"))
        assert response.status_code == 200 and response.context["available"] is False
        assert logged_client.get(reverse("dashboard:home")).status_code == 200


# --- 8. Editor writes through profiles.services ----------------------------------------------


class TestEditorUsesServices:
    def test_views_call_profile_services(self, logged_client, profile, monkeypatch):
        from apps.profiles import services as profiles

        calls = []
        real = profiles.update_profile

        def spy(p, **fields):
            calls.append(sorted(fields))
            return real(p, **fields)

        monkeypatch.setattr(profiles, "update_profile", spy)
        logged_client.post(edit("identite"), {"display_name": "Paul Mbarga", "kind": "person"})
        logged_client.post(reverse("dashboard:settings"), {"action": "language", "language": "en"})
        assert ["display_name", "kind"] in calls and ["language"] in calls

    def test_foreign_items_are_404(self, logged_client):
        other = ProfileFactory()
        service = ProfileService.objects.create(profile=other, title="Pas à toi")
        for name in ("service_update", "service_delete", "service_move"):
            assert (
                logged_client.post(reverse(f"dashboard:{name}", args=[service.pk]), {"title": "x"}).status_code == 404
            )
        service.refresh_from_db()
        assert service.title == "Pas à toi"

    def test_email_through_accounts_service(self, logged_client, profile):
        logged_client.post(reverse("dashboard:settings"), {"action": "email", "email": " pro@exemple.test "})
        profile.user.refresh_from_db()
        assert profile.user.email == "pro@exemple.test"

    def test_photo_has_size_and_variants(self, logged_client, profile):
        logged_client.post(edit("identite"), {"action": "photo", "photo": make_image()}, **HX)
        profile.refresh_from_db()
        assert profile.photo_width == 800 and profile.photo_height == 600


# --- 10. Local SEO in the editor ---------------------------------------------------------------


class TestLocalSeoEditor:
    def test_hours_section_renders_with_presets(self, logged_client):
        body = logged_client.get(edit("horaires")).content.decode()
        assert 'name="mo_open"' in body and 'value="mon_sat_8_18"' in body and "Lun–Sam 8h–18h" in body

    def test_preset(self, logged_client, profile):
        response = logged_client.post(edit("horaires"), {"preset": "mon_sat_8_18"})
        assert response.status_code == 302
        profile.refresh_from_db()
        assert set(profile.opening_hours) == {"mo", "tu", "we", "th", "fr", "sa"}
        assert profile.opening_hours["sa"] == [["08:00", "18:00"]]

    def test_unknown_preset_404(self, logged_client):
        assert logged_client.post(edit("horaires"), {"preset": "nope"}).status_code == 404

    def test_per_day_form(self, logged_client, profile):
        data = {"mo_open": "on", "mo_from": "07:30", "mo_to": "12:00", "su_open": "", "su_from": "", "su_to": ""}
        response = logged_client.post(edit("horaires"), data, **HX)
        assert json.loads(response["HX-Trigger"])["toast"]["kind"] == "success"
        profile.refresh_from_db()
        assert profile.opening_hours == {"mo": [["07:30", "12:00"]]}
        body = logged_client.get(edit("horaires")).content.decode()
        assert 'value="07:30"' in body

    def test_per_day_form_errors(self, logged_client, profile):
        response = logged_client.post(edit("horaires"), {"mo_open": "on", "mo_from": "18:00", "mo_to": "08:00"}, **HX)
        assert json.loads(response["HX-Trigger"])["toast"]["kind"] == "error"
        profile.refresh_from_db()
        assert profile.opening_hours == {}

    def test_contact_position_and_geolocation_button(self, logged_client, profile):
        body = logged_client.get(edit("contact")).content.decode()
        assert "data-geolocate" in body and 'data-geo="lat"' in body and 'data-geo="lng"' in body
        data = {"whatsapp": "690000001", "latitude": "4.0510564", "longitude": "9.7678687"}
        assert logged_client.post(edit("contact"), data).status_code == 302
        profile.refresh_from_db()
        assert profile.latitude == Decimal("4.051056") and profile.longitude == Decimal("9.767869")

    def test_contact_position_needs_both_values(self, logged_client, profile):
        response = logged_client.post(edit("contact"), {"whatsapp": "690000001", "latitude": "4.05"})
        assert response.status_code == 200 and "ET la longitude" in response.content.decode()
        response = logged_client.post(edit("contact"), {"whatsapp": "690000001", "latitude": "95", "longitude": "9"})
        assert response.status_code == 200
        profile.refresh_from_db()
        assert profile.latitude is None

    def test_price_range_in_metier(self, logged_client, profile):
        data = {"trade_choice": str(profile.trade_id), "city": profile.city_id, "price_range": "5 000–50 000 FCFA"}
        assert logged_client.post(edit("metier"), data).status_code == 302
        profile.refresh_from_db()
        assert profile.price_range == "5 000–50 000 FCFA"


# --- 13. Query budget ------------------------------------------------------------------------


def test_dashboard_home_query_budget(logged_client, profile, django_assert_max_num_queries):
    for i in range(5):
        ProfileService.objects.create(profile=profile, title=f"S{i}")
    _real_stats(profile)
    logged_client.get(reverse("dashboard:home"))  # warm the session
    with django_assert_max_num_queries(16):
        assert logged_client.get(reverse("dashboard:home")).status_code == 200
