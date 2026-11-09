"""Generated images: Open Graph card (1200×630 PNG) and QR codes (segno)."""

from __future__ import annotations

import hashlib
import io
import logging
from functools import lru_cache
from pathlib import Path

import segno
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageDraw, ImageFont, ImageOps

from apps.seo.meta import OG_IMAGE_HEIGHT, OG_IMAGE_WIDTH, clean_text

logger = logging.getLogger(__name__)

BRAND_TEAL = "#0A7F7D"
BRAND_CORAL = "#FD6552"
WHITE = "#FFFFFF"
OG_VERSION = "1"  # bump to regenerate every cached card after a design change

_FONT_CANDIDATES = {
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False):
    for candidate in _FONT_CANDIDATES[bold]:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:  # pragma: no cover - unreadable font file
                continue
    return ImageFont.load_default(size=size)  # Pillow ≥ 10.1 ships a scalable fallback


def _fit_lines(draw: ImageDraw.ImageDraw, text: str, max_width: int, sizes, bold: bool, max_lines: int = 2):
    """Pick the largest font size for which `text` wraps into at most `max_lines` lines."""
    words = text.split() or [""]
    for size in sizes:
        font = _font(size, bold)
        lines, current = [], ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)
        if len(lines) <= max_lines and all(draw.textlength(line, font=font) <= max_width for line in lines):
            return font, lines
    font = _font(sizes[-1], bold)
    lines = lines[:max_lines]
    while lines and draw.textlength(lines[-1] + "…", font=font) > max_width and len(lines[-1]) > 1:
        lines[-1] = lines[-1][:-1]
    lines[-1] = lines[-1].rstrip() + "…"
    return font, lines


def _open_photo(profile) -> Image.Image | None:
    if not profile.photo:
        return None
    try:
        with profile.photo.open("rb") as handle:
            photo = Image.open(handle)
            photo.load()
        return ImageOps.fit(photo.convert("RGB"), (260, 260))
    except Exception:  # a broken upload must never break the share card
        logger.warning("Could not read photo of profile %s for og.png", profile.pk)
        return None


def render_og_image(name: str, title: str = "", city: str = "", photo: Image.Image | None = None) -> bytes:
    """Brand card: teal background, coral accent, name / job / city, optional round photo."""
    image = Image.new("RGB", (OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT), BRAND_TEAL)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, OG_IMAGE_HEIGHT - 24, OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT], fill=BRAND_CORAL)
    left, text_width = 80, OG_IMAGE_WIDTH - 160
    if photo is not None:
        mask = Image.new("L", photo.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, *photo.size], fill=255)
        image.paste(photo, (OG_IMAGE_WIDTH - 80 - photo.width, 150), mask)
        draw.ellipse(
            [OG_IMAGE_WIDTH - 86 - photo.width, 144, OG_IMAGE_WIDTH - 74, 156 + photo.height],
            outline=BRAND_CORAL,
            width=6,
        )
        text_width -= photo.width + 40

    name_font, name_lines = _fit_lines(draw, clean_text(name) or "—", text_width, (84, 72, 62, 54), bold=True)
    y = 150
    for line in name_lines:
        draw.text((left, y), line, font=name_font, fill=WHITE)
        y += int(name_font.size * 1.15)
    y += 20
    draw.rectangle([left, y, left + 120, y + 8], fill=BRAND_CORAL)
    y += 40
    subtitle = " · ".join(part for part in (clean_text(title), clean_text(city)) if part)
    if subtitle:
        sub_font, sub_lines = _fit_lines(draw, subtitle, text_width, (46, 40, 34), bold=False, max_lines=2)
        for line in sub_lines:
            draw.text((left, y), line, font=sub_font, fill=WHITE)
            y += int(sub_font.size * 1.25)
    draw.text((left, OG_IMAGE_HEIGHT - 90), settings.SITE_NAME, font=_font(32, bold=True), fill=WHITE)

    buffer = io.BytesIO()
    image.quantize(colors=64, method=Image.Quantize.MEDIANCUT).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def og_fingerprint(profile) -> str:
    parts = [
        OG_VERSION,
        str(profile.pk),
        profile.display_name,
        profile.title,
        profile.city.name if profile.city else "",
        profile.photo.name if profile.photo else "",
        profile.content_updated_at.isoformat() if profile.content_updated_at else "",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def og_image_for(profile) -> bytes:
    """Return the PNG, cached in the default storage under og/<pk>-<fingerprint>.png."""
    path = f"og/{profile.pk}-{og_fingerprint(profile)}.png"
    try:
        if default_storage.exists(path):
            with default_storage.open(path, "rb") as handle:
                return handle.read()
    except Exception:  # storage hiccup: regenerate
        logger.warning("Could not read cached %s", path)
    data = render_og_image(
        profile.display_name, profile.title, profile.city.name if profile.city else "", _open_photo(profile)
    )
    try:
        default_storage.save(path, ContentFile(data))
    except Exception:  # caching is best effort only
        logger.warning("Could not cache %s", path)
    return data


def qr_code(target: str) -> segno.QRCode:
    return segno.make(target, error="m", micro=False)


def qr_svg(target: str) -> bytes:
    buffer = io.BytesIO()
    qr_code(target).save(buffer, kind="svg", scale=10, border=2, dark="#000000", light="#FFFFFF", xmldecl=True)
    return buffer.getvalue()


def qr_png(target: str) -> bytes:
    buffer = io.BytesIO()
    qr_code(target).save(buffer, kind="png", scale=12, border=2, dark="#000000", light="#FFFFFF")
    return buffer.getvalue()
