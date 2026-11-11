"""/espace/modeles/… — fixed paths first, then /<code>/… (services.RESERVED_CODES are never theme codes)."""

from django.urls import path

from . import views

app_name = "themes"

urlpatterns = [
    path("", views.gallery, name="gallery"),
    path("personnaliser", views.customize, name="customize"),
    path("personnaliser/apercu", views.draft_preview, name="draft_preview"),
    path("personnaliser/apercu.css", views.draft_css, name="draft_css"),
    path("publier", views.publish, name="publish"),
    path("en-ligne", views.published, name="published"),
    path("en-ligne/statut", views.published_status, name="published_status"),
    path("<slug:code>/", views.detail, name="detail"),
    path("<slug:code>/apercu", views.preview, name="preview"),
    path("<slug:code>/apercu.css", views.preview_css, name="preview_css"),
    path("<slug:code>/utiliser", views.use, name="use"),
]
