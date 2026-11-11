"""Test helpers: mark a staff session as having passed 2FA (never imported by production code)."""

from __future__ import annotations

from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice


def mark_otp_verified(client, user) -> TOTPDevice:
    """Give `user` a confirmed TOTP device (if needed) and mark the client's session as verified.

    Call after client.force_login(user). The root conftest does it automatically for staff users
    (except in tests marked `real_2fa`).
    """
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()
    return device
