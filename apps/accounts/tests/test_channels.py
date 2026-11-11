"""OTP channels (ADR-0009): availability, WhatsApp Cloud API, platform switches applied to every channel."""

import logging

import pytest
import requests

from apps.accounts import otp, services
from apps.accounts.models import OTPChallenge
from apps.accounts.otp import whatsapp
from apps.platform.models import BlockedPhone
from tests.factories import UserFactory

from .otp_helpers import FakeResponse, configure_firebase, configure_whatsapp, set_switches

pytestmark = pytest.mark.django_db

PHONE = "+237690000101"


@pytest.fixture
def wa_calls(monkeypatch):
    """Capture WhatsApp HTTP calls; respond 200 by default."""

    class Calls(list):
        pass

    calls = Calls()
    responses = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return responses.pop(0) if responses else FakeResponse(200, {"messages": [{"id": "wamid.X"}]})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    calls.responses = responses
    return calls


# --- Availability ----------------------------------------------------------------------------


class TestAvailability:
    def test_nothing_configured_offers_only_dev_console_in_tests(self):
        assert [c.code for c in otp.available_channels()] == ["console"]

    def test_console_never_offered_outside_debug_with_real_backend(self, settings):
        settings.DEBUG = False
        settings.SMS_BACKEND = "apps.accounts.sms.ConsoleSmsBackend"
        assert otp.available_channels() == []

    def test_console_offered_in_debug(self, settings):
        settings.DEBUG = True
        settings.SMS_BACKEND = "apps.accounts.sms.ConsoleSmsBackend"
        assert [c.code for c in otp.available_channels()] == ["console"]

    def test_configured_and_enabled_channels_default_first(self, settings):
        configure_whatsapp(settings)
        configure_firebase(settings)
        assert [c.code for c in otp.available_channels()] == ["whatsapp", "firebase_sms"]
        set_switches(otp_default_channel="firebase_sms")
        assert [c.code for c in otp.available_channels()] == ["firebase_sms", "whatsapp"]

    def test_disabled_channel_is_not_offered(self, settings):
        configure_whatsapp(settings)
        configure_firebase(settings)
        set_switches(otp_whatsapp_enabled=False)
        assert [c.code for c in otp.available_channels()] == ["firebase_sms"]

    def test_enabled_but_unconfigured_channel_is_not_offered(self, settings):
        configure_whatsapp(settings)
        settings.WHATSAPP_ACCESS_TOKEN = ""
        assert "whatsapp" not in [c.code for c in otp.available_channels()]

    def test_sms_gateway_needs_a_real_backend_and_the_switch(self, settings):
        settings.SMS_BACKEND = "apps.accounts.sms.ConsoleSmsBackend"
        set_switches(otp_sms_gateway_enabled=True)
        assert "sms_gateway" not in [c.code for c in otp.available_channels()]
        settings.SMS_BACKEND = "myproject.sms.RealProviderBackend"
        assert [c.code for c in otp.available_channels()] == ["sms_gateway"]

    def test_channel_status_shape(self, settings):
        configure_whatsapp(settings)
        set_switches(otp_firebase_sms_enabled=False)
        status = otp.channel_status()
        assert [s["code"] for s in status] == ["whatsapp", "firebase_sms", "sms_gateway"]
        assert set(status[0]) == {"code", "label", "enabled", "configured", "kind"}
        assert status[0] | {"label": ""} == {
            "code": "whatsapp",
            "label": "",
            "enabled": True,
            "configured": True,
            "kind": "server",
        }
        assert status[1]["enabled"] is False and status[1]["configured"] is False and status[1]["kind"] == "client"
        assert status[2]["enabled"] is False


# --- WhatsApp Cloud API ----------------------------------------------------------------------


class TestWhatsApp:
    def test_payload_and_headers(self, settings, wa_calls):
        configure_whatsapp(settings)
        whatsapp.WhatsAppChannel().send(PHONE, "123456")
        call = wa_calls[0]
        assert call["url"] == "https://graph.facebook.com/v23.0/1234567890/messages"
        assert call["headers"]["Authorization"] == "Bearer secret-token-xyz"
        assert call["timeout"]
        assert call["json"] == {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": "237690000101",  # no "+"
            "type": "template",
            "template": {
                "name": "modulis_otp",
                "language": {"code": "fr"},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": "123456"}]},
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [{"type": "text", "text": "123456"}],
                    },
                ],
            },
        }

    @pytest.mark.parametrize(
        ("status", "code", "retryable", "message_part"),
        [
            (400, 131026, False, "pas de compte WhatsApp"),
            (400, 131030, False, "pas de compte WhatsApp"),
            (429, 130429, True, "très sollicité"),
            (400, 131056, True, "très sollicité"),
            (500, 131000, True, "très sollicité"),
            (503, None, True, "indisponible"),
            (401, 190, False, "indisponible"),
            (400, 132001, False, "indisponible"),
            (400, 100, False, "indisponible"),
        ],
    )
    def test_error_mapping(self, settings, wa_calls, status, code, retryable, message_part):
        configure_whatsapp(settings)
        error = {"error": {"message": "secret details 654321", "type": "OAuthException", "fbtrace_id": "T1"}}
        if code is not None:
            error["error"]["code"] = code
        wa_calls.responses.append(FakeResponse(status, error))
        with pytest.raises(otp.DeliveryError) as exc:
            whatsapp.WhatsAppChannel().send(PHONE, "654321")
        assert exc.value.retryable is retryable
        assert message_part in exc.value.user_message
        assert "654321" not in exc.value.user_message and "654321" not in str(exc.value)

    def test_network_error_is_retryable(self, settings, monkeypatch):
        configure_whatsapp(settings)

        def boom(*args, **kwargs):
            raise requests.ConnectionError("https://graph.facebook.com/... refused")

        monkeypatch.setattr(whatsapp.requests, "post", boom)
        with pytest.raises(otp.DeliveryError) as exc:
            whatsapp.WhatsAppChannel().send(PHONE, "111222")
        assert exc.value.retryable

    def test_non_json_error(self, settings, wa_calls):
        configure_whatsapp(settings)
        wa_calls.responses.append(FakeResponse(502, ValueError("not json")))
        with pytest.raises(otp.DeliveryError) as exc:
            whatsapp.WhatsAppChannel().send(PHONE, "111222")
        assert exc.value.retryable

    def test_request_otp_sends_by_whatsapp_and_never_logs_code_or_token(
        self, settings, wa_calls, caplog, django_capture_on_commit_callbacks
    ):
        configure_whatsapp(settings)
        caplog.set_level(logging.DEBUG)
        wa_calls.responses.append(FakeResponse(400, {"error": {"code": 131026, "message": "x"}}))
        with django_capture_on_commit_callbacks(execute=True):
            challenge = services.request_otp(PHONE, "login", ip_hash="ip", channel="whatsapp")
        assert challenge.channel == "whatsapp"
        code = wa_calls[0]["json"]["template"]["components"][0]["parameters"][0]["text"]
        assert len(code) == 6 and code not in challenge.code_hmac
        assert code not in caplog.text
        assert "secret-token-xyz" not in caplog.text
        assert PHONE not in caplog.text  # masked in logs
        # The permanent failure is kept as a safe message for the code screen.
        assert "pas de compte WhatsApp" in services.delivery_failure(PHONE, "login")

    def test_success_leaves_no_delivery_failure(self, settings, wa_calls, django_capture_on_commit_callbacks):
        configure_whatsapp(settings)
        with django_capture_on_commit_callbacks(execute=True):
            services.request_otp(PHONE, "login", channel="whatsapp")
        assert len(wa_calls) == 1
        assert services.delivery_failure(PHONE, "login") == ""

    def test_transient_error_is_raised_for_retry_then_recorded(self, settings, wa_calls):
        configure_whatsapp(settings)
        challenge = services.request_otp(PHONE, "login", channel="whatsapp")
        wa_calls.responses.extend([FakeResponse(503, {}), FakeResponse(503, {})])
        with pytest.raises(otp.DeliveryError):
            services.deliver_otp("whatsapp", PHONE, "123456", challenge.pk, final=False)
        services.deliver_otp("whatsapp", PHONE, "123456", challenge.pk, final=True)
        assert "indisponible" in services.delivery_failure(PHONE, "login")

    def test_code_from_whatsapp_verifies(self, settings, wa_calls, django_capture_on_commit_callbacks):
        configure_whatsapp(settings)
        with django_capture_on_commit_callbacks(execute=True):
            services.request_otp(PHONE, "login", channel="whatsapp")
        code = wa_calls[0]["json"]["template"]["components"][1]["parameters"][0]["text"]
        services.verify_otp(PHONE, "login", code)


# --- Rules applied to every channel -----------------------------------------------------------


class TestRules:
    def test_default_channel_used_when_none_given(self, sms_outbox, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            challenge = services.request_otp(PHONE, "login")
        assert challenge.channel == "console" and len(sms_outbox) == 1

    def test_unavailable_channel_refused(self):
        with pytest.raises(services.ChannelUnavailable):
            services.request_otp(PHONE, "login", channel="whatsapp")
        assert not OTPChallenge.objects.exists()

    def test_disabled_channel_refused(self, settings):
        configure_whatsapp(settings)
        set_switches(otp_whatsapp_enabled=False)
        with pytest.raises(services.ChannelUnavailable):
            services.request_otp(PHONE, "login", channel="whatsapp")

    def test_no_channel_at_all(self, settings):
        settings.SMS_BACKEND = "apps.accounts.sms.ConsoleSmsBackend"  # no dev console outside DEBUG
        with pytest.raises(services.ChannelUnavailable):
            services.request_otp(PHONE, "login")

    def test_blocked_phone_refused_with_generic_message(self, sms_outbox):
        BlockedPhone.objects.create(phone=PHONE, reason="fraude")
        with pytest.raises(services.AccountNotAllowed) as exc:
            services.request_otp(PHONE, "login")
        assert "bloqu" not in str(exc.value).lower()
        assert not OTPChallenge.objects.exists() and sms_outbox == []

    def test_signups_closed_refuses_unknown_phone_only(self, django_capture_on_commit_callbacks):
        set_switches(signups_enabled=False)
        with pytest.raises(services.SignupsClosed) as exc:
            services.request_otp(PHONE, "login")
        assert "inscriptions sont momentanément fermées" in str(exc.value)
        UserFactory(phone="+237690000102")
        services.request_otp("+237690000102", "login")  # existing account: still allowed

    def test_login_disabled_refuses_everyone(self):
        UserFactory(phone=PHONE)
        set_switches(login_enabled=False)
        with pytest.raises(services.LoginDisabled):
            services.request_otp(PHONE, "login")

    @pytest.mark.parametrize("channel", ["whatsapp", "firebase_sms"])
    def test_staff_refused_on_every_channel(self, settings, channel):
        configure_whatsapp(settings)
        configure_firebase(settings)
        UserFactory(phone=PHONE, is_staff=True)
        with pytest.raises(services.AccountNotAllowed):
            services.request_otp(PHONE, "login", channel=channel)

    def test_prefix_whitelist_on_every_channel(self, settings):
        configure_firebase(settings)
        with pytest.raises(services.PhoneNotAllowed):
            services.request_otp("+33612345678", "login", channel="firebase_sms")

    def test_client_channel_creates_pending_challenge_and_sends_nothing(
        self, settings, sms_outbox, django_capture_on_commit_callbacks
    ):
        configure_firebase(settings)
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            challenge = services.request_otp(PHONE, "login", channel="firebase_sms")
        # Only the settings-cache invalidation may run (singleton created on first read): no send task.
        assert [c for c in callbacks if c.__name__ != "invalidate"] == [] and sms_outbox == []
        assert challenge.channel == "firebase_sms" and challenge.code_hmac == ""
        with pytest.raises(services.InvalidCode):  # a typed code can never answer a Firebase challenge
            services.verify_otp(PHONE, "login", "")

    def test_client_channel_counts_in_send_limits(self, settings):
        configure_firebase(settings)
        settings.OTP_MAX_SENDS_PER_PHONE_PER_HOUR = 1
        services.request_otp(PHONE, "login", channel="firebase_sms")
        with pytest.raises(services.TooManyRequests):
            services.request_otp(PHONE, "login", channel="firebase_sms")


class TestGetOrCreateUserDefence:
    def test_blocked(self):
        BlockedPhone.objects.create(phone=PHONE, reason="x")
        with pytest.raises(services.AccountNotAllowed):
            services.get_or_create_user(PHONE)

    def test_signups_closed_new_phone(self):
        set_switches(signups_enabled=False)
        with pytest.raises(services.SignupsClosed):
            services.get_or_create_user(PHONE)
        UserFactory(phone="+237690000103")
        _user, created = services.get_or_create_user("+237690000103")
        assert not created

    def test_login_disabled(self):
        UserFactory(phone=PHONE)
        set_switches(login_enabled=False)
        with pytest.raises(services.LoginDisabled):
            services.get_or_create_user(PHONE)
