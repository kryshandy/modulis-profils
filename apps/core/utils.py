"""Small cross-cutting helpers (IP handling, hashing)."""

import hashlib
import hmac

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone


def client_ip(request: HttpRequest) -> str:
    """Return the real client IP.

    Behind Cloudflare, `CF-Connecting-IP` is only trusted when explicitly enabled
    (TRUST_CF_CONNECTING_IP), otherwise anyone could spoof it.
    """
    if settings.TRUST_CF_CONNECTING_IP:
        cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
        if cf_ip:
            return cf_ip.strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def hash_ip(ip: str, *, daily: bool = True) -> str:
    """Salted, non-reversible hash of an IP. With `daily`, the salt rotates every day."""
    salt = settings.ANALYTICS_SALT
    if daily:
        salt = f"{salt}:{timezone.localdate().isoformat()}"
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def ratelimit_ip_key(group, request) -> str:
    """Key function for django-ratelimit that honours the trusted-proxy setting."""
    return client_ip(request)
