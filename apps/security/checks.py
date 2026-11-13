"""Production reminder: the evaluation super-admin (bootstrap_superadmin) must be deleted."""

from django.conf import settings
from django.core.checks import Warning, register
from django.db import DatabaseError


def bootstrap_admin_exists() -> bool:
    from apps.accounts.management.commands.bootstrap_superadmin import bootstrap_phone
    from apps.accounts.models import User

    try:
        phone = bootstrap_phone()
        return bool(phone) and User.objects.filter(phone=phone, is_superuser=True).exists()
    except (DatabaseError, ValueError, Exception):
        return False


@register(deploy=True)
def bootstrap_admin(app_configs, **kwargs):
    if settings.DEBUG or not bootstrap_admin_exists():
        return []
    return [
        Warning(
            "Le super-admin d'évaluation (BOOTSTRAP_ADMIN_PHONE) existe encore.",
            hint="Créez votre propre super-admin (make admin), puis : python manage.py bootstrap_superadmin --delete",
            id="security.W101",
        )
    ]
