"""OTP by SMS through our own gateway (SMS_BACKEND, local aggregator) and the dev console channel."""

from __future__ import annotations

from django.conf import settings
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .. import sms
from .base import SERVER, OTPChannel

DEV_BACKENDS = {"ConsoleSmsBackend", "MemorySmsBackend", "DisabledSmsBackend"}  # never count as "configured"


def sms_body(code: str) -> str:
    return gettext("{site} : ton code est {code}. Il expire dans 5 minutes. Ne le partage avec personne.").format(
        site=settings.SITE_NAME, code=code
    )


def _backend_name() -> str:
    return (settings.SMS_BACKEND or "").rsplit(".", 1)[-1]


class SmsGatewayChannel(OTPChannel):
    code = "sms_gateway"
    kind = SERVER
    label = _("SMS via passerelle (agrégateur)")
    choice_label = _("Recevoir le code par SMS")
    choice_help = _("Un SMS classique sur ton téléphone.")
    code_label = _("Code reçu par SMS")
    verify_hint = _("Tu vas recevoir un SMS avec ton code à 6 chiffres. Il peut mettre jusqu'à une minute à arriver.")

    def is_configured(self) -> bool:
        return bool(settings.SMS_BACKEND) and _backend_name() not in DEV_BACKENDS

    def send(self, phone: str, code: str) -> None:
        sms.send_sms(phone, sms_body(code))


class ConsoleChannel(OTPChannel):
    """Development only: the code is printed in the console (`make logs`), or kept in memory in tests.

    Offered only when no real channel is available AND (DEBUG or the in-memory test backend).
    """

    code = "console"
    kind = SERVER
    label = _("Console de développement")
    choice_label = _("Code affiché dans la console (développement)")
    choice_help = _("Visible uniquement en développement : le code s'affiche dans les logs.")
    code_label = _("Code reçu par SMS")
    verify_hint = _("Développement : le code est affiché dans la console du serveur (make logs).")

    def is_configured(self) -> bool:
        return bool(settings.DEBUG) or _backend_name() == "MemorySmsBackend"

    def send(self, phone: str, code: str) -> None:
        message = sms.SmsMessage(to=phone, body=sms_body(code))
        if _backend_name() == "MemorySmsBackend":
            sms.MemorySmsBackend().send(message)
        else:
            sms.ConsoleSmsBackend().send(message)
