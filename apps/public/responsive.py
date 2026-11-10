"""Responsive images (SEO audit 2026-11-10 #6): srcset/sizes from the WebP variants of an upload.

`apps.profiles.services.image_variants(fieldfile) -> [(url, width), …]` lists the smaller copies
(<name>-160.webp, -400.webp, -800.webp) when they exist. Until it is available, or when it fails,
pages fall back to a single `src`. Width and height attributes are always set (no layout shift).
"""

from __future__ import annotations

import logging

from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString

logger = logging.getLogger(__name__)

THUMB_SIZE = 56  # profile cards
THUMB_MAX_VARIANT = 160  # a 56 px thumbnail never downloads more than the 160 px copy
AVATAR_SIZE = 160  # profile page photo
AVATAR_MAX_VARIANT = 400  # 2.5× density at most: never the 800 px copy
GALLERY_SIZES = "(min-width: 40rem) 14rem, 50vw"  # profile.css: 2 columns, 3 from 40rem in a 42rem page


def variants(fieldfile) -> list[tuple[str, int]]:
    if not fieldfile:
        return []
    try:
        from apps.profiles import services
    except ImportError:  # pragma: no cover - profiles is always installed
        return []
    finder = getattr(services, "image_variants", None)
    if finder is None:
        return []
    try:
        found = finder(fieldfile) or []
        return sorted(((str(url), int(width)) for url, width in found if url and width), key=lambda v: v[1])
    except (OSError, ValueError, TypeError):  # storage hiccup or unexpected shape: single src
        logger.warning("image_variants failed for %s", getattr(fieldfile, "name", "?"))
        return []


def _url(fieldfile) -> str:
    try:
        return fieldfile.url
    except ValueError:  # no file associated
        return ""


def responsive_image(
    fieldfile,
    *,
    display_width: int,
    width: int | None = None,
    height: int | None = None,
    max_width: int | None = None,
    sizes: str = "",
    original_width: int | None = None,
) -> dict:
    """{src, srcset, sizes, width, height} for an <img> (or a preload link)."""
    found = variants(fieldfile)
    if max_width:
        # the smallest copy if none fits: still far lighter than the original
        found = [v for v in found if v[1] <= max_width] or found[:1]
    elif original_width and found and original_width > found[-1][1]:
        found = [*found, (_url(fieldfile), original_width)]
    if found:
        target = display_width * 2
        src = next((url for url, w in found if w >= target), found[-1][0])
        srcset = ", ".join(f"{url} {w}w" for url, w in found)
    else:
        src, srcset = _url(fieldfile), ""
    return {
        "src": src,
        "srcset": srcset,
        "sizes": (sizes or f"{display_width}px") if srcset else "",
        "width": width or display_width,
        "height": height or display_width,
    }


def img_attrs(image: dict) -> SafeString:
    """Escaped `src srcset sizes width height` attributes for a dict from responsive_image()."""
    pairs = [("src", image["src"])]
    if image.get("srcset"):
        pairs += [("srcset", image["srcset"]), ("sizes", image["sizes"])]
    pairs += [("width", image["width"]), ("height", image["height"])]
    return format_html_join(" ", '{}="{}"', pairs)


def preload_attrs(image: dict) -> SafeString:
    if image.get("srcset"):
        return format_html('href="{}" imagesrcset="{}" imagesizes="{}"', image["src"], image["srcset"], image["sizes"])
    return format_html('href="{}"', image["src"])
