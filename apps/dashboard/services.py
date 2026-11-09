"""Dashboard helpers: active profile, image pipeline, ordering, stats adapter.

The profiles app exposes no CRUD service for page content yet, so every write to a profile's
own content (services, gallery, links) is centralised here, and always followed by
`profiles.services.refresh_seo_state`.
"""

from __future__ import annotations

import io
import logging
import uuid
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.profiles.models import Profile, ProfileLink, ProfileMedia, ProfileService
from apps.profiles.services import refresh_seo_state

logger = logging.getLogger(__name__)

SESSION_PROFILE_KEY = "dashboard_profile_id"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000  # refuse decompression bombs before decoding
PHOTO_MAX_SIDE = 800
GALLERY_MAX_SIDE = 1200
MAX_SERVICES = 20
MAX_MEDIA = 12
MAX_LINKS = 10

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


# --- Image pipeline --------------------------------------------------------------------------


def process_image(uploaded, *, max_side: int = PHOTO_MAX_SIDE) -> ContentFile:
    """Check that `uploaded` is a real image, resize it and re-encode it as WebP.

    Re-encoding drops every metadata block (EXIF with GPS position, camera serial…). The EXIF
    orientation is applied first so that phone photos are not displayed sideways.
    """
    if uploaded is None:
        raise ValidationError(_("Choisis une photo."))
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise ValidationError(_("Cette photo est trop lourde (5 Mo maximum). Essaie une photo plus petite."))
    error = ValidationError(_("Ce fichier n'est pas une photo. Choisis une image JPG, PNG ou WebP."))
    try:
        uploaded.seek(0)
        with Image.open(uploaded) as probe:
            if probe.width * probe.height > MAX_SOURCE_PIXELS:
                raise ValidationError(_("Cette photo est trop grande. Essaie une photo plus petite."))
            probe.verify()
        uploaded.seek(0)
        with Image.open(uploaded) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") and _has_alpha(img) else img.convert("RGB")
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            img.info = {}  # convert() copies metadata: drop it explicitly
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=80, method=4, exif=b"", icc_profile=None)
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise error from exc
    content = ContentFile(out.getvalue(), name=f"{uuid.uuid4().hex}.webp")
    content.image_size = img.size
    return content


def _has_alpha(img) -> bool:
    if img.mode == "P":
        return "transparency" in img.info
    return True


@transaction.atomic
def set_profile_photo(profile: Profile, uploaded) -> Profile:
    content = process_image(uploaded, max_side=PHOTO_MAX_SIDE)
    old = profile.photo.name if profile.photo else ""
    profile.photo.save(content.name, content, save=False)
    profile.save(update_fields=["photo", "updated_at"])
    if old:
        transaction.on_commit(lambda: profile.photo.storage.delete(old))
    refresh_seo_state(profile)
    return profile


@transaction.atomic
def remove_profile_photo(profile: Profile) -> Profile:
    if profile.photo:
        profile.photo.delete(save=False)
        profile.save(update_fields=["photo", "updated_at"])
        refresh_seo_state(profile)
    return profile


# --- Ordered children (services, gallery, links) ---------------------------------------------


def _next_order(queryset) -> int:
    return (queryset.aggregate(m=Max("order"))["m"] or 0) + 1


def move_item(queryset, item, direction: str) -> None:
    """Swap `item` with its neighbour inside `queryset` (already filtered by owner)."""
    items = list(queryset.order_by("order", "id"))
    for position, obj in enumerate(items):  # normalise so that orders are unique
        if obj.order != position:
            obj.order = position
            obj.save(update_fields=["order"])
    index = next(i for i, obj in enumerate(items) if obj.pk == item.pk)
    other = index - 1 if direction == "up" else index + 1
    if 0 <= other < len(items):
        a, b = items[index], items[other]
        a.order, b.order = b.order, a.order
        a.save(update_fields=["order"])
        b.save(update_fields=["order"])


@transaction.atomic
def add_service(profile: Profile, title: str, description: str = "", price_label: str = "") -> ProfileService:
    if profile.services.count() >= MAX_SERVICES:
        raise ValidationError(_("Tu as déjà %(n)d prestations : c'est le maximum.") % {"n": MAX_SERVICES})
    service = ProfileService.objects.create(
        profile=profile,
        title=title.strip()[:100],
        description=description.strip()[:300],
        price_label=price_label.strip()[:60],
        order=_next_order(profile.services),
    )
    refresh_seo_state(profile)
    return service


@transaction.atomic
def add_media(profile: Profile, uploaded, caption: str = "") -> ProfileMedia:
    if profile.media.count() >= MAX_MEDIA:
        raise ValidationError(_("Ta galerie est pleine (%(n)d photos). Supprime une photo d'abord.") % {"n": MAX_MEDIA})
    content = process_image(uploaded, max_side=GALLERY_MAX_SIDE)
    width, height = content.image_size
    media = ProfileMedia(
        profile=profile, caption=caption.strip()[:140], width=width, height=height, order=_next_order(profile.media)
    )
    media.image.save(content.name, content, save=False)
    media.save()
    refresh_seo_state(profile)
    return media


@transaction.atomic
def delete_media(media: ProfileMedia) -> None:
    profile = media.profile
    name = media.image.name
    storage = media.image.storage
    media.delete()
    if name:
        transaction.on_commit(lambda: storage.delete(name))
    refresh_seo_state(profile)


@transaction.atomic
def add_link(profile: Profile, kind: str, url: str) -> ProfileLink:
    if profile.links.count() >= MAX_LINKS:
        raise ValidationError(_("Tu as déjà %(n)d liens : c'est le maximum.") % {"n": MAX_LINKS})
    link = ProfileLink.objects.create(profile=profile, kind=kind, url=url, order=_next_order(profile.links))
    refresh_seo_state(profile)
    return link


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
    """Totals per event kind over 30 days, or None while the analytics app is not ready.

    Accepts the shapes `{kind: n}` or `{"totals": {kind: n}, "daily": [...]}`.
    """
    try:
        from apps.analytics.services import stats_for_profile
    except ImportError:
        return None
    try:
        try:
            raw = stats_for_profile(profile, days=30)
        except TypeError:
            raw = stats_for_profile(profile)
    except Exception:  # never break the dashboard because of statistics
        logger.exception("stats_for_profile failed for profile %s", profile.pk)
        return None
    if not isinstance(raw, dict):
        return None
    totals = raw.get("totals", raw)
    if not isinstance(totals, dict):
        return None
    clean = {}
    for kind, _label in STAT_KINDS:
        value = totals.get(kind, 0)
        if isinstance(value, dict):
            value = value.get("total", 0)
        try:
            clean[kind] = int(value or 0)
        except (TypeError, ValueError):
            clean[kind] = 0
    return {"totals": clean, "daily": raw.get("daily") if isinstance(raw.get("daily"), list) else []}


def stat_rows(stats: dict | None) -> list[dict]:
    """Rows for the CSS/SVG bar chart: label, value and bar width in % of the max."""
    totals = (stats or {}).get("totals") or {}
    peak = max(totals.values(), default=0) or 1
    return [
        {"kind": kind, "label": label, "value": totals.get(kind, 0), "pct": round(100 * totals.get(kind, 0) / peak)}
        for kind, label in STAT_KINDS
    ]


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
