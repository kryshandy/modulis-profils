"""Profile domain services: automatic page creation, slugs, page content, completeness and SEO state.

Every profile creation goes through `get_or_create_profile` / `create_profile` (CLAUDE.md rule):
web sign-up, first card scan and field agents all share the same anti-duplicate logic.
Every write to a page's content (fields, photo, services, gallery, links) goes through the
"Page content" functions below: other apps (dashboard, admin commands) never write these models.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import IntegrityError, models, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.core.models import City, Trade

from . import images
from .models import Profile, ProfileLink, ProfileMedia, ProfileService, SlugRegistry

logger = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,48}[a-z0-9])$")
SLUG_MIN, SLUG_MAX = 3, 50

# First-level URL segments used by the platform itself (must match config/urls.py; a test checks it).
SYSTEM_RESERVED_SLUGS = {
    "admin",
    "gestion",
    "espace",
    "c",
    "p",
    "a",
    "api",
    "static",
    "media",
    "villes",
    "metiers",
    "signaler",
    "sitemap",
    "sitemap-xml",
    "robots",
    "robots-txt",
    "favicon",
    "aide",
    "tarifs",
    "cgu",
    "confidentialite",
    "mentions-legales",
    "contact",
    "a-propos",
    "connexion",
    "inscription",
    "deconnexion",
    "compte",
    "carte",
    "cartes",
    "activer",
    "annuaire",
    "recherche",
    "blog",
    "www",
    "mail",
    "support",
    "modulis",
    "modulis-tech",
    "abonnement",
    "offres",
    "pro",
    "entreprise",
    "entreprises",
    "emploi",
    "emplois",
    "health",
    "healthz",
    "well-known",
}


# --- Slugs -----------------------------------------------------------------------------------


def slug_hash(slug: str) -> str:
    """Erased slugs are stored as a keyed hash (right to erasure).

    HMAC with a dedicated secret: a plain SHA-256 could be reversed with a dictionary of names.
    """
    digest = hmac.new(settings.SLUG_HASH_KEY.encode(), slug.encode(), hashlib.sha256).hexdigest()
    return "h-" + digest[:40]


def validate_slug_format(slug: str) -> None:
    if not (SLUG_MIN <= len(slug) <= SLUG_MAX) or not SLUG_RE.match(slug) or "--" in slug:
        raise ValidationError(_("L'adresse doit faire 3 à 50 caractères : lettres minuscules, chiffres et tirets."))


def is_slug_available(slug: str) -> bool:
    return not SlugRegistry.objects.filter(slug__in=[slug, slug_hash(slug)]).exists()


def is_generic_slug(slug: str) -> bool:
    """A single word, a trade or a city: only complete (indexable) profiles may claim it."""
    if "-" not in slug:
        return True
    return Trade.objects.filter(slug=slug).exists() or City.objects.filter(slug=slug).exists()


def _base_slug(text: str) -> str:
    return slugify(text)[:SLUG_MAX].strip("-")


def generate_slug(display_name: str, trade: Trade | None = None, city: City | None = None) -> str:
    """ange-kenmogne → ange-kenmogne-plombier → ange-kenmogne-plombier-douala → …-2…"""
    base = _base_slug(display_name) or "pro"
    if len(base) < SLUG_MIN:
        base = f"{base}-pro"
    candidates = [base]
    if trade:
        candidates.append(_base_slug(f"{base}-{trade.slug}"))
    if trade and city:
        candidates.append(_base_slug(f"{base}-{trade.slug}-{city.slug}"))
    elif city:
        candidates.append(_base_slug(f"{base}-{city.slug}"))
    for candidate in candidates:
        if "-" in candidate and is_slug_available(candidate):  # never auto-assign a one-word slug
            return candidate
    root = candidates[-1][: SLUG_MAX - 4]
    for n in range(2, 1000):
        candidate = f"{root}-{n}"
        if is_slug_available(candidate):
            return candidate
    raise RuntimeError("could not generate a free slug")  # pragma: no cover


def reserve_slug(slug: str, reason: str) -> bool:
    """Reserve a slug if free. Returns False (and logs) if a profile already owns it."""
    slug = slug.lower()
    existing = SlugRegistry.objects.filter(slug=slug).first()
    if existing is None:
        SlugRegistry.objects.create(slug=slug, kind=SlugRegistry.Kind.RESERVED, reason=reason)
        return True
    if existing.kind == SlugRegistry.Kind.RESERVED:
        return True
    logger.error("Cannot reserve %r (%s): already used by a profile", slug, reason)
    return False


def sync_reserved_slugs() -> None:
    for slug in SYSTEM_RESERVED_SLUGS:
        reserve_slug(slug, "system")
    for trade in Trade.objects.all():
        reserve_slug(trade.slug, "trade")
        reserve_slug(trade.plural_slug, "trade")
    for city in City.objects.all():
        reserve_slug(city.slug, "city")


def slug_changes_last_year(profile: Profile) -> int:
    """Slugs this profile retired during the last 365 days (the date of retirement, not of creation)."""
    return SlugRegistry.objects.filter(
        profile=profile, kind=SlugRegistry.Kind.OLD, retired_at__gte=timezone.now() - timedelta(days=365)
    ).count()


@transaction.atomic
def change_slug(profile: Profile, new_slug: str) -> Profile:
    """Give `profile` a new address; the previous one becomes OLD (301 forever).

    A profile may go back to one of ITS OWN old slugs: the two registry entries swap kinds.
    """
    new_slug = (new_slug or "").strip().lower()
    if new_slug == profile.slug:
        return profile
    validate_slug_format(new_slug)
    if slug_changes_last_year(profile) >= settings.SLUG_MAX_CHANGES_PER_YEAR:
        raise ValidationError(_("Tu as déjà changé d'adresse 3 fois cette année."))
    own_old = (
        SlugRegistry.objects.select_for_update()
        .filter(slug=new_slug, profile=profile, kind=SlugRegistry.Kind.OLD)
        .first()
    )
    if own_old is not None:
        own_old.kind = SlugRegistry.Kind.CURRENT
        own_old.retired_at = None
        own_old.save(update_fields=["kind", "retired_at"])
    else:
        if not profile.is_indexable and is_generic_slug(new_slug):
            raise ValidationError(
                _(
                    "Cette adresse est trop générique. Complète d'abord ta page, "
                    "ou ajoute ton prénom (ex. paul-plombier)."
                )
            )
        if not is_slug_available(new_slug):
            raise ValidationError(_("Cette adresse est déjà prise."))
        try:
            with transaction.atomic():
                SlugRegistry.objects.create(slug=new_slug, kind=SlugRegistry.Kind.CURRENT, profile=profile)
        except IntegrityError as exc:  # race: someone took it between the check and the insert
            raise ValidationError(_("Cette adresse est déjà prise.")) from exc
    SlugRegistry.objects.filter(slug=profile.slug, profile=profile).update(
        kind=SlugRegistry.Kind.OLD, retired_at=timezone.now()
    )
    old_url = profile.absolute_url
    profile.slug = new_slug
    profile.save(update_fields=["slug", "updated_at"])
    _queue_indexing([old_url, profile.absolute_url])
    return profile


def resolve_slug(slug: str) -> tuple[str | None, Profile | None]:
    """Return (kind, profile) for a first-level segment, or (None, None) if unknown."""
    slug = slug.lower()
    entry = SlugRegistry.objects.select_related("profile").filter(slug__in=[slug, slug_hash(slug)]).first()
    if entry is None:
        return None, None
    return entry.kind, entry.profile


# --- Profile creation ------------------------------------------------------------------------


@transaction.atomic
def create_profile(
    user,
    display_name: str,
    *,
    trade: Trade | None = None,
    city: City | None = None,
    kind: str = Profile.Kind.PERSON,
    created_by_agent=None,
    **fields,
) -> Profile:
    display_name = (display_name or "").strip()[:80] or user.full_name or _("Mon activité")
    for _attempt in range(5):
        slug = generate_slug(display_name, trade, city)
        try:
            with transaction.atomic():
                profile = Profile.objects.create(
                    user=user,
                    slug=slug,
                    display_name=display_name,
                    trade=trade,
                    city=city,
                    kind=kind,
                    created_by_agent=created_by_agent,
                    whatsapp=fields.pop("whatsapp", user.phone),
                    phone_public=fields.pop("phone_public", user.phone),
                    **fields,
                )
                SlugRegistry.objects.create(slug=slug, kind=SlugRegistry.Kind.CURRENT, profile=profile)
        except IntegrityError:
            continue  # concurrent creation took the slug: try the next candidate
        refresh_seo_state(profile)
        return profile
    raise RuntimeError("could not create profile")  # pragma: no cover


def get_or_create_profile(phone_e164: str, display_name: str = "", **kwargs) -> tuple[object, Profile, bool]:
    """The single entry point for automatic page creation (plan §5.1).

    `phone_e164` must have been verified by OTP. If the account already has an active profile,
    it is returned unchanged: one phone never produces a duplicate page.
    """
    from apps.accounts.models import User
    from apps.accounts.services import get_or_create_user, set_full_name

    user, _created = get_or_create_user(phone_e164)
    with transaction.atomic():
        # Lock the account row: a double tap or a login + card activation in parallel must not
        # both see "no profile" and create two pages (code review #1).
        User.objects.select_for_update().filter(pk=user.pk).first()
        existing = user.profiles.exclude(status=Profile.Status.DELETED).order_by("created_at").first()
        if existing:
            return user, existing, False
        set_full_name(user, display_name)
        return user, create_profile(user, display_name, **kwargs), True


# --- Completeness & SEO state (plan §6.6) ----------------------------------------------------

WORD_RE = re.compile(r"\w+", re.UNICODE)


def own_words(profile: Profile) -> int:
    text = " ".join([profile.bio] + [f"{s.title} {s.description}" for s in profile.services.all()])
    return len(WORD_RE.findall(text))


def completeness_items(profile: Profile) -> list[dict]:
    """Checklist used both for the score and for the dashboard gauge."""
    has_contact = bool(profile.whatsapp or profile.phone_public)
    gallery = profile.media.count()
    links = profile.links.count()
    return [
        {"key": "photo", "label": _("Ajoute une photo"), "points": 20, "done": bool(profile.photo)},
        {
            "key": "trade_city",
            "label": _("Indique ton métier et ta ville"),
            "points": 20,
            "done": bool((profile.trade or profile.custom_title) and profile.city),
        },
        {
            "key": "bio",
            "label": _("Écris ta présentation (120 caractères minimum)"),
            "points": 20,
            "done": len(profile.bio.strip()) >= settings.SEO_MIN_BIO_CHARS,
        },
        {
            "key": "services",
            "label": _("Ajoute au moins 2 prestations"),
            "points": 15,
            "done": profile.services.count() >= 2,
        },
        {"key": "contact", "label": _("Ajoute ton WhatsApp ou ton téléphone"), "points": 15, "done": has_contact},
        {
            "key": "gallery",
            "label": _("Ajoute 3 photos de tes réalisations (ou 2 liens)"),
            "points": 10,
            "done": gallery >= 3 or links >= 2,
        },
    ]


def compute_completeness(profile: Profile) -> int:
    return sum(item["points"] for item in completeness_items(profile) if item["done"])


def simhash(text: str) -> str:
    """64-bit SimHash of a text: near-identical bios produce the same fingerprint."""
    tokens = [t for t in WORD_RE.findall(text.lower()) if len(t) > 2]
    if not tokens:
        return ""
    vector = [0] * 64
    for token in tokens:
        h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            vector[bit] += 1 if h >> bit & 1 else -1
    value = sum(1 << bit for bit in range(64) if vector[bit] > 0)
    return f"{value:016x}"


NEAR_DUPLICATE_MAX_DISTANCE = 10  # Hamming distance between two 64-bit SimHashes


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def find_bio_original(profile: Profile) -> Profile | None:
    """Return an OLDER active profile whose bio is (nearly) identical, or None.

    The oldest page keeps its indexing: only the copy is penalised (SEO audit #2). Candidates are
    limited to the same trade or city, which is where copy-pasted bios happen (field agents).
    """
    if not profile.bio_fingerprint:
        return None
    candidates = (
        Profile.objects.filter(status=Profile.Status.ACTIVE, created_at__lt=profile.created_at)
        .exclude(pk=profile.pk)
        .exclude(bio_fingerprint="")
        .filter(models.Q(trade_id=profile.trade_id) | models.Q(city_id=profile.city_id))
        .only("pk", "bio_fingerprint", "slug")
    )
    for other in candidates.iterator():
        if hamming(profile.bio_fingerprint, other.bio_fingerprint) <= NEAR_DUPLICATE_MAX_DISTANCE:
            return other
    return None


def is_bio_duplicated(profile: Profile) -> bool:
    return find_bio_original(profile) is not None


_UNSET = object()


def indexability_blockers(profile: Profile, *, bio_original=_UNSET) -> list[str]:
    """Reasons why `profile` is not indexable. `bio_original` avoids a second duplicate lookup."""
    reasons = []
    if not profile.is_publicly_visible:
        reasons.append(_("La page est privée ou suspendue."))
    if profile.completeness_score < settings.SEO_INDEXABLE_MIN_SCORE:
        reasons.append(_("La page est complète à moins de %(n)d %%.") % {"n": settings.SEO_INDEXABLE_MIN_SCORE})
    if len(profile.bio.strip()) < settings.SEO_MIN_BIO_CHARS:
        reasons.append(_("La présentation est trop courte."))
    if own_words(profile) < settings.SEO_MIN_OWN_WORDS:
        reasons.append(
            _("Il faut au moins %(n)d mots de texte (présentation + prestations).") % {"n": settings.SEO_MIN_OWN_WORDS}
        )
    duplicated = is_bio_duplicated(profile) if bio_original is _UNSET else bio_original is not None
    if duplicated:
        reasons.append(_("La présentation est identique à celle d'une autre page : écris un texte personnel."))
    return reasons


def refresh_seo_state(profile: Profile, *, content_changed: bool = True) -> Profile:
    """Recompute score, fingerprint and indexability; queue an indexing notification if needed.

    A near-duplicate of an older page's bio is also sent to moderation (one open report at most).
    """
    was_indexable = profile.is_indexable
    profile.bio_fingerprint = simhash(profile.bio) if len(profile.bio) >= 40 else ""
    profile.completeness_score = compute_completeness(profile)
    original = find_bio_original(profile)
    profile.is_indexable = not indexability_blockers(profile, bio_original=original)
    if original is not None and profile.status == Profile.Status.ACTIVE:
        from apps.moderation.services import report_duplicate_bio

        report_duplicate_bio(profile, original)
    fields = ["completeness_score", "is_indexable", "bio_fingerprint"]
    if content_changed:
        profile.content_updated_at = timezone.now()
        fields.append("content_updated_at")
    Profile.objects.filter(pk=profile.pk).update(**{f: getattr(profile, f) for f in fields})
    concerned = profile.is_indexable or was_indexable  # newly (non-)indexable pages must be (de)notified
    if concerned and (content_changed or profile.is_indexable != was_indexable):
        urls = [profile.absolute_url]
        if profile.is_indexable != was_indexable:  # city and trade×city listings change too
            urls += _related_urls(profile)
        _queue_indexing(urls)
    return profile


def _related_urls(profile: Profile) -> list[str]:
    from apps.seo.indexing import related_urls

    return related_urls(profile)


def _queue_indexing(urls: list[str]) -> None:
    from apps.seo.indexing import queue_urls

    transaction.on_commit(lambda: queue_urls(urls))


# --- Moderation & lifecycle ------------------------------------------------------------------


@transaction.atomic
def suspend_profile(profile: Profile, reason: str) -> None:
    profile.status = Profile.Status.SUSPENDED
    profile.suspended_reason = reason[:200]
    profile.save(update_fields=["status", "suspended_reason", "updated_at"])
    refresh_seo_state(profile, content_changed=False)


@transaction.atomic
def reactivate_profile(profile: Profile) -> None:
    profile.status = Profile.Status.ACTIVE
    profile.suspended_reason = ""
    profile.save(update_fields=["status", "suspended_reason", "updated_at"])
    refresh_seo_state(profile, content_changed=False)


@transaction.atomic
def delete_profile(profile: Profile) -> None:
    """Right to erasure: content wiped, URLs answer 410, cards disabled, slugs kept only as hashes.

    Files are deleted only after the transaction commits (a rollback must not lose them), and the
    account itself is anonymised when its last page is deleted (security audit I6).
    """
    from apps.accounts.services import anonymize_user
    from apps.cards.services import disable_cards_for_profile

    urls = [f"{settings.SITE_URL}/{entry.slug}" for entry in profile.slugs.all()]
    if profile.is_indexable:
        urls += _related_urls(profile)  # computed before the wipe
    disable_cards_for_profile(profile, reason="profile_deleted")
    for entry in list(profile.slugs.all()):
        hashed = slug_hash(entry.slug)
        entry.delete()
        SlugRegistry.objects.get_or_create(slug=hashed, defaults={"kind": SlugRegistry.Kind.ERASED, "reason": "erased"})

    files = images.stored_file_names(profile.photo.name) if profile.photo else []
    for media in profile.media.all():
        files += images.stored_file_names(media.image.name)
    pk = profile.pk
    profile.media.all().delete()
    profile.services.all().delete()
    profile.links.all().delete()
    Profile.objects.filter(pk=pk).update(
        status=Profile.Status.DELETED,
        display_name="—",
        custom_title="",
        district="",
        service_area="",
        bio="",
        photo="",
        photo_width=0,
        photo_height=0,
        latitude=None,
        longitude=None,
        opening_hours={},
        price_range="",
        whatsapp="",
        phone_public="",
        email_public="",
        address="",
        maps_url="",
        bio_fingerprint="",
        is_indexable=False,
        slug=slug_hash(profile.slug)[:50],
    )
    if not profile.user.profiles.exclude(status=Profile.Status.DELETED).exists():
        anonymize_user(profile.user)
    transaction.on_commit(lambda: _delete_files(files, og_prefix=f"{pk}-"))
    _queue_indexing(urls)


def _delete_files(names: list[str], *, og_prefix: str) -> None:
    images.delete_stored_files(default_storage, names)
    try:  # cached share images og/<pk>-<fingerprint>.png (apps.public.images)
        _dirs, og_files = default_storage.listdir("og")
    except (FileNotFoundError, NotImplementedError, OSError):
        og_files = []
    for name in og_files:
        if name.startswith(og_prefix):
            default_storage.delete(f"og/{name}")


# --- Page content (the ONLY writers of Profile / ProfileService / ProfileMedia / ProfileLink) ----

MAX_SERVICES = 20
MAX_MEDIA = 12
MAX_LINKS = 10

# Fields a pro (or a script) may change through update_profile(). Status, slug, verification,
# SEO state and photo have dedicated services.
EDITABLE_PROFILE_FIELDS = frozenset(
    {
        "display_name",
        "kind",
        "is_feminine",
        "trade",
        "custom_title",
        "city",
        "district",
        "service_area",
        "language",
        "bio",
        "cover_color",
        "whatsapp",
        "phone_public",
        "email_public",
        "address",
        "maps_url",
        "latitude",
        "longitude",
        "opening_hours",
        "price_range",
        "visibility",
    }
)
# Changing only these does not change the page's text (no new content_updated_at).
PRESENTATION_ONLY_FIELDS = frozenset({"cover_color", "visibility"})
CHOICE_FIELDS = {
    "kind": Profile.Kind.values,
    "language": Profile.Language.values,
    "visibility": Profile.Visibility.values,
}

OPENING_DAYS = ("mo", "tu", "we", "th", "fr", "sa", "su")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
MAX_RANGES_PER_DAY = 3


def _lock_profile(profile: Profile) -> None:
    """Row lock on the profile: serialises MAX checks and ordering (double taps, two tabs)."""
    list(Profile.objects.select_for_update().filter(pk=profile.pk).values_list("pk", flat=True))


def normalize_opening_hours(value) -> dict:
    """Validate {"mo": [["08:00", "18:00"]], ...}; returns a clean dict in week order (closed days omitted)."""
    if not value:
        return {}
    error = ValidationError(_("Horaires invalides : indique des heures comme 08:00, l'ouverture avant la fermeture."))
    if not isinstance(value, dict):
        raise error
    clean = {}
    for day, ranges in value.items():
        if day not in OPENING_DAYS or not isinstance(ranges, list | tuple) or len(ranges) > MAX_RANGES_PER_DAY:
            raise error
        day_ranges = []
        for item in ranges:
            if not (isinstance(item, list | tuple) and len(item) == 2):
                raise error
            start, end = item
            if not (isinstance(start, str) and isinstance(end, str) and TIME_RE.match(start) and TIME_RE.match(end)):
                raise error
            if start >= end:
                raise error
            day_ranges.append([start, end])
        if day_ranges:
            clean[day] = sorted(day_ranges)
    return {day: clean[day] for day in OPENING_DAYS if day in clean}


def _clean_coordinate(value, limit: int):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(_("Coordonnée GPS invalide.")) from exc
    if not -limit <= number <= limit:
        raise ValidationError(_("Coordonnée GPS invalide."))
    return number


def _clean_profile_fields(fields: dict) -> dict:
    unknown = set(fields) - EDITABLE_PROFILE_FIELDS
    if unknown:
        raise ValueError(f"update_profile: non-editable field(s) {sorted(unknown)}")
    for name, allowed in CHOICE_FIELDS.items():
        if name in fields and fields[name] not in allowed:
            raise ValidationError(_("Valeur invalide."))
    if "opening_hours" in fields:
        fields["opening_hours"] = normalize_opening_hours(fields["opening_hours"])
    if "latitude" in fields:
        fields["latitude"] = _clean_coordinate(fields["latitude"], 90)
    if "longitude" in fields:
        fields["longitude"] = _clean_coordinate(fields["longitude"], 180)
    if "price_range" in fields:
        fields["price_range"] = " ".join((fields["price_range"] or "").split())[:20]
    return fields


@transaction.atomic
def update_profile(profile: Profile, **fields) -> Profile:
    """Write page fields (whitelisted), then recompute the SEO state.

    ModelForms may be validated with `save(commit=False)` and their values passed here.
    """
    if not fields:
        return profile
    fields = _clean_profile_fields(dict(fields))
    _lock_profile(profile)
    moved = profile.is_indexable and any(
        name in fields and fields[name] != getattr(profile, name) for name in ("city", "trade")
    )
    old_listings = _related_urls(profile) if moved else []  # the listings it leaves must be refreshed
    for name, value in fields.items():
        setattr(profile, name, value)
    profile.save(update_fields=[*fields, "updated_at"])
    refresh_seo_state(profile, content_changed=bool(set(fields) - PRESENTATION_ONLY_FIELDS))
    if old_listings:
        _queue_indexing(old_listings + _related_urls(profile))
    return profile


def set_language(profile: Profile, language: str) -> Profile:
    """The page language changes its title, meta and JSON-LD: it is a content change."""
    return update_profile(profile, language=language)


@transaction.atomic
def mark_onboarding_completed(profile: Profile) -> Profile:
    if profile.onboarding_completed_at is None:
        profile.onboarding_completed_at = timezone.now()
        profile.save(update_fields=["onboarding_completed_at", "updated_at"])
    return profile


@transaction.atomic
def mark_tour_completed(profile: Profile) -> Profile:
    if profile.tour_completed_at is None:
        profile.tour_completed_at = timezone.now()
        profile.save(update_fields=["tour_completed_at", "updated_at"])
    return profile


def _delete_files_on_commit(storage, name: str) -> None:
    names = images.stored_file_names(name)
    if names:
        transaction.on_commit(lambda: images.delete_stored_files(storage, names))


# Photo -----------------------------------------------------------------------------------------


@transaction.atomic
def set_photo(profile: Profile, uploaded) -> Profile:
    """Replace the profile photo (WebP + variants); the previous files are deleted after commit."""
    content = images.process_image(uploaded, max_side=images.PHOTO_MAX_SIDE)
    _lock_profile(profile)
    old = profile.photo.name if profile.photo else ""
    images.store_image(profile.photo, content)
    profile.photo_width, profile.photo_height = content.image_size
    profile.save(update_fields=["photo", "photo_width", "photo_height", "updated_at"])
    if old:
        _delete_files_on_commit(profile.photo.storage, old)
    refresh_seo_state(profile)
    return profile


@transaction.atomic
def remove_photo(profile: Profile) -> Profile:
    if not profile.photo:
        return profile
    _lock_profile(profile)
    old, storage = profile.photo.name, profile.photo.storage
    profile.photo = ""
    profile.photo_width = profile.photo_height = 0
    profile.save(update_fields=["photo", "photo_width", "photo_height", "updated_at"])
    _delete_files_on_commit(storage, old)
    refresh_seo_state(profile)
    return profile


def image_variants(fieldfile) -> list[tuple[str, int]]:
    """Responsive sources of a stored photo or gallery image: [(url, width), ...] ascending.

    The main file is always last, with its real width (0 when unknown: legacy upload without
    variants, run `manage.py build_image_variants`). Use it for `srcset="url 160w, url 400w, ..."`.
    """
    if not fieldfile:
        return []
    instance = fieldfile.instance
    width = instance.photo_width if isinstance(instance, Profile) else int(getattr(instance, "width", 0) or 0)
    storage = fieldfile.storage
    sources = [(storage.url(images.variant_name(fieldfile.name, w)), w) for w in images.variant_widths(width)]
    sources.append((fieldfile.url, width))
    return sources


# Ordered children ------------------------------------------------------------------------------

_CHILDREN = {"service": "services", "media": "media", "link": "links"}


def _next_order(queryset) -> int:
    return (queryset.aggregate(m=Max("order"))["m"] or 0) + 1


@transaction.atomic
def move_item(profile: Profile, kind: str, item_id: int, direction: str) -> None:
    """Swap a service / gallery image / link of `profile` with its neighbour ("up" or "down").

    Raises <Model>.DoesNotExist if the item does not belong to `profile` (no IDOR).
    """
    if kind not in _CHILDREN or direction not in ("up", "down"):
        raise ValueError("move_item: bad kind or direction")
    _lock_profile(profile)
    queryset = getattr(profile, _CHILDREN[kind]).all()
    item = queryset.get(pk=item_id)
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


# Services --------------------------------------------------------------------------------------


@transaction.atomic
def add_service(profile: Profile, title: str, description: str = "", price_label: str = "") -> ProfileService:
    title = (title or "").strip()[:100]
    if not title:
        raise ValidationError(_("Le nom de la prestation est obligatoire."))
    _lock_profile(profile)
    if profile.services.count() >= MAX_SERVICES:
        raise ValidationError(_("Tu as déjà %(n)d prestations : c'est le maximum.") % {"n": MAX_SERVICES})
    service = ProfileService.objects.create(
        profile=profile,
        title=title,
        description=(description or "").strip()[:300],
        price_label=(price_label or "").strip()[:60],
        order=_next_order(profile.services),
    )
    refresh_seo_state(profile)
    return service


@transaction.atomic
def update_service(
    profile: Profile, service_id: int, *, title: str, description: str = "", price_label: str = ""
) -> ProfileService:
    title = (title or "").strip()[:100]
    if not title:
        raise ValidationError(_("Le nom de la prestation est obligatoire."))
    service = profile.services.get(pk=service_id)
    service.title = title
    service.description = (description or "").strip()[:300]
    service.price_label = (price_label or "").strip()[:60]
    service.save(update_fields=["title", "description", "price_label"])
    refresh_seo_state(profile)
    return service


@transaction.atomic
def delete_service(profile: Profile, service_id: int) -> None:
    profile.services.get(pk=service_id).delete()
    refresh_seo_state(profile)


# Gallery ---------------------------------------------------------------------------------------


def _check_media_room(profile: Profile) -> None:
    if profile.media.count() >= MAX_MEDIA:
        raise ValidationError(_("Ta galerie est pleine (%(n)d photos). Supprime une photo d'abord.") % {"n": MAX_MEDIA})


@transaction.atomic
def add_media(profile: Profile, uploaded, caption: str = "") -> ProfileMedia:
    _check_media_room(profile)  # fail fast, before decoding the image
    content = images.process_image(uploaded, max_side=images.GALLERY_MAX_SIDE)
    _lock_profile(profile)
    _check_media_room(profile)  # again under the lock (parallel uploads)
    width, height = content.image_size
    media = ProfileMedia(
        profile=profile,
        caption=(caption or "").strip()[:140],
        width=width,
        height=height,
        order=_next_order(profile.media),
    )
    images.store_image(media.image, content)
    media.save()
    refresh_seo_state(profile)
    return media


@transaction.atomic
def update_media(profile: Profile, media_id: int, *, caption: str) -> ProfileMedia:
    media = profile.media.get(pk=media_id)
    media.caption = (caption or "").strip()[:140]
    media.save(update_fields=["caption"])
    refresh_seo_state(profile)
    return media


@transaction.atomic
def delete_media(profile: Profile, media_id: int) -> None:
    media = profile.media.get(pk=media_id)
    name, storage = media.image.name, media.image.storage
    media.delete()
    _delete_files_on_commit(storage, name)
    refresh_seo_state(profile)


def set_cover(profile: Profile, media_id: int | None) -> None:
    """Use one of the page's own gallery photos as cover image (None = back to the drawn composition)."""
    media = profile.media.get(pk=media_id) if media_id else None  # foreign id: DoesNotExist
    Profile.objects.filter(pk=profile.pk).update(cover=media, updated_at=timezone.now())
    profile.cover = media
    refresh_seo_state(profile)


# Links -----------------------------------------------------------------------------------------


def _clean_link(kind: str, url: str) -> tuple[str, str]:
    if kind not in ProfileLink.Kind.values:
        raise ValidationError(_("Type de lien invalide."))
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or len(url) > 300:
        raise ValidationError(_("Le lien doit commencer par https://"))
    return kind, url


@transaction.atomic
def add_link(profile: Profile, kind: str, url: str) -> ProfileLink:
    kind, url = _clean_link(kind, url)
    _lock_profile(profile)
    if profile.links.count() >= MAX_LINKS:
        raise ValidationError(_("Tu as déjà %(n)d liens : c'est le maximum.") % {"n": MAX_LINKS})
    link = ProfileLink.objects.create(profile=profile, kind=kind, url=url, order=_next_order(profile.links))
    refresh_seo_state(profile)
    return link


@transaction.atomic
def update_link(profile: Profile, link_id: int, *, kind: str, url: str) -> ProfileLink:
    kind, url = _clean_link(kind, url)
    link = profile.links.get(pk=link_id)
    link.kind, link.url = kind, url
    link.save(update_fields=["kind", "url"])
    refresh_seo_state(profile)
    return link


@transaction.atomic
def delete_link(profile: Profile, link_id: int) -> None:
    profile.links.get(pk=link_id).delete()
    refresh_seo_state(profile)
