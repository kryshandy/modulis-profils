"""SMS sending backends. OTP is delivered by SMS only.

The real provider (local SMS aggregator) is plugged in by adding a backend class here and
setting SMS_BACKEND. Sending always happens in a background task (apps.accounts.tasks).
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmsMessage:
    to: str
    body: str


class BaseSmsBackend:
    def send(self, message: SmsMessage) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSmsBackend(BaseSmsBackend):
    """Development: print the SMS in the console / docker logs."""

    def send(self, message: SmsMessage) -> None:
        logger.warning("SMS to %s: %s", message.to, message.body)
        print(f"\n===== SMS -> {message.to} =====\n{message.body}\n==============================\n", flush=True)


class MemorySmsBackend(BaseSmsBackend):
    """Tests: keep messages in memory (like Django's locmem email backend)."""

    outbox: list[SmsMessage] = []

    def send(self, message: SmsMessage) -> None:
        MemorySmsBackend.outbox.append(message)


class DisabledSmsBackend(BaseSmsBackend):
    """Production default when no SMS gateway is used (WhatsApp / Firebase only): never sends."""

    def send(self, message: SmsMessage) -> None:
        raise RuntimeError("No SMS gateway configured (SMS_BACKEND).")


def get_backend() -> BaseSmsBackend:
    return import_string(settings.SMS_BACKEND)()


def send_sms(to: str, body: str) -> None:
    get_backend().send(SmsMessage(to=to, body=body))
