"""System checks: the legal notice must identify the publisher and the host in production."""

from django.conf import settings
from django.core.checks import Warning, register

from .conf import missing_identity_fields


@register()
def legal_identity(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    missing = missing_identity_fields()
    if not missing:
        return []
    return [
        Warning(
            "Mentions légales incomplètes : " + ", ".join(missing) + ".",
            hint="Renseigner ces variables dans .env (voir .env.example, section « Informations légales »).",
            id="legal.W001",
        )
    ]
