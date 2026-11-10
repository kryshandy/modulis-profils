"""{% load public_images %} — responsive <img> attributes for public templates."""

from django import template

from apps.public import responsive

register = template.Library()


@register.simple_tag
def thumb_attrs(fieldfile):
    """56 px profile-card thumbnail: at most the 160 px variant, width/height always set."""
    image = responsive.responsive_image(
        fieldfile, display_width=responsive.THUMB_SIZE, max_width=responsive.THUMB_MAX_VARIANT
    )
    return responsive.img_attrs(image)


@register.simple_tag
def img_attrs(image):
    """Attributes for a dict built by apps.public.responsive.responsive_image()."""
    return responsive.img_attrs(image)


@register.simple_tag
def preload_attrs(image):
    return responsive.preload_attrs(image)
