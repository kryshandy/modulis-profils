"""Public rendering of page blocks: template data and structured data (ADR-0012)."""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.public import responsive

from .models import PageBlock
from .services import is_renderable

# Display widths (themes/base.css: --wrap 84rem) used for the `sizes` attribute of block images.
IMAGE_SIZES = {
    "text_image": (560, "(min-width: 64rem) 38rem, 100vw"),
    "before_after": (480, "(min-width: 64rem) 20rem, 50vw"),
}
VIDEO_EMBEDS = {
    "youtube": "https://www.youtube-nocookie.com/embed/{id}?autoplay=1&rel=0",
    "vimeo": "https://player.vimeo.com/video/{id}?autoplay=1&dnt=1",
}
VIDEO_CSP = {"frame-src": ["https://www.youtube-nocookie.com", "https://player.vimeo.com"]}


def _image(img, kind: str) -> dict:
    display, sizes = IMAGE_SIZES.get(kind, (480, "(min-width: 64rem) 30rem, 100vw"))
    return responsive.responsive_image(
        img.image,
        display_width=display,
        width=img.width or 1200,
        height=img.height or 800,
        sizes=sizes,
        original_width=img.width or None,
    )


def block_payload(block: PageBlock) -> dict | None:
    if not is_renderable(block):
        return None
    data = dict(block.data or {})
    imgs = {img.slot: _image(img, block.kind) for img in block.images.all()}
    style = block.style or {}
    items = []
    for row in data.get("items", []):
        slot = row.get("_slot", 0)
        item = {k: v for k, v in row.items() if not k.startswith("_")}
        item["images"] = {s: imgs[f"{s}_{slot}"] for s in ("before", "after") if f"{s}_{slot}" in imgs}
        if block.kind == "before_after" and len(item["images"]) < 2:
            continue  # a pair needs both photos
        items.append(item)
    if block.block_type.items is not None and not items:
        return None
    payload = {
        "id": block.pk,
        "key": block.key,
        "kind": block.kind,
        "kind_label": str(block.block_type.label),
        "anchor": block.anchor,
        "template": f"blocks/public/_{block.kind}.html",
        "title": data.get("title", ""),
        "data": data,
        "items": items,
        "image": imgs.get("image"),
        "classes": " ".join(
            [
                f"t-block--{block.kind}",
                f"t-block--bg-{style.get('background', 'auto')}",
                f"t-block--sp-{style.get('spacing', 'normal')}",
                f"t-block--al-{style.get('align', 'start')}",
            ]
        ),
    }
    if block.kind == "video" and isinstance(data.get("url"), dict):
        video = data["url"]
        payload["video"] = {
            "provider": video["provider"],
            "watch_url": video["url"],
            "embed_url": VIDEO_EMBEDS[video["provider"]].format(id=video["video_id"]),
            "label": "YouTube" if video["provider"] == "youtube" else "Vimeo",
        }
    return payload


def render_map(profile) -> dict[str, dict]:
    """{"b<id>": payload} of the page's blocks that have enough content to be shown."""
    blocks = PageBlock.objects.filter(profile=profile, moderated=False).prefetch_related("images")
    result = {}
    for block in blocks:
        payload = block_payload(block)
        if payload is not None:
            result[block.key] = payload
    return result


def faq_node(payloads, page_url: str) -> dict | None:
    """FAQPage JSON-LD from the visible FAQ blocks (questions and answers exactly as displayed)."""
    entities = [
        {
            "@type": "Question",
            "name": item["q"],
            "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
        }
        for p in payloads
        if p["kind"] == "faq"
        for item in p["items"]
    ]
    if not entities:
        return None
    return {"@type": "FAQPage", "@id": f"{page_url}#faq", "name": _("Questions fréquentes"), "mainEntity": entities}
