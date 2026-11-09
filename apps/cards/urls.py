"""Card URLs. The printed format https://DOMAIN/c/XXXXXXX is frozen forever (ADR-0003)."""

from django.urls import path

from . import views

app_name = "cards"

urlpatterns = [
    path("<str:code>", views.scan, name="scan"),
    path("<str:code>/activer", views.activate, name="activate"),
]
