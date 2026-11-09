"""Every first-level URL segment must be a reserved slug, otherwise a profile could shadow a route."""

import re

import pytest
from django.conf import settings
from django.urls import get_resolver

from apps.profiles.services import SYSTEM_RESERVED_SLUGS


def _first_segments():
    segments = set()
    for pattern in get_resolver().url_patterns:
        route = str(pattern.pattern)
        nested = getattr(pattern, "url_patterns", None)
        routes = [route + str(p.pattern) for p in nested] if nested else [route]
        for full in routes:
            first = full.lstrip("^").split("/")[0]
            if first and "<" not in first and not first.startswith("("):
                segments.add(re.sub(r"[.$\\].*", "", first))
    return segments


def test_all_static_root_segments_are_reserved():
    missing = {s for s in _first_segments() if s} - SYSTEM_RESERVED_SLUGS
    assert not missing, f"Add these to SYSTEM_RESERVED_SLUGS: {sorted(missing)}"


def test_admin_url_is_reserved():
    assert settings.ADMIN_URL.strip("/") in SYSTEM_RESERVED_SLUGS


@pytest.mark.django_db
def test_seed_data_loaded():
    from apps.core.models import City, Trade

    assert City.objects.filter(slug="douala").exists()
    assert Trade.objects.filter(slug="plombier", schema_type="Plumber").exists()
