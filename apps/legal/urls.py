"""Public legal pages. Their first-level segments are reserved slugs (profiles.services)."""

from django.urls import path

from . import views

app_name = "legal"

urlpatterns = [
    path("cgu", views.terms, name="terms"),
    path("confidentialite", views.privacy, name="privacy"),
    path("mentions-legales", views.notice, name="notice"),
    path("espace/conditions", views.accept, name="accept"),
]
