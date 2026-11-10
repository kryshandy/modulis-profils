"""HTTP caching headers of the public pages (SEO audit 2026-11-10 #7).

- Cacheable public pages: `public, max-age=300, s-maxage=600, stale-while-revalidate=86400`.
- 404 / 410: short public cache (60 s).
- `Vary: Accept-Language` is dropped from public pages: they are not language-negotiated (the language
  comes from the profile, French elsewhere), so the header only fragments CDN and browser caches.
  LocaleMiddleware adds it AFTER the view returns, hence the middleware below, which must be placed
  BEFORE `django.middleware.locale.LocaleMiddleware` in settings.MIDDLEWARE (responses go back up).
"""

from __future__ import annotations

import functools

from django.conf import settings
from django.http import HttpResponse
from django.utils import translation
from django.utils.cache import cc_delim_re, patch_cache_control

PUBLIC_MAX_AGE = 300
PUBLIC_S_MAXAGE = 600
STALE_WHILE_REVALIDATE = 86400
ERROR_MAX_AGE = 60
LANGUAGE_INDEPENDENT = "language_independent"  # response attribute read by PublicHeadersMiddleware


def set_public_cache(response: HttpResponse) -> HttpResponse:
    patch_cache_control(
        response,
        public=True,
        max_age=PUBLIC_MAX_AGE,
        s_maxage=PUBLIC_S_MAXAGE,
        stale_while_revalidate=STALE_WHILE_REVALIDATE,
    )
    return response


def set_private_no_store(response: HttpResponse) -> HttpResponse:
    patch_cache_control(response, private=True, no_store=True)
    return response


def set_error_cache(response: HttpResponse) -> HttpResponse:
    patch_cache_control(response, public=True, max_age=ERROR_MAX_AGE)
    return response


def mark_language_independent(response: HttpResponse, lang: str | None = None) -> HttpResponse:
    setattr(response, LANGUAGE_INDEPENDENT, True)
    response.headers.setdefault("Content-Language", lang or settings.LANGUAGE_CODE)
    return response


def language_independent(view):
    """Render the view in LANGUAGE_CODE (never from Accept-Language) and flag the response for the middleware."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        with translation.override(settings.LANGUAGE_CODE):
            response = view(request, *args, **kwargs)
        if not getattr(response, LANGUAGE_INDEPENDENT, False):
            mark_language_independent(response)
        return response

    return wrapper


def drop_vary(response: HttpResponse, header: str) -> None:
    if not response.has_header("Vary"):
        return
    kept = [h for h in cc_delim_re.split(response["Vary"]) if h and h.lower() != header.lower()]
    if kept:
        response["Vary"] = ", ".join(kept)
    else:
        del response["Vary"]


def _is_public_path(path: str) -> bool:
    private_prefixes = ["/espace/"]
    admin = settings.ADMIN_URL.strip("/")
    if admin:
        private_prefixes.append(f"/{admin}/")
    return not path.startswith(tuple(private_prefixes))


class PublicHeadersMiddleware:
    """Drop `Vary: Accept-Language` from flagged public responses; short cache on public 404s."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(response, LANGUAGE_INDEPENDENT, False):
            drop_vary(response, "Accept-Language")
        if response.status_code == 404 and not response.has_header("Cache-Control") and _is_public_path(request.path):
            set_error_cache(response)
        return response
