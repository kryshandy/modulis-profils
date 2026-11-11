"""Brand helpers for the Espace pro shell (Modulis identity)."""

import logging

from django import template
from django.db import DatabaseError

register = template.Library()
logger = logging.getLogger(__name__)


@register.simple_tag
def platform_announcement() -> str:
    """Banner text set in the control center (SiteSettings.announcement), "" when empty or unavailable.

    Read through apps.platform.services only (one app never reads another's models). The settings are cached
    by the platform app (no query on most requests, so no savepoint here: it would cost two queries per page).
    """
    from apps.platform.services import get_settings

    try:
        text = get_settings().announcement or ""
    except DatabaseError:
        logger.warning("platform announcement unavailable", exc_info=True)
        return ""
    return text.strip()
