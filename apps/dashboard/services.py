"""Dashboard helpers: active profile, stats adapter and sharing.

The dashboard never writes page content itself: every write goes through
`apps.profiles.services` (update_profile, set_photo, add_service, move_item…).
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from django.db import DatabaseError, transaction
from django.utils.translation import gettext as _

from apps.profiles.images import GALLERY_MAX_SIDE, MAX_UPLOAD_BYTES, PHOTO_MAX_SIDE, process_image  # noqa: F401
from apps.profiles.models import Profile
from apps.profiles.services import MAX_LINKS, MAX_MEDIA, MAX_SERVICES  # noqa: F401  (used by views/templates)

logger = logging.getLogger(__name__)

SESSION_PROFILE_KEY = "dashboard_profile_id"

# Six cover colours, all with AA contrast for white text.
COVER_COLORS = [
    ("#0A7F7D", _("Sarcelle Modulis")),
    ("#075E5E", _("Sarcelle profond")),
    ("#063A39", _("Forêt")),
    ("#2747E6", _("Cobalt")),
    ("#B33A24", _("Terre cuite")),
    ("#16242C", _("Encre")),
]


# --- Profiles of the logged-in user ---------------------------------------------------------


def user_profiles(user):
    """Every live profile of `user` — the ONLY queryset used to fetch a profile (no IDOR)."""
    return Profile.objects.filter(user=user).exclude(status=Profile.Status.DELETED).select_related("trade", "city")


def active_profile(request) -> Profile | None:
    profiles = user_profiles(request.user)
    wanted = request.session.get(SESSION_PROFILE_KEY)
    profile = profiles.filter(pk=wanted).first() if wanted else None
    if profile is None:
        profile = profiles.order_by("created_at").first()
        if profile is not None:
            request.session[SESSION_PROFILE_KEY] = profile.pk
    return profile


def set_active_profile(request, profile_id) -> bool:
    try:
        profile = user_profiles(request.user).filter(pk=int(profile_id)).first()
    except (TypeError, ValueError):
        profile = None
    if profile is None:
        return False
    request.session[SESSION_PROFILE_KEY] = profile.pk
    return True


# --- Stats -----------------------------------------------------------------------------------

STAT_KINDS = [
    ("visit", _("Visites de ta page")),
    ("scan", _("Scans de carte / QR")),
    ("whatsapp", _("Clics WhatsApp")),
    ("call", _("Clics Appeler")),
    ("email", _("Clics Email")),
    ("maps", _("Clics Itinéraire")),
    ("vcard", _("Contacts enregistrés")),
    ("link", _("Clics sur tes liens")),
    ("share", _("Partages")),
]


def stats_30_days(profile: Profile) -> dict | None:
    """`analytics.services.stats_for_profile` over 30 days, used as is, or None on a database error.

    Keys: days, start, end, totals {kind: n}, unique_visitors, contacts, series [{day, <kind>: n}].
    The savepoint keeps the request transaction usable if the query fails (ATOMIC_REQUESTS).
    """
    from apps.analytics.services import stats_for_profile

    try:
        with transaction.atomic():
            return stats_for_profile(profile, days=30)
    except DatabaseError:  # never break the dashboard because of statistics
        logger.exception("stats_for_profile failed for profile %s", profile.pk)
        return None


def stat_rows(stats: dict | None) -> list[dict]:
    """Rows for the CSS/SVG bar chart: label, value and bar width in % of the max."""
    totals = (stats or {}).get("totals") or {}
    peak = max((totals.get(kind, 0) for kind, _label in STAT_KINDS), default=0) or 1
    return [
        {"kind": kind, "label": label, "value": totals.get(kind, 0), "pct": round(100 * totals.get(kind, 0) / peak)}
        for kind, label in STAT_KINDS
    ]


SERIES_HEIGHT = 60  # viewBox height of the daily SVG chart (each day is 10 units wide)


def series_rows(stats: dict | None) -> list[dict]:
    """Daily visits from `series` for the SVG bar chart: day, visits, x, y and bar height."""
    series = (stats or {}).get("series") or []
    peak = max((day.get("visit", 0) for day in series), default=0) or 1
    rows = []
    for index, day in enumerate(series):
        visits = day.get("visit", 0)
        height = round(SERIES_HEIGHT * visits / peak) if visits else 1
        rows.append(
            {"day": day["day"], "visits": visits, "x": index * 10 + 1, "y": SERIES_HEIGHT - height, "h": height}
        )
    return rows


# --- Sharing ---------------------------------------------------------------------------------


def share_text(profile: Profile) -> str:
    title = f" — {profile.title}" if profile.title else ""
    return _("Découvre ma page pro %(name)s%(title)s : %(url)s") % {
        "name": profile.display_name,
        "title": title,
        "url": profile.absolute_url,
    }


def whatsapp_share_url(profile: Profile) -> str:
    return "https://wa.me/?text=" + quote(share_text(profile))
