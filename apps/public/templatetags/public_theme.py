"""{% load public_theme %} — helpers of the themed profile pages."""

from django import template

register = template.Library()


@register.filter
def pretty_phone(value: str) -> str:
    """+237 6 90 00 00 11 style display of an E.164 number (falls back to the raw value)."""
    if not value:
        return ""
    try:
        from apps.accounts.services import display_phone
    except ImportError:  # pragma: no cover - accounts is always installed
        return value
    try:
        return display_phone(value) or value
    except (ValueError, TypeError):
        return value


@register.simple_tag
def section_template(key: str) -> str:
    if key.startswith("b") and key[1:].isdigit():  # page builder block (apps.blocks)
        return "public/themes/sections/_block.html"
    return f"public/themes/sections/_{key}.html"
