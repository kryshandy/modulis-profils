from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SecurityConfig(AppConfig):
    """Staff two-factor authentication (TOTP + backup codes) on the admin (ADR-0010)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.security"
    verbose_name = _("Sécurité de l'administration")

    def ready(self) -> None:
        from . import checks  # noqa: F401  (registers security.W101)
