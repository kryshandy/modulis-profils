"""Profile domain services: automatic page creation, slugs, completeness and SEO state.

Every profile creation goes through `get_or_create_profile` / `create_profile` (CLAUDE.md rule):
web sign-up, first card scan and field agents all share the same anti-duplicate logic.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.core.models import City, Trade

from .models import Profile, SlugRegistry

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
    """Erased slugs are stored hashed (right to erasure): we keep no name in clear."""
    return "h-" + hashlib.sha256(slug.encode()).hexdigest()[:40]


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
    return SlugRegistry.objects.filter(
        profile=profile, kind=SlugRegistry.Kind.OLD, created_at__gte=timezone.now() - timedelta(days=365)
    ).count()


@transaction.atomic
def change_slug(profile: Profile, new_slug: str) -> Profile:
    new_slug = (new_slug or "").strip().lower()
    if new_slug == profile.slug:
        return profile
    validate_slug_format(new_slug)
    if slug_changes_last_year(profile) >= settings.SLUG_MAX_CHANGES_PER_YEAR:
        raise ValidationError(_("Tu as déjà changé d'adresse 3 fois cette année."))
    if not profile.is_indexable and is_generic_slug(new_slug):
        raise ValidationError(
            _("Cette adresse est trop générique. Complète d'abord ta page, ou ajoute ton prénom (ex. paul-plombier).")
        )
    if not is_slug_available(new_slug):
        raise ValidationError(_("Cette adresse est déjà prise."))
    try:
        with transaction.atomic():
            SlugRegistry.objects.create(slug=new_slug, kind=SlugRegistry.Kind.CURRENT, profile=profile)
    except IntegrityError as exc:  # race: someone took it between the check and the insert
        raise ValidationError(_("Cette adresse est déjà prise.")) from exc
    SlugRegistry.objects.filter(slug=profile.slug, profile=profile).update(kind=SlugRegistry.Kind.OLD)
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
    from apps.accounts.services import get_or_create_user

    user, _created = get_or_create_user(phone_e164)
    existing = user.profiles.exclude(status=Profile.Status.DELETED).order_by("created_at").first()
    if existing:
        return user, existing, False
    if display_name and not user.full_name:
        user.full_name = display_name[:120]
        user.save(update_fields=["full_name"])
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


def is_bio_duplicated(profile: Profile) -> bool:
    if not profile.bio_fingerprint:
        return False
    return (
        Profile.objects.filter(bio_fingerprint=profile.bio_fingerprint, status=Profile.Status.ACTIVE)
        .exclude(pk=profile.pk)
        .exists()
    )


def indexability_blockers(profile: Profile) -> list[str]:
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
    if is_bio_duplicated(profile):
        reasons.append(_("La présentation est identique à celle d'une autre page : écris un texte personnel."))
    return reasons


def refresh_seo_state(profile: Profile, *, content_changed: bool = True) -> Profile:
    """Recompute score, fingerprint and indexability; queue an indexing notification if needed."""
    was_indexable = profile.is_indexable
    profile.bio_fingerprint = simhash(profile.bio) if len(profile.bio) >= 40 else ""
    profile.completeness_score = compute_completeness(profile)
    profile.is_indexable = not indexability_blockers(profile)
    fields = ["completeness_score", "is_indexable", "bio_fingerprint"]
    if content_changed:
        profile.content_updated_at = timezone.now()
        fields.append("content_updated_at")
    Profile.objects.filter(pk=profile.pk).update(**{f: getattr(profile, f) for f in fields})
    concerned = profile.is_indexable or was_indexable  # newly (non-)indexable pages must be (de)notified
    if concerned and (content_changed or profile.is_indexable != was_indexable):
        _queue_indexing([profile.absolute_url])
    return profile


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
    """Right to erasure: content wiped, URLs answer 410, cards disabled, slugs kept only as hashes."""
    from apps.cards.services import disable_cards_for_profile

    urls = [f"{settings.SITE_URL}/{entry.slug}" for entry in profile.slugs.all()]
    disable_cards_for_profile(profile, reason="profile_deleted")
    for entry in list(profile.slugs.all()):
        hashed = slug_hash(entry.slug)
        entry.delete()
        SlugRegistry.objects.get_or_create(slug=hashed, defaults={"kind": SlugRegistry.Kind.ERASED, "reason": "erased"})
    if profile.photo:
        profile.photo.delete(save=False)
    for media in profile.media.all():
        media.image.delete(save=False)
    profile.media.all().delete()
    profile.services.all().delete()
    profile.links.all().delete()
    Profile.objects.filter(pk=profile.pk).update(
        status=Profile.Status.DELETED,
        display_name="—",
        bio="",
        whatsapp="",
        phone_public="",
        email_public="",
        address="",
        maps_url="",
        is_indexable=False,
        slug=slug_hash(profile.slug)[:50],
    )
    _queue_indexing(urls)
