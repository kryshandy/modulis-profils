"""Card activation with WhatsApp / Firebase SMS and the platform switches (ADR-0009)."""

import pytest
from django.urls import reverse

from apps.accounts.models import OTPChallenge, User
from apps.accounts.otp import whatsapp
from apps.accounts.tests.otp_helpers import (
    FakeResponse,
    FirebaseKeys,
    configure_firebase,
    configure_whatsapp,
    set_switches,
)
from apps.cards.models import Card
from tests.factories import CardFactory, ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db

PHONE_RAW = "690 00 00 88"
PHONE = "+237690000088"
GOOD_CODE = "ABCD2345"


def _url(card):
    return reverse("cards:activate", args=[card.public_code])


@pytest.fixture
def wa_sent(settings, monkeypatch):
    configure_whatsapp(settings)
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        return FakeResponse(200, {"messages": [{"id": "wamid.X"}]})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    return sent


@pytest.fixture
def keys(settings, monkeypatch):
    configure_firebase(settings)
    k = FirebaseKeys()
    k.install(monkeypatch)
    return k


class TestCardActivationSwitch:
    def test_unactivated_card_shows_unavailable(self, client):
        set_switches(card_activation_enabled=False)
        for status in (Card.Status.STOCK, Card.Status.SOLD):
            card = CardFactory(status=status)
            response = client.get(f"/c/{card.public_code}")
            assert response.status_code == 503
            assert "activation des cartes est momentanément indisponible" in response.content.decode()
            assert "noindex" in response["X-Robots-Tag"]
            assert client.get(_url(card)).status_code == 503

    def test_active_card_still_redirects(self, client):
        set_switches(card_activation_enabled=False)
        profile = ProfileFactory()
        card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
        response = client.get(f"/c/{card.public_code}")
        assert response.status_code == 302 and response["Location"] == f"/{profile.slug}"


class TestPageCreationSwitch:
    def test_new_phone_not_revealed_before_the_code(self, client, sms_outbox, django_capture_on_commit_callbacks):
        """Whether a number has a page is only said after the OTP (no account enumeration with a card)."""
        set_switches(page_creation_enabled=False)
        card = CardFactory()
        client.post(_url(card), {"activation_code": GOOD_CODE})
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(_url(card), {"phone": PHONE_RAW})
        assert response.status_code == 302
        assert OTPChallenge.objects.filter(phone=PHONE).exists() and len(sms_outbox) == 1
        assert "suspendue" not in client.get(_url(card)).content.decode()
        code = sms_outbox[-1].body.split("code est ")[1][:6]
        client.post(_url(card), {"code": code})
        response = client.get(_url(card))
        assert response.status_code == 503
        assert "création de nouvelles pages est momentanément suspendue" in response.content.decode()
        card.refresh_from_db()
        assert card.status != Card.Status.ACTIVE

    def test_existing_page_can_still_get_the_card_but_no_new_page(
        self, client, sms_outbox, django_capture_on_commit_callbacks
    ):
        profile = ProfileFactory(user=UserFactory(phone=PHONE))
        set_switches(page_creation_enabled=False)
        card = CardFactory()
        client.post(_url(card), {"activation_code": GOOD_CODE})
        with django_capture_on_commit_callbacks(execute=True):
            client.post(_url(card), {"phone": PHONE_RAW})
        code = sms_outbox[-1].body.split("code est ")[1][:6]
        client.post(_url(card), {"code": code})
        page = client.get(_url(card)).content.decode()
        assert "Créer une nouvelle page" not in page
        response = client.post(_url(card), {"action": "create", "display_name": "Autre Page"})
        assert response.status_code == 302 and profile.user.profiles.count() == 1
        response = client.post(_url(card), {"action": "choose", "profile": str(profile.pk)})
        assert response.status_code == 302
        card.refresh_from_db()
        assert card.status == Card.Status.ACTIVE and card.profile == profile

    def test_profile_step_defence(self, client, sms_outbox, django_capture_on_commit_callbacks):
        card = CardFactory()
        client.post(_url(card), {"activation_code": GOOD_CODE})
        with django_capture_on_commit_callbacks(execute=True):
            client.post(_url(card), {"phone": PHONE_RAW})
        code = sms_outbox[-1].body.split("code est ")[1][:6]
        client.post(_url(card), {"code": code})
        set_switches(page_creation_enabled=False)  # switched off in the meantime
        response = client.get(_url(card))
        assert response.status_code == 503
        assert "momentanément suspendue" in response.content.decode()


class TestCardChannels:
    def test_phone_step_offers_channels(self, client, wa_sent, keys):
        card = CardFactory()
        client.post(_url(card), {"activation_code": GOOD_CODE})
        page = client.get(_url(card)).content.decode()
        assert "Recevoir le code par WhatsApp" in page and "Recevoir le code par SMS" in page
        assert 'value="whatsapp" checked' in page
        assert "<select" not in page  # the channel field is never rendered as a select

    def test_whatsapp_flow(self, client, wa_sent, django_capture_on_commit_callbacks):
        card = CardFactory()
        client.post(_url(card), {"activation_code": GOOD_CODE})
        with django_capture_on_commit_callbacks(execute=True):
            client.post(_url(card), {"phone": PHONE_RAW, "channel": "whatsapp"})
        assert wa_sent[0]["to"] == "237690000088"
        assert "Ouvre WhatsApp" in client.get(_url(card)).content.decode()
        code = wa_sent[0]["template"]["components"][0]["parameters"][0]["text"]
        response = client.post(_url(card), {"code": code})
        assert response.status_code == 302
        assert 'name="display_name"' in client.get(_url(card)).content.decode()

    def test_firebase_flow(self, client, keys):
        card = CardFactory()
        client.post(_url(card), {"activation_code": GOOD_CODE})
        response = client.post(_url(card), {"phone": PHONE_RAW, "channel": "firebase_sms"})
        assert response.status_code == 302
        page = client.get(_url(card)).content.decode()
        assert 'data-autostart="1"' in page and f'data-verify-url="{_url(card)}"' in page
        assert "data-firebase-form" in page
        bad = client.post(_url(card), {"action": "firebase", "id_token": keys.token("+237690000089")})
        assert bad.status_code == 400 and "no-store" in bad["Cache-Control"]
        response = client.post(_url(card), {"action": "firebase", "id_token": keys.token(PHONE)})
        assert response.status_code == 200 and response.json() == {"redirect": _url(card)}
        assert 'name="display_name"' in client.get(_url(card)).content.decode()
        response = client.post(_url(card), {"action": "create", "display_name": "Firebase Test"})
        assert response.status_code == 302
        assert User.objects.get(phone=PHONE).profiles.count() == 1

    def test_firebase_action_refused_on_server_channel(self, client, keys, wa_sent):
        card = CardFactory()
        client.post(_url(card), {"activation_code": GOOD_CODE})
        client.post(_url(card), {"phone": PHONE_RAW, "channel": "whatsapp"})
        response = client.post(_url(card), {"action": "firebase", "id_token": keys.token(PHONE)})
        assert response.status_code == 400

    def test_firebase_never_before_activation_code(self, client, keys):
        card = CardFactory()
        response = client.post(_url(card), {"action": "firebase", "id_token": keys.token(PHONE)})
        assert response.status_code == 200  # stays on the code step, nothing verified
        assert not OTPChallenge.objects.exists()
