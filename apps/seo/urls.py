"""robots.txt, sitemaps and the IndexNow key file. Root segments are reserved slugs ("robots", "sitemap")."""

from django.contrib.sitemaps import views as sitemap_views
from django.urls import path, re_path
from django.views.decorators.cache import cache_page

from . import views
from .sitemaps import SITEMAPS

app_name = "seo"

SITEMAP_CACHE_SECONDS = 10 * 60

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots"),
    path(
        "sitemap.xml",
        cache_page(SITEMAP_CACHE_SECONDS)(views.sitemap_index),
        {"sitemaps": SITEMAPS},
        name="sitemap",
    ),
    path(
        "sitemap-<slug:section>.xml",
        cache_page(SITEMAP_CACHE_SECONDS)(sitemap_views.sitemap),
        {"sitemaps": SITEMAPS},
        name="sitemap_section",
    ),
    re_path(r"^(?P<key>[A-Za-z0-9-]{8,128})\.txt$", views.indexnow_key, name="indexnow_key"),
]
