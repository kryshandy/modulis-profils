"""OTP delivery channel interface (ADR-0009).

A channel is either:
- "server": our server generates the code and sends it (WhatsApp Cloud API, SMS gateway, dev console);
- "client": the provider generates, sends and checks the code in the browser, and our server only
  verifies a signed proof afterwards (Firebase Authentication, phone provider).

Secrets live in environment variables; the admin only switches channels on and off
(apps.platform.SiteSettings). A channel is offered only when it is enabled AND configured.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

SERVER = "server"
CLIENT = "client"


class DeliveryError(Exception):
    """A send failed. `user_message` is safe to show; it never contains the code nor a secret."""

    def __init__(self, user_message: str, *, retryable: bool = False, reason: str = ""):
        super().__init__(reason or "delivery failed")
        self.user_message = str(user_message)
        self.retryable = retryable
        self.reason = reason


class OTPChannel:
    code: str = ""
    kind: str = SERVER
    #: Shown in the admin control center.
    label = ""
    #: Shown to the pro on the login screen ("Recevoir le code par …").
    choice_label = ""
    #: Short help under the choice.
    choice_help = ""
    #: Field label on the code screen.
    code_label = _("Code reçu")
    #: Shown on the code screen, after the code was sent.
    verify_hint = ""
    recommended = False

    def is_configured(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def send(self, phone: str, code: str) -> None:
        """Deliver `code` to `phone` (E.164). Server channels only. Raises DeliveryError."""
        raise NotImplementedError(f"{self.code} is a client-side channel")

    def __repr__(self) -> str:
        return f"<OTPChannel {self.code}>"
