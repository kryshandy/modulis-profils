"""Right of access and portability: everything we hold about a pro account, as one JSON document.

Built from the model fields (new fields are exported automatically) minus internal technical ones.
Photos are given as absolute URLs. Visit statistics are exported as daily totals (raw events only
hold anonymous visitor data, not the pro's).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from .conf import LEGAL_VERSION

EXCLUDED = {
    "password",
    "bio_fingerprint",
    "activation_code_hash",
    "raw_payload",
    "created_by_agent",
    "created_by",
    "user",
    "profile",
    "batch",
}


def _value(value):
    if isinstance(value, FieldFile):
        return f"{settings.SITE_URL}{value.url}" if value else ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, models.Model):
        return str(value)
    return value


def _row(obj: models.Model, extra_exclude: frozenset[str] = frozenset()) -> dict:
    data = {}
    for field in obj._meta.concrete_fields:
        if field.name in EXCLUDED or field.name in extra_exclude:
            continue
        value = getattr(obj, field.name)
        if field.choices and value not in (None, ""):
            data[field.name] = getattr(obj, f"get_{field.name}_display")()
        else:
            data[field.name] = _value(value)
    return data


def export_user_data(user) -> dict:
    from apps.analytics.models import DailyStat
    from apps.billing.models import Payment, Subscription
    from apps.cards.models import Card
    from apps.profiles.models import Profile

    profiles = Profile.objects.filter(user=user).exclude(status=Profile.Status.DELETED).order_by("created_at")
    pages = []
    for profile in profiles:
        stats = DailyStat.objects.filter(profile=profile).order_by("day", "kind")
        pages.append(
            {
                "page": _row(profile),
                "url": profile.absolute_url,
                "prestations": [_row(s) for s in profile.services.order_by("order")],
                "photos": [_row(m) for m in profile.media.order_by("order")],
                "liens": [_row(link) for link in profile.links.order_by("order")],
                "cartes": [_row(c) for c in Card.objects.filter(profile=profile).order_by("activated_at")],
                "abonnements": [_row(s) for s in Subscription.objects.filter(profile=profile).order_by("starts_at")],
                "paiements": [_row(p) for p in Payment.objects.filter(profile=profile).order_by("created_at")],
                "statistiques_journalieres": [
                    {
                        "jour": s.day.isoformat(),
                        "type": s.get_kind_display(),
                        "total": s.total,
                        "visiteurs": s.unique_visitors,
                    }
                    for s in stats
                ],
            }
        )
    return {
        "format": "modulis-profils/export-v1",
        "genere_le": timezone.now().isoformat(),
        "plateforme": settings.SITE_URL,
        "compte": _row(user, frozenset({"is_staff", "is_superuser", "groups", "user_permissions", "last_login"})),
        "cgu_version_en_vigueur": LEGAL_VERSION,
        "pages": pages,
    }
