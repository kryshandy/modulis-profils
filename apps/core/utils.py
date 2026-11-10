"""Small cross-cutting helpers (client IP, hashing, rate-limit keys)."""

import hashlib
import hmac
import ipaddress

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone


def client_ip(request: HttpRequest) -> str:
    """Return the real client IP.

    Forwarded headers (CF-Connecting-IP, X-Real-IP) are honoured ONLY when the direct peer
    (REMOTE_ADDR) is one of TRUSTED_PROXY_IPS — e.g. the local Nginx that itself only accepts
    Cloudflare ranges (`set_real_ip_from`). Otherwise anyone could spoof them and bypass limits.
    """
    remote = request.META.get("REMOTE_ADDR", "") or "unknown"
    if remote in settings.TRUSTED_PROXY_IPS:
        for header in ("HTTP_CF_CONNECTING_IP", "HTTP_X_REAL_IP"):
            value = (request.META.get(header) or "").strip()
            if value:
                return value
    return remote


def rate_key_ip(ip: str) -> str:
    """IP used as a rate-limit key: IPv6 is grouped by /64 (one subscriber = one /64)."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return ip


def hash_ip(ip: str, *, daily: bool = True) -> str:
    """Salted, non-reversible hash of an IP. With `daily`, the salt rotates every day (analytics)."""
    salt = settings.ANALYTICS_SALT
    if daily:
        salt = f"{salt}:{timezone.localdate().isoformat()}"
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def security_ip_hash(request: HttpRequest) -> str:
    """Stable hash used by every security counter (OTP sends, card activation, reports).

    Never daily-rotated: a midnight salt change would reset hourly limits.
    """
    return hash_ip(rate_key_ip(client_ip(request)), daily=False)


def ratelimit_ip_key(group, request) -> str:
    """Key function for django-ratelimit: trusted-proxy aware and IPv6 /64 grouped."""
    return rate_key_ip(client_ip(request))
