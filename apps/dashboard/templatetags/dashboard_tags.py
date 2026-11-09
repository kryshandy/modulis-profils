"""Template helpers for the Espace pro."""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

from apps.accounts.services import display_phone

register = template.Library()


@register.simple_tag
def icon(name: str, css: str = "") -> str:
    """Inline reference to the SVG sprite (static/img/icons.svg): no request per icon."""
    return format_html(
        '<svg class="icon {}" aria-hidden="true" focusable="false"><use href="{}#{}"></use></svg>',
        css,
        static("img/icons.svg"),
        name,
    )


@register.filter
def phone(value: str) -> str:
    return display_phone(value) if value else ""


@register.filter
def without_scheme(url: str) -> str:
    return (url or "").split("://", 1)[-1]
