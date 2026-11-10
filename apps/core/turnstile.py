"""Cloudflare Turnstile server-side verification, shared by every form that can trigger an SMS."""

from django.conf import settings

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(token: str, remote_ip: str = "") -> bool:
    """Check a Turnstile token. Always True when Turnstile is disabled (no site key)."""
    if not settings.TURNSTILE_SITE_KEY:
        return True
    if not token:
        return False
    import requests  # local import: only needed when Turnstile is enabled

    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        response = requests.post(TURNSTILE_VERIFY_URL, data=data, timeout=5)
        return bool(response.json().get("success"))
    except (requests.RequestException, ValueError):
        return False  # fail closed: no SMS can be triggered without a valid challenge
