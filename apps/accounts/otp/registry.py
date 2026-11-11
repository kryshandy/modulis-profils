"""Which OTP channels exist, which are offered, and their status for the admin control center."""

from __future__ import annotations

from .base import OTPChannel
from .firebase import FirebaseSmsChannel
from .sms_gateway import ConsoleChannel, SmsGatewayChannel
from .whatsapp import WhatsAppChannel

#: Real channels, keyed by the codes of apps.platform.SiteSettings.OtpChannel.
CHANNELS: dict[str, OTPChannel] = {
    channel.code: channel for channel in (WhatsAppChannel(), FirebaseSmsChannel(), SmsGatewayChannel())
}
CONSOLE = ConsoleChannel()


def get_channel(code: str | None) -> OTPChannel | None:
    if code == CONSOLE.code:
        return CONSOLE
    return CHANNELS.get(code or "")


def available_channels() -> list[OTPChannel]:
    """Channels a pro can use now: enabled in the admin AND configured, default channel first.

    When none is available, the dev console channel is offered in DEBUG (and with the in-memory
    test SMS backend); never in production.
    """
    from apps.platform.services import enabled_otp_channels

    channels = [CHANNELS[code] for code in enabled_otp_channels() if code in CHANNELS]
    channels = [channel for channel in channels if channel.is_configured()]
    if not channels and CONSOLE.is_configured():
        channels = [CONSOLE]
    return channels


def default_channel() -> OTPChannel | None:
    channels = available_channels()
    return channels[0] if channels else None


def channel_status() -> list[dict]:
    """[{code, label, enabled, configured, kind}] for each real channel (admin control center)."""
    from apps.platform.services import get_settings

    site = get_settings()
    enabled = {
        WhatsAppChannel.code: site.otp_whatsapp_enabled,
        FirebaseSmsChannel.code: site.otp_firebase_sms_enabled,
        SmsGatewayChannel.code: site.otp_sms_gateway_enabled,
    }
    return [
        {
            "code": code,
            "label": str(channel.label),
            "enabled": bool(enabled.get(code)),
            "configured": channel.is_configured(),
            "kind": channel.kind,
        }
        for code, channel in CHANNELS.items()
    ]
