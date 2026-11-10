"""Image pipeline for profile photos and gallery pictures.

Every upload is decoded by Pillow (JPEG, PNG or WebP only), re-encoded as WebP (which drops every
metadata block: EXIF with GPS position, camera serial…) and saved with responsive variants:

    profiles/<pk>/photo/<uuid>.webp        main file (max 800 px for the photo, 1200 px for the gallery)
    profiles/<pk>/photo/<uuid>-160.webp    variants, only for widths smaller than the main file
    profiles/<pk>/photo/<uuid>-400.webp
    profiles/<pk>/gallery/<uuid>-800.webp  (gallery only: the photo is never wider than 800 px)

`apps.profiles.services.image_variants()` turns a stored file into a srcset-ready list.
"""

from __future__ import annotations

import contextlib
import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000  # refuse decompression bombs before decoding
PHOTO_MAX_SIDE = 800
GALLERY_MAX_SIDE = 1200
VARIANT_WIDTHS = (160, 400, 800)
MAIN_QUALITY = 80
VARIANT_QUALITY = 78


def _has_alpha(img) -> bool:
    if img.mode == "P":
        return "transparency" in img.info
    return True


def encode_webp(img) -> bytes:
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=MAIN_QUALITY, method=4, exif=b"", icc_profile=None)
    return out.getvalue()


def variant_widths(main_width: int) -> list[int]:
    """Widths of the variants generated for a main file of `main_width` pixels."""
    return [w for w in VARIANT_WIDTHS if w < main_width]


def process_image(uploaded, *, max_side: int = PHOTO_MAX_SIDE) -> ContentFile:
    """Validate `uploaded`, resize it and re-encode it as WebP.

    Returns the main file as a ContentFile named `<uuid>.webp`, with two extra attributes:
    `image_size` (width, height) and `variants` [(width, webp bytes), …] sorted by width.
    The EXIF orientation is applied first so that phone photos are not displayed sideways.
    """
    if uploaded is None:
        raise ValidationError(_("Choisis une photo."))
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise ValidationError(_("Cette photo est trop lourde (5 Mo maximum). Essaie une photo plus petite."))
    error = ValidationError(_("Ce fichier n'est pas une photo. Choisis une image JPG, PNG ou WebP."))
    try:
        uploaded.seek(0)
        with Image.open(uploaded, formats=ALLOWED_FORMATS) as probe:
            if probe.width * probe.height > MAX_SOURCE_PIXELS:
                raise ValidationError(_("Cette photo est trop grande. Essaie une photo plus petite."))
            probe.verify()
        uploaded.seek(0)
        with Image.open(uploaded, formats=ALLOWED_FORMATS) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") and _has_alpha(img) else img.convert("RGB")
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            img.info = {}  # convert() copies metadata: drop it explicitly
            main = encode_webp(img)
            variants = []
            for width in variant_widths(img.width):
                height = max(1, round(img.height * width / img.width))
                variants.append((width, encode_webp(img.resize((width, height), Image.Resampling.LANCZOS))))
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, TypeError, Image.DecompressionBombError) as exc:
        raise error from exc
    content = ContentFile(main, name=f"{uuid.uuid4().hex}.webp")
    content.image_size = img.size
    content.variants = variants
    return content


def _base(name: str) -> str:
    return name[: -len(".webp")] if name.endswith(".webp") else name.rsplit(".", 1)[0]


def variant_name(name: str, width: int) -> str:
    return f"{_base(name)}-{width}.webp"


def store_image(fieldfile, content: ContentFile) -> str:
    """Save the main file through the field (upload_to) and its variants next to it."""
    fieldfile.save(content.name, content, save=False)
    for width, data in getattr(content, "variants", []):
        fieldfile.storage.save(variant_name(fieldfile.name, width), ContentFile(data))
    return fieldfile.name


def stored_file_names(name: str) -> list[str]:
    """The main file and every possible variant (deletion ignores the missing ones)."""
    if not name:
        return []
    return [name, *(variant_name(name, w) for w in VARIANT_WIDTHS)]


def delete_stored_files(storage, names: list[str]) -> None:
    for name in names:
        with contextlib.suppress(FileNotFoundError, OSError):  # already gone
            storage.delete(name)
