"""SEO head tags (plan §6.2): pure helpers, unit-tested in apps/seo/tests/test_meta.py.

Only `profile_meta` touches a model instance; every other function works on plain strings.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable

from django.conf import settings
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

TITLE_MAX = 60
DESCRIPTION_MIN = 150
DESCRIPTION_MAX = 160
ELLIPSIS = "…"
OG_IMAGE_WIDTH = 1200
OG_IMAGE_HEIGHT = 630

_SPACES_RE = re.compile(r"\s+")


def clean_text(text: str | None) -> str:
    """Plain text on one line: no HTML, no entities, single spaces."""
    if not text:
        return ""
    return _SPACES_RE.sub(" ", html.unescape(strip_tags(str(text)))).strip()


def truncate(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` characters, on a word boundary when possible, ending with "…"."""
    text = text.strip()
    if len(text) <= limit:
        return text
    if limit <= len(ELLIPSIS):
        return text[:limit]
    room = limit - len(ELLIPSIS)
    cut = text[: room + 1]
    space = cut.rfind(" ")
    # Only back off to a word boundary if we do not lose more than a quarter of the room.
    cut = cut[:space] if space >= max(1, room * 3 // 4) else cut[:room]
    return cut.rstrip(" ,;:.-–") + ELLIPSIS


def lower_first(text: str) -> str:
    """ "Plombier" -> "plombier" inside a sentence, but keep acronyms ("CEO") untouched."""
    if len(text) > 1 and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def absolute_url(path: str) -> str:
    """Absolute URL on the canonical host (settings.SITE_URL), never the request host."""
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{settings.SITE_URL}{path}"


def robots_content(indexable: bool) -> str:
    return "index, follow" if indexable else "noindex, follow"


def job_at_city(job: str, city: str) -> str:
    """ "Plombier à Douala", "Plombier", "Douala" or ""."""
    if job and city:
        return _("%(job)s à %(city)s") % {"job": job, "city": city}
    return job or city


def profile_title(name: str, job: str = "", city: str = "", max_len: int = TITLE_MAX) -> str:
    """`Nom – Métier à Ville` in at most `max_len` characters; the name is shortened first."""
    name = clean_text(name)
    job = clean_text(job)
    city = clean_text(city)
    for suffix_core in (job_at_city(job, city), job, ""):
        suffix = f" – {suffix_core}" if suffix_core else ""
        if len(name) + len(suffix) <= max_len:
            return name + suffix
        room = max_len - len(suffix)
        if suffix and room >= 12:  # keep a readable piece of the name
            return truncate(name, room) + suffix
    return truncate(name, max_len)


def _fit_description(text: str) -> str:
    return truncate(text, DESCRIPTION_MAX)


def profile_description(
    name: str,
    job: str = "",
    city: str = "",
    bio: str = "",
    services: Iterable[str] = (),
    *,
    has_whatsapp: bool = True,
) -> str:
    """150–160 characters: the cleaned bio, completed by a template when it is too short."""
    name, job, city = clean_text(name), clean_text(job), clean_text(city)
    services = [clean_text(s) for s in services if clean_text(s)]
    intro_core = job_at_city(lower_first(job), city)
    intro = f"{name}, {intro_core}." if intro_core else f"{name}."
    extras = [intro]
    if services:
        extras.append(_("Services : %(list)s.") % {"list": ", ".join(services[:4])})
    extras.append(_("Contact WhatsApp.") if has_whatsapp else _("Contact et coordonnées sur la page."))
    extras.append(_("Découvre ses prestations, ses réalisations et tous ses contacts sur sa page professionnelle."))

    text = clean_text(bio)
    if text and text[-1] not in ".!?…":
        text += "."
    if not text:
        text = extras.pop(0)
    for extra in extras:
        if len(text) >= DESCRIPTION_MIN:
            break
        text = f"{text} {extra}"
    return _fit_description(text)


def profile_alt(name: str, job: str = "", city: str = "") -> str:
    """Alt text for gallery images: « Réalisation de Nom, plombier à Douala »."""
    core = job_at_city(lower_first(job), city)
    if core:
        return _("Réalisation de %(name)s, %(job_city)s") % {"name": name, "job_city": core}
    return _("Réalisation de %(name)s") % {"name": name}


def page_meta(
    *,
    title: str,
    description: str,
    path: str,
    indexable: bool,
    image_url: str = "",
    og_type: str = "website",
    lang: str = "fr",
    image_size: tuple[int, int] | None = None,
) -> dict:
    """Everything the <head> needs, ready for templates/public/_seo_head.html."""
    canonical = absolute_url(path)
    return {
        "title": title,
        "description": description,
        "canonical": canonical,
        "robots": robots_content(indexable),
        "lang": lang,
        "og": {
            "type": og_type,
            "title": title,
            "description": description,
            "url": canonical,
            "image": absolute_url(image_url) if image_url else "",
            "image_width": image_size[0] if image_size else None,
            "image_height": image_size[1] if image_size else None,
            "site_name": settings.SITE_NAME,
            "locale": "en_US" if lang == "en" else "fr_FR",
        },
        "twitter_card": "summary_large_image" if image_url else "summary",
    }


def profile_meta(profile, *, indexable: bool | None = None, og_version: str = "") -> dict:
    """Head tags for a profile page. `indexable` defaults to the stored SEO state."""
    city = profile.city.name if profile.city else ""
    job = profile.title
    if indexable is None:
        indexable = bool(profile.is_indexable and profile.is_publicly_visible)
    og_path = f"/{profile.slug}/og.png" + (f"?v={og_version}" if og_version else "")
    meta = page_meta(
        title=profile_title(profile.display_name, job, city),
        description=profile_description(
            profile.display_name,
            job,
            city,
            profile.bio,
            [s.title for s in profile.services.all()],
            has_whatsapp=bool(profile.whatsapp),
        ),
        path=profile.get_absolute_url(),
        indexable=indexable,
        image_url=og_path,
        og_type="profile",
        lang=profile.language or "fr",
        image_size=(OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT),
    )
    return meta
