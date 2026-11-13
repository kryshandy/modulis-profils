"""Page builder services: validate block content, store its images, place blocks among the sections.

Rules kept by every function here (ADR-0012):
- content = plain text from the registry fields only, lengths capped, control characters removed;
- links = https only (button) or a recognised YouTube / Vimeo video (rendered as an embed that only
  loads on click, from the privacy-friendly domains);
- images = the same pipeline as the gallery (real type check, re-encoding to WebP, metadata and
  geolocation stripped, size caps, variants), files deleted after commit;
- at most MAX_BLOCKS blocks and MAX_BLOCK_IMAGES images per page;
- a block hidden by the moderation is never rendered and cannot be shown again by the pro.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.profiles import images
from apps.profiles.models import Profile
from apps.profiles.services import _delete_files_on_commit, _lock_profile, refresh_seo_state

from .models import BlockImage, PageBlock
from .registry import (
    BLOCK_TYPES,
    MAX_BLOCK_IMAGES,
    MAX_BLOCKS,
    STYLE_CHOICES,
    STYLE_DEFAULTS,
    BlockType,
    Field,
    image_slots,
)

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIMEO_ID_RE = re.compile(r"^\d{6,12}$")


# --- text and links -------------------------------------------------------------------------------


def clean_line(value) -> str:
    return " ".join(CONTROL_RE.sub("", str(value or "")).split())


def clean_paragraphs(value) -> str:
    text = CONTROL_RE.sub("", str(value or "").replace("\r\n", "\n").replace("\r", "\n"))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def clean_https_url(value: str) -> str:
    url = (value or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or len(url) > 300 or any(c.isspace() for c in url):
        raise ValidationError(_("Le lien doit commencer par https://"))
    return url


def parse_video(value: str) -> dict:
    """{"url", "provider", "video_id"} for a YouTube or Vimeo link; ValidationError otherwise."""
    url = clean_https_url(value)
    error = ValidationError(_("Colle le lien d'une vidéo YouTube ou Vimeo."))
    if not url:
        raise error
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = [p for p in parts.path.split("/") if p]
    video_id, provider = "", ""
    if host == "youtu.be" and path:
        provider, video_id = "youtube", path[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        provider = "youtube"
        if path[:1] == ["watch"]:
            video_id = (parse_qs(parts.query).get("v") or [""])[0]
        elif len(path) >= 2 and path[0] in ("shorts", "embed", "live"):
            video_id = path[1]
    elif host in ("vimeo.com", "player.vimeo.com"):
        provider = "vimeo"
        video_id = next((p for p in path if p.isdigit()), "")
    if provider == "youtube" and YOUTUBE_ID_RE.match(video_id):
        return {"url": url, "provider": provider, "video_id": video_id}
    if provider == "vimeo" and VIMEO_ID_RE.match(video_id):
        return {"url": url, "provider": provider, "video_id": video_id}
    raise error


def _clean_field(spec: Field, raw) -> str | dict:
    if spec.kind == "textarea":
        value = clean_paragraphs(raw)
    elif spec.kind == "choice":
        value = str(raw or "")
        allowed = [code for code, _label in spec.choices]
        return value if value in allowed else allowed[0]
    elif spec.kind == "url":
        return clean_https_url(raw)
    elif spec.kind == "video":
        return parse_video(raw) if str(raw or "").strip() else ""
    else:
        value = clean_line(raw)
    if len(value) > spec.max_length:
        raise ValidationError(_("%(n)d caractères au plus.") % {"n": spec.max_length})
    return value


# --- validation -----------------------------------------------------------------------------------


def clean_data(block_type: BlockType, post, existing_slots: set[str] | frozenset = frozenset()) -> tuple[dict, dict]:
    """Validate a posted block form. Returns (data, errors); errors maps a form field name to a message.

    Form field names: `f_<field>` for block fields, `i<index>_<field>` for repeated items. An item whose
    fields are all empty (and that holds no image) is dropped.
    """
    data: dict = {}
    errors: dict[str, str] = {}
    for spec in block_type.fields:
        name = f"f_{spec.name}"
        try:
            value = _clean_field(spec, post.get(name, ""))
        except ValidationError as exc:
            errors[name] = exc.messages[0]
            continue
        if spec.required and not value:
            errors[name] = _("Ce champ est obligatoire.")
        data[spec.name] = value
    if block_type.kind == "banner":
        action = data.get("button_action", "whatsapp")
        if action == "link" and not data.get("button_url"):
            errors["f_button_url"] = _("Indique le lien du bouton, ou choisis un autre bouton.")
    if block_type.items:
        items_spec = block_type.items
        items = []
        for index in range(items_spec.max_items):
            row, row_errors = {}, {}
            for spec in items_spec.fields:
                name = f"i{index}_{spec.name}"
                try:
                    row[spec.name] = _clean_field(spec, post.get(name, ""))
                except ValidationError as exc:
                    row_errors[name] = exc.messages[0]
                    row[spec.name] = ""
            has_image = any(f"{slot}_{index}" in existing_slots for slot, _label in items_spec.images)
            if not any(row.values()) and not row_errors and not has_image:
                continue  # empty row
            for spec in items_spec.fields:
                if spec.required and not row.get(spec.name):
                    row_errors.setdefault(f"i{index}_{spec.name}", _("Ce champ est obligatoire."))
            errors.update(row_errors)
            row["_slot"] = index  # images of this row are stored under "<slot>_<index>"
            items.append(row)
        data["items"] = items
    return data, errors


def clean_style(block_type: BlockType, post) -> dict:
    style = {}
    for key, choices in STYLE_CHOICES.items():
        if key == "align" and not block_type.alignable:
            continue
        value = post.get(f"s_{key}", STYLE_DEFAULTS[key])
        style[key] = value if value in [code for code, _label in choices] else STYLE_DEFAULTS[key]
    return style


def is_renderable(block: PageBlock) -> bool:
    """Enough content to show the block on the public page (an empty block is never rendered)."""
    t, data = block.block_type, block.data or {}
    if t is None or block.moderated:
        return False
    if t.items is not None:
        return bool(data.get("items"))
    if t.image_required:
        return bool(data.get("body")) and any(img.slot == "image" for img in block.images.all())
    required = [f.name for f in t.fields if f.required]
    return all(data.get(name) for name in required)


# --- CRUD -------------------------------------------------------------------------------------------


def _check_room(profile: Profile) -> None:
    if PageBlock.objects.filter(profile=profile).count() >= MAX_BLOCKS:
        raise ValidationError(
            _("Ta page a déjà %(n)d blocs : supprime-en un pour en ajouter un autre.") % {"n": MAX_BLOCKS}
        )


@transaction.atomic
def add_block(profile: Profile, kind: str) -> PageBlock:
    """New empty block of `kind`, placed just before the Contact section (live and draft orders)."""
    from apps.themes import services as themes

    block_type = BLOCK_TYPES.get(kind)
    if block_type is None:
        raise ValidationError(_("Type de bloc inconnu."))
    _lock_profile(profile)
    _check_room(profile)
    data = {f.name: (f.choices[0][0] if f.kind == "choice" else "") for f in block_type.fields}
    if block_type.items:
        data["items"] = []
    block = PageBlock.objects.create(profile=profile, kind=kind, data=data, style=dict(STYLE_DEFAULTS))
    themes.insert_block_section(profile, block.key)
    return block


@transaction.atomic
def update_block(block: PageBlock, post, files) -> dict:
    """Save a posted block form (content, style, images). Returns the errors (empty = saved)."""
    if block.moderated:
        raise ValidationError(_("Ce bloc a été masqué par l'équipe Modulis : il ne peut plus être modifié."))
    _lock_profile(block.profile)
    block_type = block.block_type
    allowed_slots = set(image_slots(block_type, block_type.items.max_items if block_type.items else 0))
    existing = {img.slot: img for img in block.images.all()}
    uploads = {
        name[len("img_") :]: f
        for name, f in files.items()
        if name.startswith("img_") and f and name[4:] in allowed_slots
    }
    data, errors = clean_data(block_type, post, frozenset(existing) | frozenset(uploads))
    if errors:
        return errors
    style = clean_style(block_type, post)
    # Item slots follow the row index of the form: rows removed by the pro release their images.
    kept_rows = {row["_slot"] for row in data.get("items", [])}
    for slot, img in list(existing.items()):
        row = _row_of(slot)
        if post.get(f"del_{slot}") or slot not in allowed_slots or (row is not None and row not in kept_rows):
            _remove_image(img)
            existing.pop(slot)
    total = BlockImage.objects.filter(block__profile=block.profile).exclude(block=block).count() + len(existing)
    new_slots = [slot for slot in uploads if slot not in existing]
    if total + len(new_slots) > MAX_BLOCK_IMAGES:
        return {
            "images": _("Ta page a déjà %(n)d images dans ses blocs : retires-en avant d'en ajouter.")
            % {"n": MAX_BLOCK_IMAGES}
        }
    for slot, uploaded in uploads.items():
        try:
            content = images.process_image(uploaded, max_side=images.GALLERY_MAX_SIDE)
        except ValidationError as exc:
            return {f"img_{slot}": exc.messages[0]}
        if slot in existing:
            _remove_image(existing.pop(slot))
        width, height = content.image_size
        img = BlockImage(block=block, slot=slot, width=width, height=height)
        images.store_image(img.image, content)
        img.save()
    block.data, block.style = data, style
    block.save(update_fields=["data", "style", "updated_at"])
    refresh_seo_state(block.profile)
    return {}


def _row_of(slot: str) -> int | None:
    head, _sep, tail = slot.rpartition("_")
    return int(tail) if head and tail.isdigit() else None


def _remove_image(img: BlockImage) -> None:
    name, storage = img.image.name, img.image.storage
    img.delete()
    _delete_files_on_commit(storage, name)


@transaction.atomic
def delete_block(block: PageBlock) -> None:
    from apps.themes import services as themes

    profile = block.profile
    _lock_profile(profile)
    for img in list(block.images.all()):
        _remove_image(img)
    key = block.key
    block.delete()
    themes.remove_block_section(profile, key)
    refresh_seo_state(profile)


def delete_all_for_profile(profile: Profile) -> None:
    """Right to erasure (profiles.services.delete_profile): blocks and their image files."""
    for img in BlockImage.objects.filter(block__profile=profile):
        _remove_image(img)
    PageBlock.objects.filter(profile=profile).delete()


@transaction.atomic
def moderate(block: PageBlock, *, hidden: bool, note: str = "", actor=None) -> None:
    from apps.platform.services import audit

    PageBlock.objects.filter(pk=block.pk).update(moderated=hidden, moderation_note=note[:200] if hidden else "")
    audit(actor, "block.moderate" if hidden else "block.unmoderate", f"profile:{block.profile_id}", block=block.pk)
