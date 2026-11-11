"""Session hardening for the staff."""

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in, dispatch_uid="core_staff_short_session")
def shorten_staff_session(sender, request, user, **kwargs):
    """Pros stay logged in 30 days on their phone; staff sessions expire after STAFF_SESSION_AGE.

    A staff password login also drops any previous 2FA mark of the session: every password login
    must be followed by a fresh TOTP verification (ADR-0010).
    """
    if request is not None and getattr(user, "is_staff", False) and hasattr(request, "session"):
        request.session.set_expiry(settings.STAFF_SESSION_AGE)
        if not getattr(user, "otp_device", None):
            from apps.security.services import forget_session_verification

            forget_session_verification(request)
