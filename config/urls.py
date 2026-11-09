"""Root URL map. ORDER MATTERS: profile slugs live at the root, so they come last.

Every first-level segment declared here must be in profiles.services.SYSTEM_RESERVED_SLUGS
(enforced by apps/core/tests/test_reserved_slugs.py).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core.views import healthz

admin.site.site_header = "Modulis Profils — Administration"
admin.site.site_title = "Modulis Profils"
admin.site.index_title = "Tableau de bord"

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("espace/", include("apps.dashboard.urls")),
    path("c/", include("apps.cards.urls")),
    path("signaler/", include("apps.moderation.urls")),
    path("", include("apps.analytics.urls")),  # /p/… pixel, /a/… click tracking
    path("", include("apps.seo.urls")),  # robots.txt, sitemaps, IndexNow key file
    path("", include("apps.public.urls")),  # home, directory, /<slug> — MUST stay last
]

if settings.DEBUG:
    urlpatterns = static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + urlpatterns
