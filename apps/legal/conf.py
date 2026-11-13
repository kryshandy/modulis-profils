"""Version and identity data of the legal documents (CGU, privacy policy, legal notice).

Bump LEGAL_VERSION (ISO date of the new text) whenever the CGU or the privacy policy change in a way
users must be told about: every pro is then asked to accept the new version at their next visit to
the pro space (apps.legal.middleware). Keep LEGAL_CHANGES short and in plain words.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.utils.translation import gettext_lazy as _

LEGAL_VERSION = "2026-11-13"
LEGAL_EFFECTIVE_DATE = date(2026, 11, 13)

# What changed in LEGAL_VERSION, shown on the acceptance screen (first version: what the CGU cover).
LEGAL_CHANGES = [
    _("Ta page pro reste gratuite ; les offres payantes sont facultatives et sans renouvellement automatique."),
    _("Tu restes propriétaire de tes textes et photos ; tu nous autorises seulement à les afficher."),
    _("Tes données ne sont jamais vendues. Tu peux les télécharger ou tout supprimer depuis tes paramètres."),
    _("Les contenus interdits et la façon dont une page peut être suspendue sont précisés."),
]

# Identity fields that must be filled in production (system check legal.W001).
REQUIRED_IN_PRODUCTION = (
    "LEGAL_FORM",
    "LEGAL_RCCM",
    "LEGAL_NIU",
    "LEGAL_ADDRESS",
    "LEGAL_PUBLICATION_DIRECTOR",
    "LEGAL_HOST_NAME",
)


def company() -> dict:
    """Publisher and host identity, from settings (environment variables LEGAL_*)."""
    return {
        "name": settings.LEGAL_ENTITY_NAME,
        "form": settings.LEGAL_FORM,
        "rccm": settings.LEGAL_RCCM,
        "niu": settings.LEGAL_NIU,
        "address": settings.LEGAL_ADDRESS,
        "email": settings.LEGAL_EMAIL,
        "phone": settings.LEGAL_PHONE,
        "phone_href": "".join(ch for ch in settings.LEGAL_PHONE if ch.isdigit() or ch == "+"),
        "director": settings.LEGAL_PUBLICATION_DIRECTOR,
        "privacy_email": settings.LEGAL_PRIVACY_EMAIL,
        "host_name": settings.LEGAL_HOST_NAME,
        "host_address": settings.LEGAL_HOST_ADDRESS,
        "court_city": settings.LEGAL_COURT_CITY,
        "site_name": settings.SITE_NAME,
        "site_url": settings.SITE_URL,
    }


def missing_identity_fields() -> list[str]:
    return [name for name in REQUIRED_IN_PRODUCTION if not getattr(settings, name, "")]
