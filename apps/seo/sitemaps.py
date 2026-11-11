"""Sitemaps (plan §6.4): only indexable pages, `lastmod` = content_updated_at, absolute SITE_URL."""

from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse

from . import selectors

SITEMAP_TEMPLATE = "seo/sitemap.xml"  # lastmod as a full W3C datetime (SEO audit 2026-11-10 #9)


def _seconds(value):
    """W3C datetime without microseconds (rendered with the time zone by the template)."""
    return value.replace(microsecond=0) if value is not None else None


class SiteUrlSitemap(Sitemap):
    """Always build URLs on the canonical host, whatever host the request came from."""

    @property
    def protocol(self):  # type: ignore[override]
        return urlsplit(settings.SITE_URL).scheme or "https"

    def get_domain(self, site=None):
        return urlsplit(settings.SITE_URL).netloc


class ProfileSitemap(SiteUrlSitemap):
    limit = 50_000

    def items(self):
        return selectors.indexable_profiles().select_related(None).only("slug", "content_updated_at").order_by("pk")

    def location(self, item):
        return item.get_absolute_url()

    def lastmod(self, item):
        return _seconds(item.content_updated_at)

    def get_latest_lastmod(self):
        """One aggregate query instead of loading every profile for the sitemap index."""
        return _seconds(selectors.indexable_profiles().aggregate(latest=Max("content_updated_at"))["latest"])


class DirectorySitemap(SiteUrlSitemap):
    """City pages and trade×city directories that meet SEO_DIRECTORY_MIN_PROFILES."""

    def items(self):
        from apps.public.views import directory_enabled

        if not directory_enabled():  # switched off in the control center: those pages answer 404
            return []
        minimum = selectors.directory_min()
        entries = [
            {"path": reverse("public:city", kwargs={"city": c["city"].slug}), "lastmod": c["lastmod"]}
            for c in selectors.city_stats(minimum)
        ]
        entries += [
            {
                "path": reverse(
                    "public:directory", kwargs={"trade_plural": c["trade"].plural_slug, "city": c["city"].slug}
                ),
                "lastmod": c["lastmod"],
            }
            for c in selectors.directory_combos(minimum)
        ]
        return sorted(entries, key=lambda e: e["path"])

    def location(self, item):
        return item["path"]

    def lastmod(self, item):
        return _seconds(item["lastmod"])


class StaticPagesSitemap(SiteUrlSitemap):
    def items(self):
        return ["public:home"]

    def location(self, item):
        return reverse(item)


SITEMAPS = {
    "profils": ProfileSitemap,
    "annuaire": DirectorySitemap,
    "pages": StaticPagesSitemap,
}
