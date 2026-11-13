from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BlocksConfig(AppConfig):
    """Page builder: content blocks the pro stacks between the sections of their page (ADR-0012)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.blocks"
    verbose_name = _("Blocs des pages")
