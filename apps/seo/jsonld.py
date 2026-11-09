"""Structured data (plan §6.3). Built from user input, so the output is ALWAYS escaped (CLAUDE.md).

`<`, `>` and `&` become `\\u003c`, `\\u003e`, `\\u0026`: still valid JSON, and a bio containing
`</script>` can never close the surrounding <script type="application/ld+json"> element.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from django.conf import settings
from django.utils.safestring import SafeString, mark_safe

from .meta import absolute_url, clean_text

SCHEMA_CONTEXT = "https://schema.org"
_SCHEMA_TYPE_RE = re.compile(r"^[A-Z][A-Za-z]{1,59}$")
_JSON_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", " ": "\\u2028", " ": "\\u2029"}
_JSON_ESCAPE_RE = re.compile("[<>&  ]")


def dumps(data) -> SafeString:
    """Serialize for embedding inside <script type="application/ld+json">."""
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return mark_safe(_JSON_ESCAPE_RE.sub(lambda m: _JSON_ESCAPES[m.group(0)], raw))  # noqa: S308 - escaped above


def schema_type_for(profile) -> str:
    """Person for liberal professions, else the LocalBusiness subtype carried by the trade."""
    trade = profile.trade
    if trade is None:
        return "Person" if profile.kind == "person" else "LocalBusiness"
    schema_type = (trade.schema_type or "").strip()
    if not _SCHEMA_TYPE_RE.match(schema_type):
        return "LocalBusiness"
    return schema_type


def _drop_empty(data: dict) -> dict:
    return {k: v for k, v in data.items() if v not in (None, "", [], {})}


def http_links(urls: Iterable[str]) -> list[str]:
    return [u for u in urls if u and u.lower().startswith(("https://", "http://"))]


def profile_entity(profile, *, image_url: str = "") -> dict:
    """The Person / LocalBusiness node of a profile page."""
    schema_type = schema_type_for(profile)
    is_person = schema_type == "Person"
    url = absolute_url(profile.get_absolute_url())
    city = profile.city
    address = None
    if city:
        address = _drop_empty(
            {
                "@type": "PostalAddress",
                "streetAddress": clean_text(profile.address),
                "addressLocality": city.name,
                "addressRegion": city.region,
                "addressCountry": city.country_id,
            }
        )
    offers = [
        _drop_empty(
            {
                "@type": "Offer",
                "description": clean_text(service.price_label),
                "itemOffered": _drop_empty(
                    {
                        "@type": "Service",
                        "name": clean_text(service.title),
                        "description": clean_text(service.description),
                    }
                ),
            }
        )
        for service in profile.services.all()
    ]
    data = {
        "@context": SCHEMA_CONTEXT,
        "@type": schema_type,
        "@id": f"{url}#{'person' if is_person else 'business'}",
        "name": clean_text(profile.display_name),
        "url": url,
        "image": absolute_url(image_url) if image_url else "",
        "description": clean_text(profile.bio)[:500],
        "telephone": profile.phone_public or profile.whatsapp,
        "email": profile.email_public,
        "address": address,
        "sameAs": http_links(link.url for link in profile.links.all()),
        "makesOffer": offers,
    }
    if is_person:
        data["jobTitle"] = clean_text(profile.title)
    else:
        area = clean_text(profile.service_area)
        data["areaServed"] = area or (city.name if city else "")
        if profile.maps_url and profile.maps_url.startswith("https://"):
            data["hasMap"] = profile.maps_url
    return _drop_empty(data)


def breadcrumb(items: Iterable[tuple[str, str]]) -> dict:
    """BreadcrumbList from (name, path) pairs; the last item may have an empty path (current page)."""
    elements = []
    for position, (name, path) in enumerate(items, start=1):
        element = {"@type": "ListItem", "position": position, "name": clean_text(name)}
        if path:
            element["item"] = absolute_url(path)
        elements.append(element)
    return {"@context": SCHEMA_CONTEXT, "@type": "BreadcrumbList", "itemListElement": elements}


def website() -> dict:
    return {"@context": SCHEMA_CONTEXT, "@type": "WebSite", "name": settings.SITE_NAME, "url": absolute_url("/")}
