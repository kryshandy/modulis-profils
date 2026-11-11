"""Login by WhatsApp / Firebase SMS and the platform switches on the Espace pro (ADR-0009)."""

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
from apps.platform.models import BlockedPhone
from tests.factories import ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db

PHONE_RAW = "690 00 00 77"
PHONE = "+237690000077"


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


def _wa_code(sent) -> str:
    return sent[-1]["template"]["components"][0]["parameters"][0]["text"]


class TestLoginPage:
    def test_channel_choice_whatsapp_recommended_and_preselected(self, client, wa_sent, keys):
        body = client.get(reverse("dashboard:login")).content.decode()
        assert "Recevoir le code par WhatsApp" in body and "Recevoir le code par SMS" in body
        assert 'value="whatsapp" checked' in body
        assert "Recommandé" in body
        assert "console" not in body  # dev channel only when nothing real is available

    def test_default_channel_from_admin(self, client, wa_sent, keys):
        set_switches(otp_default_channel="firebase_sms")
        body = client.get(reverse("dashboard:login")).content.decode()
        assert 'value="firebase_sms" checked' in body

    def test_single_channel_is_a_hidden_input(self, client, wa_sent):
        body = client.get(reverse("dashboard:login")).content.decode()
        assert 'type="hidden" name="channel" value="whatsapp"' in body
        assert "sur WhatsApp" in body

    def test_no_inline_script(self, client, wa_sent, keys):
        body = client.get(reverse("dashboard:login")).content.decode()
        assert "<script>" not in body and "onclick" not in body

    def test_login_disabled(self, client):
        set_switches(login_enabled=False)
        response = client.get(reverse("dashboard:login"))
        body = response.content.decode()
        assert "connexion est momentanément indisponible" in body
        assert 'name="phone"' not in body
        response = client.post(reverse("dashboard:login"), {"phone": PHONE_RAW})
        assert response.status_code == 200 and not OTPChallenge.objects.exists()

    def test_no_channel_available(self, client, settings):
        settings.SMS_BACKEND = "apps.accounts.sms.ConsoleSmsBackend"
        body = client.get(reverse("dashboard:login")).content.decode()
        assert "envoi de codes est momentanément indisponible" in body

    def test_signups_closed_message(self, client):
        set_switches(signups_enabled=False)
        response = client.post(reverse("dashboard:login"), {"phone": PHONE_RAW})
        assert "inscriptions sont momentanément fermées" in response.content.decode()
        assert not OTPChallenge.objects.exists()

    def test_blocked_phone(self, client):
        BlockedPhone.objects.create(phone=PHONE, reason="fraude")
        response = client.post(reverse("dashboard:login"), {"phone": PHONE_RAW})
        assert "utiliser ce numéro pour le moment" in response.content.decode()

    def test_disabled_channel_cannot_be_forced(self, client, wa_sent, keys):
        set_switches(otp_whatsapp_enabled=False)
        response = client.post(reverse("dashboard:login"), {"phone": PHONE_RAW, "channel": "whatsapp"})
        assert response.status_code == 200 and not OTPChallenge.objects.exists()
        assert wa_sent == []


class TestWhatsAppLogin:
    def test_full_flow(self, client, wa_sent, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(reverse("dashboard:login"), {"phone": PHONE_RAW, "channel": "whatsapp"})
        assert response["Location"] == reverse("dashboard:verify")
        assert wa_sent[0]["to"] == "237690000077"
        page = client.get(reverse("dashboard:verify")).content.decode()
        assert "Ouvre WhatsApp" in page and "Code reçu sur WhatsApp" in page
        assert "firebase-otp" not in page
        response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": _wa_code(wa_sent)})
        assert response["Location"] == reverse("dashboard:onboarding", kwargs={"step": "nom"})
        assert User.objects.filter(phone=PHONE).exists()

    def test_delivery_failure_shown_with_sms_alternative(
        self, client, settings, monkeypatch, keys, django_capture_on_commit_callbacks
    ):
        configure_whatsapp(settings)
        monkeypatch.setattr(whatsapp.requests, "post", lambda *a, **k: FakeResponse(400, {"error": {"code": 131026}}))
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("dashboard:login"), {"phone": PHONE_RAW, "channel": "whatsapp"})
        page = client.get(reverse("dashboard:verify")).content.decode()
        assert "pas de compte WhatsApp" in page
        assert "Recevoir plutôt le code par SMS" in page
        # Switching channel does not wait for the 60 s resend delay.
        response = client.post(reverse("dashboard:verify"), {"action": "switch", "channel": "firebase_sms"})
        assert response.status_code == 302
        assert client.session["otp_channel"] == "firebase_sms"
        assert OTPChallenge.objects.filter(phone=PHONE, channel="firebase_sms").exists()


class TestFirebaseLogin:
    def _start(self, client):
        response = client.post(reverse("dashboard:login"), {"phone": PHONE_RAW, "channel": "firebase_sms"})
        assert response["Location"] == reverse("dashboard:verify")

    def test_verify_page_has_config_in_data_attributes(self, client, keys):
        self._start(client)
        page = client.get(reverse("dashboard:verify")).content.decode()
        assert "Tu vas recevoir un SMS" in page
        assert 'data-project-id="modulis-test"' in page and 'data-api-key="public-api-key"' in page
        assert 'data-autostart="1"' in page
        assert f'data-verify-url="{reverse("dashboard:firebase_verify")}"' in page
        assert 'type="module"' in page and "js/firebase-otp.js" in page
        assert "<script>" not in page
        # Reloading never re-sends on its own: the resend goes through our checks again.
        assert 'data-autostart="0"' in client.get(reverse("dashboard:verify")).content.decode()

    def test_typed_code_without_js_is_refused(self, client, keys):
        self._start(client)
        response = client.post(reverse("dashboard:verify"), {"action": "verify", "code": "123456"})
        assert "Active JavaScript" in response.content.decode()
        assert "_auth_user_id" not in client.session

    def test_valid_token_logs_in(self, client, keys):
        ProfileFactory(user__phone=PHONE)
        self._start(client)
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE)})
        assert response.status_code == 200
        assert response.json() == {"redirect": reverse("dashboard:home")}
        assert client.session["_auth_user_id"] == str(User.objects.get(phone=PHONE).pk)
        assert "otp_phone" not in client.session

    def test_new_account_goes_to_onboarding(self, client, keys):
        self._start(client)
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE)})
        assert response.json()["redirect"] == reverse("dashboard:onboarding", kwargs={"step": "nom"})

    def test_token_for_another_phone(self, client, keys):
        self._start(client)
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token("+237690000078")})
        assert response.status_code == 400 and "error" in response.json()
        assert "_auth_user_id" not in client.session

    def test_invalid_token(self, client, keys):
        self._start(client)
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE, aud="x")})
        assert response.status_code == 400

    def test_without_pending_session(self, client, keys):
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE)})
        assert response.status_code == 400

    def test_session_on_whatsapp_cannot_use_firebase(self, client, keys, wa_sent):
        client.post(reverse("dashboard:login"), {"phone": PHONE_RAW, "channel": "whatsapp"})
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE)})
        assert response.status_code == 400

    def test_get_not_allowed(self, client, keys):
        assert client.get(reverse("dashboard:firebase_verify")).status_code == 405

    def test_csrf_required(self, keys):
        from django.test import Client

        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(reverse("dashboard:firebase_verify"), {"id_token": "x"})
        assert response.status_code == 403

    def test_staff_refused(self, client, keys):
        self._start(client)
        UserFactory(phone=PHONE, is_staff=True)
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE)})
        assert response.status_code == 400 and "_auth_user_id" not in client.session

    def test_signups_closed_after_send(self, client, keys):
        self._start(client)
        set_switches(signups_enabled=False)
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE)})
        assert response.status_code == 400
        assert "inscriptions" in response.json()["error"]

    def test_rate_limited(self, client, keys):
        self._start(client)
        for _ in range(10):
            client.post(reverse("dashboard:firebase_verify"), {"id_token": "bad"})
        response = client.post(reverse("dashboard:firebase_verify"), {"id_token": keys.token(PHONE)})
        assert response.status_code == 429


class TestOnboardingPageCreation:
    def test_page_creation_closed(self, client):
        user = UserFactory()
        client.force_login(user)
        set_switches(page_creation_enabled=False)
        url = reverse("dashboard:onboarding", kwargs={"step": "nom"})
        assert "momentanément suspendue" in client.get(url).content.decode()
        response = client.post(url, {"display_name": "Jean Test", "kind": "person"})
        assert response.status_code == 200
        assert "momentanément suspendue" in response.content.decode()
        assert not user.profiles.exists()

    def test_existing_page_still_editable(self, logged_client, profile):
        set_switches(page_creation_enabled=False)
        url = reverse("dashboard:onboarding", kwargs={"step": "nom"})
        response = logged_client.post(url, {"display_name": "Nouveau Nom", "kind": profile.kind})
        assert response.status_code == 302
