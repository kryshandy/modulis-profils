"""OTP by WhatsApp: Meta WhatsApp Cloud API, approved *authentication* template with a copy-code button.

POST https://graph.facebook.com/{version}/{phone-number-id}/messages (Bearer token). The code must
appear twice: as the body parameter and as the parameter of the copy-code (url) button.
Neither the code nor the token is ever logged.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .base import SERVER, DeliveryError, OTPChannel

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/{version}/{phone_number_id}/messages"
TIMEOUT = 10  # seconds

# Meta error codes (https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes).
RETRYABLE_CODES = {1, 2, 4, 17, 341, 80007, 130429, 131000, 131016, 131048, 131056, 133004}
NO_WHATSAPP_CODES = {131026, 131021, 131030, 131045, 131049, 131050, 1013}

MSG_UNAVAILABLE = _("L'envoi par WhatsApp est momentanément indisponible. Choisis de recevoir le code par SMS.")
MSG_NO_WHATSAPP = _(
    "Impossible d'envoyer le code sur WhatsApp à ce numéro (pas de compte WhatsApp ?). "
    "Choisis de recevoir le code par SMS."
)
MSG_BUSY = _("WhatsApp est très sollicité en ce moment. Réessaie dans un instant ou choisis le SMS.")


def recipient(phone: str) -> str:
    """Cloud API recipients are digits only, country code included, no "+"."""
    return phone.lstrip("+")


def build_payload(phone: str, code: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient(phone),
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_OTP_TEMPLATE,
            "language": {"code": settings.WHATSAPP_OTP_LANGUAGE},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]},
            ],
        },
    }


def map_error(status: int, data: object) -> DeliveryError:
    """Turn a Meta error response into a safe DeliveryError (never echoes the response text)."""
    error = data.get("error", {}) if isinstance(data, dict) else {}
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    reason = f"status={status} code={code} subcode={subcode} fbtrace_id={error.get('fbtrace_id', '')}"
    if code in NO_WHATSAPP_CODES:
        return DeliveryError(MSG_NO_WHATSAPP, retryable=False, reason=reason)
    if code in RETRYABLE_CODES or status == 429:
        return DeliveryError(MSG_BUSY, retryable=True, reason=reason)
    if status >= 500:
        return DeliveryError(MSG_UNAVAILABLE, retryable=True, reason=reason)
    # 190 (token), 10/200 (permission), 100 (parameter), 132xxx (template), 368, 131031 (account)…:
    # configuration problems: no retry, the team must act.
    return DeliveryError(MSG_UNAVAILABLE, retryable=False, reason=reason)


class WhatsAppChannel(OTPChannel):
    code = "whatsapp"
    kind = SERVER
    label = _("WhatsApp (API Cloud de Meta)")
    choice_label = _("Recevoir le code par WhatsApp")
    choice_help = _("Recommandé : rapide et gratuit pour toi.")
    code_label = _("Code reçu sur WhatsApp")
    verify_hint = _("Ouvre WhatsApp : tu as reçu un message de Modulis avec ton code à 6 chiffres.")
    recommended = True

    def is_configured(self) -> bool:
        return bool(
            settings.WHATSAPP_ACCESS_TOKEN
            and settings.WHATSAPP_PHONE_NUMBER_ID
            and settings.WHATSAPP_OTP_TEMPLATE
            and settings.WHATSAPP_API_VERSION
        )

    def send(self, phone: str, code: str) -> None:
        url = GRAPH_URL.format(version=settings.WHATSAPP_API_VERSION, phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID)
        headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}
        try:
            response = requests.post(url, json=build_payload(phone, code), headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            # The exception text may contain the URL (no secret), never the headers: still, log the type only.
            logger.warning("WhatsApp OTP: network error (%s)", type(exc).__name__)
            raise DeliveryError(MSG_UNAVAILABLE, retryable=True, reason=type(exc).__name__) from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code == 200 and isinstance(data, dict) and data.get("messages"):
            logger.info("WhatsApp OTP accepted by Meta for %s", mask(phone))
            return
        error = map_error(response.status_code, data)
        logger.error("WhatsApp OTP refused for %s: %s", mask(phone), error.reason)
        raise error


def mask(phone: str) -> str:
    """+237690000001 -> +2376******01 (logs: enough to investigate, not a full number)."""
    return phone[:5] + "*" * max(len(phone) - 7, 0) + phone[-2:] if len(phone) > 7 else "***"
