"""Per-response Content-Security-Policy additions (django-csp 4).

The global policy (settings.CONTENT_SECURITY_POLICY) only allows our own origin. Third-party hosts
are added on the few responses that need them, never site-wide:
- Cloudflare Turnstile: pages showing the anti-bot widget;
- Firebase Phone Auth + its invisible reCAPTCHA (ADR-0009): the code screens of the Firebase channel.
"""

from __future__ import annotations

TURNSTILE = {
    "script-src": ["https://challenges.cloudflare.com"],
    "frame-src": ["https://challenges.cloudflare.com"],
}

FIREBASE = {
    "script-src": ["https://www.gstatic.com", "https://www.google.com", "https://apis.google.com"],
    "connect-src": [
        "https://identitytoolkit.googleapis.com",
        "https://securetoken.googleapis.com",
        "https://www.googleapis.com",
    ],
    "frame-src": ["https://www.google.com", "https://*.firebaseapp.com"],
}


def allow(response, *policies: dict):
    """Add the sources of `policies` to this response's CSP (merged with any earlier addition)."""
    update = {key: list(values) for key, values in (getattr(response, "_csp_update", None) or {}).items()}
    for policy in policies:
        for directive, sources in policy.items():
            current = update.setdefault(directive, [])
            current.extend(s for s in sources if s not in current)
    response._csp_update = update
    return response
