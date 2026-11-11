"""Customizer form parsing. Validation of the values themselves is done by services.clean_draft()."""

from __future__ import annotations

from . import services
from .models import Theme


def palette_from_post(post, theme: Theme, current: dict) -> dict:
    """A chosen preset wins; "custom" (or no preset) takes the five colour inputs."""
    preset = post.get("preset", "custom")
    presets = theme.palette_presets or []
    if preset.isdigit() and int(preset) < len(presets):
        return services.clean_palette(presets[int(preset)], base=services.clean_palette(theme.palette))
    palette = {}
    for key in services.PALETTE_KEYS:
        value = (post.get(f"color_{key}") or "").strip()
        palette[key] = value.upper() if services.is_hex(value) else value  # invalid → refused by clean_draft
    if not any(palette.values()):
        return dict(current)
    return palette


def sections_from_post(post) -> list[dict]:
    order = [key for key in post.getlist("order") if key in services.SECTION_KEYS]
    order = list(dict.fromkeys(order)) or list(services.SECTION_KEYS)
    sections = [{"key": key, "visible": post.get(f"visible_{key}") == "on"} for key in order]
    move = post.get("move", "")
    key, _, direction = move.partition(":")
    keys = [s["key"] for s in sections]
    if key in keys and direction in ("up", "down"):
        i = keys.index(key)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(sections):
            sections[i], sections[j] = sections[j], sections[i]
    return services.normalize_sections(sections)


def draft_from_post(post, theme: Theme, current: dict) -> dict:
    return {
        "palette": palette_from_post(post, theme, current.get("palette") or {}),
        "font_pair": post.get("font_pair") or current.get("font_pair"),
        "corners": post.get("corners") or current.get("corners"),
        "hero_variant": post.get("hero_variant") or current.get("hero_variant"),
        "cta_label": post.get("cta_label", current.get("cta_label", "")),
        "sections": sections_from_post(post),
    }


def preset_index(theme: Theme, palette: dict) -> str:
    """Index of the preset equal to `palette`, else "custom"."""
    for index, preset in enumerate(theme.palette_presets or []):
        if services.clean_palette(preset) == services.clean_palette(palette):
            return str(index)
    return "custom"
