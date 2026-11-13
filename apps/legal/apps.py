from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LegalConfig(AppConfig):
    name = "apps.legal"
    label = "legal"
    verbose_name = _("Informations légales")

    def ready(self) -> None:
        from . import checks  # noqa: F401  (registers the system checks)
