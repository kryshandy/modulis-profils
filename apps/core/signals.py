"""Session hardening for the staff."""

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in, dispatch_uid="core_staff_short_session")
def shorten_staff_session(sender, request, user, **kwargs):
    """Pros stay logged in 30 days on their phone; staff sessions expire after STAFF_SESSION_AGE."""
    if request is not None and getattr(user, "is_staff", False) and hasattr(request, "session"):
        request.session.set_expiry(settings.STAFF_SESSION_AGE)
