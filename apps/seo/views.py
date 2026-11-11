"""robots.txt and the IndexNow key file (docs/etudes/kliz.md §4)."""

from __future__ import annotations

import hmac
import re

from django.conf import settings
from django.contrib.sitemaps.views import SitemapIndexItem, x_robots_tag
from django.http import Http404, HttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_safe

INDEXNOW_KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
TRACKING_PREFIXES = ("p", "a")  # /p/<pk>.gif view pixel, /a/<pk>/<kind> click beacons (apps.analytics)


def robots_lines() -> list[str]:
    """Production rules (plan §6.5). Never `Disallow: /`: pre-production is password-protected instead."""
    lines = ["User-agent: *", "Allow: /"]
    # The admin is NOT listed: ADMIN_URL is secret (ADR-0010) and robots.txt is public. Admin pages are
    # behind login + 2FA and send noindex anyway.
    lines.append("Disallow: /espace/")
    lines += [f"Disallow: /{prefix}/" for prefix in TRACKING_PREFIXES]
    lines += ["", f"Sitemap: {settings.SITE_URL}{reverse('seo:sitemap')}"]
    return lines


@require_safe
@cache_control(public=True, max_age=3600)
def robots_txt(request):
    return HttpResponse("\n".join(robots_lines()) + "\n", content_type="text/plain; charset=utf-8")


@require_safe
def indexnow_key(request, key):
    expected = settings.KLIZ_INDEXNOW_KEY or ""
    if not (INDEXNOW_KEY_RE.match(expected) and hmac.compare_digest(key, expected)):
        raise Http404
    response = HttpResponse(expected, content_type="text/plain; charset=utf-8")
    response["X-Robots-Tag"] = "noindex"
    return response


@x_robots_tag
@require_safe
def sitemap_index(request, sitemaps, sitemap_url_name="seo:sitemap_section"):
    """Like django.contrib.sitemaps.views.index, but on the canonical SITE_URL host (not the request host)."""
    items = []
    for section, site in sitemaps.items():
        site = site() if callable(site) else site
        if not site.paginator.count:
            continue  # an empty section is not listed (SEO audit 2026-11-10 #9)
        url = f"{settings.SITE_URL}{reverse(sitemap_url_name, kwargs={'section': section})}"
        lastmod = site.get_latest_lastmod()
        items.append(SitemapIndexItem(url, lastmod))
        items += [SitemapIndexItem(f"{url}?p={page}", lastmod) for page in range(2, site.paginator.num_pages + 1)]
    return TemplateResponse(request, "sitemap_index.xml", {"sitemaps": items}, content_type="application/xml")
