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


def robots_lines() -> list[str]:
    """Production rules (plan §6.5). Never `Disallow: /`: pre-production is password-protected instead."""
    lines = ["User-agent: *", "Allow: /"]
    for prefix in ("espace/", settings.ADMIN_URL):
        prefix = prefix.strip("/")
        if prefix:  # an empty prefix would produce "Disallow: /"
            lines.append(f"Disallow: /{prefix}/")
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
        url = f"{settings.SITE_URL}{reverse(sitemap_url_name, kwargs={'section': section})}"
        lastmod = site.get_latest_lastmod()
        items.append(SitemapIndexItem(url, lastmod))
        items += [SitemapIndexItem(f"{url}?p={page}", lastmod) for page in range(2, site.paginator.num_pages + 1)]
    return TemplateResponse(request, "sitemap_index.xml", {"sitemaps": items}, content_type="application/xml")
