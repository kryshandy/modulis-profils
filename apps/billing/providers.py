"""Payment provider interface and internal HMAC-signed sandbox provider (no external network calls)."""

from __future__ import annotations

import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from .models import Payment

if TYPE_CHECKING:
    pass


class PaymentError(Exception):
    """Business or protocol error raised during payment initiation, verification, or webhook parsing."""


class InvalidSignatureError(PaymentError):
    """Raised when a webhook request fails HMAC signature verification."""


class PaymentProvider(ABC):
    """Abstract interface for payment providers (sandbox now, aggregators later)."""

    name: str

    @abstractmethod
    def initiate(self, payment: Payment, callback_url: str) -> dict:
        """Initialize a payment session and return provider metadata."""

    @abstractmethod
    def verify(self, payment: Payment) -> dict:
        """Verify the current status of a payment with the provider."""

    @abstractmethod
    def parse_webhook(self, request: HttpRequest) -> dict:
        """Validate webhook signature and parse the incoming payload."""


class SandboxPaymentProvider(PaymentProvider):
    """Local payment simulator secured with HMAC-SHA256 (zero network calls)."""

    name = "sandbox"
    SIGNATURE_HEADER = "X-Sandbox-Signature"

    def _hmac_key(self) -> bytes:
        key = getattr(settings, "BILLING_SANDBOX_HMAC_KEY", settings.SECRET_KEY)
        return key.encode("utf-8")

    def sign(self, payload_bytes: bytes) -> str:
        """Compute the HMAC-SHA256 hex digest for a raw webhook payload."""
        return hmac.new(self._hmac_key(), payload_bytes, hashlib.sha256).hexdigest()

    def verify_signature(self, payload_bytes: bytes, signature: str) -> bool:
        """Verify an incoming HMAC-SHA256 signature in constant time."""
        if not signature:
            return False
        expected = self.sign(payload_bytes)
        return hmac.compare_digest(expected, signature)

    def initiate(self, payment: Payment, callback_url: str) -> dict:
        provider_reference = f"SBX-{payment.reference}"
        return {
            "provider_reference": provider_reference,
            "payment_url": callback_url,
            "raw": {
                "mode": self.name,
                "reference": payment.reference,
                "amount": payment.amount,
                "currency": payment.currency,
            },
        }

    def verify(self, payment: Payment) -> dict:
        if payment.status == Payment.Status.SUCCEEDED:
            status = Payment.Status.SUCCEEDED
        else:
            candidate = payment.raw_payload.get("simulated_status") or payment.raw_payload.get("status")
            status = candidate if candidate in Payment.Status.values else Payment.Status.PENDING
        return {
            "status": status,
            "provider_reference": payment.provider_reference or f"SBX-{payment.reference}",
            "amount": payment.amount,
            "currency": payment.currency,
            "raw": dict(payment.raw_payload),
        }

    def parse_webhook(self, request: HttpRequest) -> dict:
        signature = request.headers.get(self.SIGNATURE_HEADER, "")
        if not self.verify_signature(request.body, signature):
            raise InvalidSignatureError(_("Signature de webhook invalide."))

        try:
            data = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentError(_("Charge utile JSON invalide.")) from exc

        if not isinstance(data, dict):
            raise PaymentError(_("Charge utile JSON invalide."))

        reference = data.get("reference")
        status = data.get("status")
        amount = data.get("amount")
        currency = data.get("currency")

        if not isinstance(reference, str) or not reference:
            raise PaymentError(_("Référence de paiement manquante."))
        if status not in Payment.Status.values:
            raise PaymentError(_("Statut de paiement invalide."))
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise PaymentError(_("Montant de paiement invalide."))
        if not isinstance(currency, str) or not currency:
            raise PaymentError(_("Devise de paiement manquante."))

        return {
            "reference": reference,
            "provider_reference": str(data.get("provider_reference", "")),
            "status": status,
            "amount": amount,
            "currency": currency,
            "raw": data,
        }


PROVIDERS: dict[str, type[PaymentProvider]] = {
    SandboxPaymentProvider.name: SandboxPaymentProvider,
}


def get_provider(name: str) -> PaymentProvider:
    """Instantiate a registered payment provider by name."""
    provider_cls = PROVIDERS.get(name)
    if provider_cls is None:
        raise PaymentError(_("Fournisseur de paiement inconnu."))
    return provider_cls()
