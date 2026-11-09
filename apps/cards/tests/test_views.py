import re

import pytest
from django.urls import reverse

from apps.accounts.models import OTPChallenge, User
from apps.analytics.models import Event
from apps.cards import services
from apps.cards.models import Card, CardActivationAttempt
from apps.profiles.models import Profile
from tests.factories import CardFactory, CityFactory, ProfileFactory, TradeFactory, UserFactory

pytestmark = pytest.mark.django_db

PHONE_RAW = "690 00 00 42"
PHONE = "+237690000042"
GOOD_CODE = "ABCD2345"  # CardFactory's activation code


def _sms_code(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1].body).group(1)


def _assert_protected(response):
    assert "no-store" in response["Cache-Control"]
    assert "noindex" in response["X-Robots-Tag"]


# --- Scan ------------------------------------------------------------------------------------


class TestScan:
    def test_unknown_code_is_404(self, client):
        response = client.get("/c/ZZZZZZZ")
        assert response.status_code == 404
        assert "Carte introuvable" in response.content.decode()
        _assert_protected(response)

    def test_active_card_redirects_302_and_counts_scan(self, client):
        profile = ProfileFactory()
        card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
        response = client.get(f"/c/{card.public_code.lower()}", HTTP_USER_AGENT="Mozilla/5.0 (iPhone) Mobile")
        assert response.status_code == 302  # never 301 (ADR-0003)
        assert response["Location"] == f"/{profile.slug}"
        _assert_protected(response)
        card.refresh_from_db()
        assert card.scan_count == 1 and card.last_scan_at
        event = Event.objects.get()
        assert event.kind == Event.Kind.SCAN and event.card == card and event.profile == profile
        assert event.device == "mobile" and not event.is_bot

    def test_stock_and_sold_cards_go_to_activation(self, client):
        for status in (Card.Status.STOCK, Card.Status.SOLD):
            card = CardFactory(status=status)
            response = client.get(f"/c/{card.public_code}")
            assert response.status_code == 302
            assert response["Location"] == reverse("cards:activate", args=[card.public_code])
            _assert_protected(response)

    def test_disabled_card_page_links_public_profile(self, client):
        profile = ProfileFactory()
        card = CardFactory(status=Card.Status.DISABLED, profile=profile, disabled_reason="lost")
        response = client.get(f"/c/{card.public_code}")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Carte désactivée" in content and f'href="/{profile.slug}"' in content
        _assert_protected(response)

    def test_disabled_card_hides_private_profile(self, client):
        profile = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
        card = CardFactory(status=Card.Status.DISABLED, profile=profile)
        response = client.get(f"/c/{card.public_code}")
        assert f"/{profile.slug}" not in response.content.decode()

    def test_private_profile_shows_minimal_contact_page(self, client):
        profile = ProfileFactory(visibility=Profile.Visibility.PRIVATE)
        card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
        response = client.get(f"/c/{card.public_code}")
        assert response.status_code == 200
        content = response.content.decode()
        assert profile.display_name in content and "tel:" in content
        assert 'content="noindex' in content
        _assert_protected(response)
        assert Event.objects.filter(kind=Event.Kind.SCAN).count() == 1

    def test_suspended_profile_is_unavailable(self, client):
        profile = ProfileFactory(status=Profile.Status.SUSPENDED)
        card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
        response = client.get(f"/c/{card.public_code}")
        assert response.status_code == 404
        assert "indisponible" in response.content.decode()
        assert not Event.objects.exists()

    def test_scan_rate_limit_per_ip(self, client):
        card = CardFactory(status=Card.Status.ACTIVE, profile=ProfileFactory())
        statuses = [client.get(f"/c/{card.public_code}").status_code for _ in range(61)]
        assert statuses[:60] == [302] * 60
        assert statuses[60] == 429

    def test_unknown_code_enumeration_is_blocked(self, client):
        card = CardFactory(status=Card.Status.ACTIVE, profile=ProfileFactory())
        for i in range(21):
            assert client.get(f"/c/ZZZZZ{i:02d}").status_code == 404
        # The IP is now blocked, even for a valid code.
        assert client.get(f"/c/{card.public_code}").status_code == 429
        # Another IP is not affected.
        assert client.get(f"/c/{card.public_code}", REMOTE_ADDR="10.0.0.9").status_code == 302


# --- Activation ------------------------------------------------------------------------------


class TestActivation:
    def _url(self, card):
        return reverse("cards:activate", args=[card.public_code])

    def _pass_code(self, client, card):
        response = client.post(self._url(card), {"activation_code": GOOD_CODE.lower()})
        assert response.status_code == 302
        return response

    def _pass_phone(self, client, card, capture):
        with capture(execute=True):
            response = client.post(self._url(card), {"phone": PHONE_RAW})
        assert response.status_code == 302, response.content.decode()
        return response

    def test_get_shows_code_step(self, client):
        card = CardFactory()
        response = client.get(self._url(card))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="activation_code"' in content and "Étape 1 sur 4" in content
        _assert_protected(response)
        assert "cf-turnstile" not in content  # disabled in tests

    def test_full_flow_new_account(self, client, sms_outbox, django_capture_on_commit_callbacks):
        card = CardFactory()
        trade, city = TradeFactory(), CityFactory()
        self._pass_code(client, card)
        assert 'name="phone"' in client.get(self._url(card)).content.decode()
        self._pass_phone(client, card, django_capture_on_commit_callbacks)
        assert len(sms_outbox) == 1 and sms_outbox[0].to == PHONE
        assert OTPChallenge.objects.get().purpose == OTPChallenge.Purpose.CARD_ACTIVATION
        response = client.post(self._url(card), {"code": _sms_code(sms_outbox)})
        assert response.status_code == 302
        page = client.get(self._url(card)).content.decode()
        assert 'name="display_name"' in page
        response = client.post(
            self._url(card),
            {"action": "create", "display_name": "Paul Test", "trade": trade.pk, "city": city.pk},
        )
        assert response.status_code == 302
        assert response["Location"] == "/espace/"  # dashboard:onboarding not wired yet → fallback
        card.refresh_from_db()
        user = User.objects.get(phone=PHONE)
        assert card.status == Card.Status.ACTIVE
        assert card.profile.user == user and card.profile.display_name == "Paul Test"
        assert card.profile.trade == trade and card.profile.city == city
        assert user.phone_verified_at is not None
        assert int(client.session["_auth_user_id"]) == user.pk
        assert "card_activation:" + card.public_code not in client.session

    def test_existing_account_links_existing_profile(self, client, sms_outbox, django_capture_on_commit_callbacks):
        owner = UserFactory(phone=PHONE)
        profile = ProfileFactory(user=owner)
        card = CardFactory(status=Card.Status.SOLD)
        self._pass_code(client, card)
        self._pass_phone(client, card, django_capture_on_commit_callbacks)
        client.post(self._url(card), {"code": _sms_code(sms_outbox)})
        page = client.get(self._url(card)).content.decode()
        assert f"/{profile.slug}" in page
        assert "Créer une nouvelle page" not in page  # free plan: one page only
        response = client.post(self._url(card), {"action": "choose", "profile": profile.pk})
        assert response.status_code == 302
        card.refresh_from_db()
        assert card.status == Card.Status.ACTIVE and card.profile == profile
        assert Profile.objects.filter(user=owner).count() == 1  # never a duplicate
        assert int(client.session["_auth_user_id"]) == owner.pk

    def test_other_users_profile_cannot_be_chosen(self, client, sms_outbox, django_capture_on_commit_callbacks):
        ProfileFactory(user=UserFactory(phone=PHONE))
        stranger = ProfileFactory()
        card = CardFactory()
        self._pass_code(client, card)
        self._pass_phone(client, card, django_capture_on_commit_callbacks)
        client.post(self._url(card), {"code": _sms_code(sms_outbox)})
        response = client.post(self._url(card), {"action": "choose", "profile": stranger.pk})
        assert response.status_code == 200
        card.refresh_from_db()
        assert card.status == Card.Status.STOCK

    def test_wrong_activation_code_sends_no_sms(self, client, sms_outbox, django_capture_on_commit_callbacks):
        card = CardFactory()
        response = client.post(self._url(card), {"activation_code": "WRONG999"})
        assert response.status_code == 200
        assert "Code d&#x27;activation incorrect" in response.content.decode()
        # Trying to skip the code step: the phone step is not reachable.
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(self._url(card), {"phone": PHONE_RAW})
        assert response.status_code == 200
        assert sms_outbox == []
        assert not OTPChallenge.objects.exists()
        assert CardActivationAttempt.objects.filter(card=card, success=False).count() == 1

    def test_activation_attempts_limited_and_committed(self, client, settings):
        card = CardFactory()
        for _ in range(settings.CARD_ACTIVATION_MAX_ATTEMPTS_PER_IP_HOUR):
            client.post(self._url(card), {"activation_code": "WRONG999"})
        response = client.post(self._url(card), {"activation_code": GOOD_CODE})
        assert response.status_code == 200
        assert "Trop d&#x27;essais" in response.content.decode()
        assert CardActivationAttempt.objects.filter(card=card).count() == 5

    def test_wrong_otp_counts_attempt(self, client, sms_outbox, django_capture_on_commit_callbacks):
        card = CardFactory()
        self._pass_code(client, card)
        self._pass_phone(client, card, django_capture_on_commit_callbacks)
        wrong = "000000" if _sms_code(sms_outbox) != "000000" else "111111"
        response = client.post(self._url(card), {"code": wrong})
        assert response.status_code == 200
        assert "Code incorrect" in response.content.decode()
        assert OTPChallenge.objects.get().attempts == 1

    def test_invalid_phone_rerenders(self, client):
        card = CardFactory()
        self._pass_code(client, card)
        response = client.post(self._url(card), {"phone": "123"})
        assert response.status_code == 200
        assert "pas valide" in response.content.decode()

    def test_restart_goes_back_to_code(self, client):
        card = CardFactory()
        self._pass_code(client, card)
        client.post(self._url(card), {"action": "restart"})
        assert 'name="activation_code"' in client.get(self._url(card)).content.decode()

    def test_active_card_activation_redirects_to_scan(self, client):
        card = CardFactory(status=Card.Status.ACTIVE, profile=ProfileFactory())
        response = client.get(self._url(card))
        assert response.status_code == 302
        assert response["Location"] == reverse("cards:scan", args=[card.public_code])

    def test_unknown_card_activation_404(self, client):
        assert client.get("/c/ZZZZZZZ/activer").status_code == 404

    def test_turnstile_required_when_enabled(self, client, settings, monkeypatch):
        settings.TURNSTILE_SITE_KEY = "site-key"
        settings.TURNSTILE_SECRET_KEY = "secret"
        calls = []

        class FakeResponse:
            def __init__(self, ok):
                self.ok = ok

            def json(self):
                return {"success": self.ok}

        def fake_post(url, data, timeout):
            calls.append(data)
            return FakeResponse(data["response"] == "good-token")

        monkeypatch.setattr("requests.post", fake_post)
        card = CardFactory()
        page = client.get(self._url(card)).content.decode()
        assert 'data-sitekey="site-key"' in page and "challenges.cloudflare.com/turnstile" in page
        response = client.post(self._url(card), {"activation_code": GOOD_CODE, "cf-turnstile-response": "bad"})
        assert response.status_code == 200 and "anti-robot" in response.content.decode()
        assert not CardActivationAttempt.objects.exists()  # rejected before even checking the code
        response = client.post(self._url(card), {"activation_code": GOOD_CODE, "cf-turnstile-response": "good-token"})
        assert response.status_code == 302
        assert calls[-1]["secret"] == "secret"


def test_verify_turnstile_disabled_by_default():
    assert services.verify_turnstile("") is True


def test_mark_sold_only_from_stock():
    card = CardFactory()
    assert services.mark_sold(card)
    card.refresh_from_db()
    assert card.status == Card.Status.SOLD and card.sold_at
    assert not services.mark_sold(card)
