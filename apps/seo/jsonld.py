"""Structured data (plan §6.3). Built from user input, so the output is ALWAYS escaped (CLAUDE.md).

`<`, `>` and `&` become `\\u003c`, `\\u003e`, `\\u0026`: still valid JSON, and a bio containing
`</script>` can never close the surrounding <script type="application/ld+json"> element.

Every public page carries ONE block: {"@context": …, "@graph": [WebSite, Organization, WebPage,
entity?, BreadcrumbList?]}, the nodes being linked with "@id" references (SEO audit 2026-11-10 #5).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import SafeString, mark_safe

from .meta import absolute_url, clean_text

SCHEMA_CONTEXT = "https://schema.org"
PUBLISHER_NAME = "Modulis Tech"
LOGO_STATIC = "img/logo.png"
LOGO_SIZE = 512
DEFAULT_CURRENCY = "XAF"
_SCHEMA_TYPE_RE = re.compile(r"^[A-Z][A-Za-z]{1,59}$")
_JSON_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", " ": "\\u2028", " ": "\\u2029"}
_JSON_ESCAPE_RE = re.compile("[<>&  ]")

# "5 000", "5.000", "5000", "5 000" (no-break spaces): a thousands separator is followed by 3 digits.
_NUMBER_RE = re.compile(r"\d{1,3}(?:[   .,]\d{3})+(?!\d)|\d+")
_FROM_RE = re.compile(r"\b(?:dès|des|à partir|a partir|from|starting)\b", re.IGNORECASE)
MIN_PRICE = 100  # below this, a number in a label is a duration or a quantity ("24h/24", "2 pièces")
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$|^24:00$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
DAYS = {
    "mo": "Monday",
    "tu": "Tuesday",
    "we": "Wednesday",
    "th": "Thursday",
    "fr": "Friday",
    "sa": "Saturday",
    "su": "Sunday",
}


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


# --- ids ---------------------------------------------------------------------------------------


def site_id(fragment: str) -> str:
    return f"{absolute_url('/')}#{fragment}"


def ref(node_id: str) -> dict:
    return {"@id": node_id}


def entity_id(profile) -> str:
    suffix = "person" if schema_type_for(profile) == "Person" else "business"
    return f"{absolute_url(profile.get_absolute_url())}#{suffix}"


# --- value parsers -----------------------------------------------------------------------------


def parse_price(label: str) -> dict:
    """« dès 5 000 FCFA » -> {"minPrice": 5000}; « 5 000 – 10 000 » -> min/max; « 7 500 F » -> price."""
    text = clean_text(label)
    numbers = [int(re.sub(r"\D", "", raw)) for raw in _NUMBER_RE.findall(text)]
    numbers = [n for n in numbers if n >= MIN_PRICE]
    if not numbers:
        return {}
    if len(numbers) >= 2 and numbers[1] > numbers[0]:
        return {"minPrice": numbers[0], "maxPrice": numbers[1]}
    if _FROM_RE.search(text):
        return {"minPrice": numbers[0]}
    return {"price": numbers[0]}


def currency_for(profile) -> str:
    country = getattr(getattr(profile, "city", None), "country", None)
    currency = (getattr(country, "currency", "") or "").upper()
    return currency if _CURRENCY_RE.match(currency) else DEFAULT_CURRENCY


def price_specification(label: str, currency: str) -> dict | None:
    amounts = parse_price(label)
    if not amounts:
        return None
    return {"@type": "PriceSpecification", "priceCurrency": currency, **amounts}


def geo_coordinates(profile) -> dict | None:
    lat, lng = getattr(profile, "latitude", None), getattr(profile, "longitude", None)
    if lat is None or lng is None:
        return None
    try:
        lat, lng = float(Decimal(str(lat))), float(Decimal(str(lng)))
    except (InvalidOperation, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return {"@type": "GeoCoordinates", "latitude": round(lat, 6), "longitude": round(lng, 6)}


def opening_hours_specification(hours) -> list[dict]:
    """{"mo": [["08:00", "18:00"]], …, "su": []} -> OpeningHoursSpecification, identical slots grouped."""
    if not isinstance(hours, dict):
        return []
    groups: dict[tuple[str, str], list[str]] = {}
    for code, day in DAYS.items():
        intervals = hours.get(code) or []
        if not isinstance(intervals, (list, tuple)):
            continue
        for interval in intervals:
            if not (isinstance(interval, (list, tuple)) and len(interval) == 2):
                continue
            opens, closes = (str(v) for v in interval)
            if _TIME_RE.match(opens) and _TIME_RE.match(closes) and opens != closes:
                groups.setdefault((opens, closes), []).append(f"{SCHEMA_CONTEXT}/{day}")
    return [
        {"@type": "OpeningHoursSpecification", "dayOfWeek": days, "opens": opens, "closes": closes}
        for (opens, closes), days in groups.items()
    ]


# --- nodes -------------------------------------------------------------------------------------


def profile_entity(profile, *, image_url: str = "") -> dict:
    """The Person / LocalBusiness node of a profile page. `image_url`: the real photo only, never og.png."""
    schema_type = schema_type_for(profile)
    is_person = schema_type == "Person"
    url = absolute_url(profile.get_absolute_url())
    city = profile.city
    address = None
    street = clean_text(profile.address)
    if city or street:
        address = _drop_empty(
            {
                "@type": "PostalAddress",
                "streetAddress": street,
                "addressLocality": city.name if city else "",
                "addressRegion": city.region if city else "",
                "addressCountry": city.country_id if city else "",
            }
        )
    currency = currency_for(profile)
    offers = [
        _drop_empty(
            {
                "@type": "Offer",
                "description": clean_text(service.price_label),
                "priceSpecification": price_specification(service.price_label, currency),
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
        "@type": schema_type,
        "@id": entity_id(profile),
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
        data["geo"] = geo_coordinates(profile)
        data["openingHoursSpecification"] = opening_hours_specification(getattr(profile, "opening_hours", None))
        data["priceRange"] = clean_text(getattr(profile, "price_range", "") or "")[:100]
    return _drop_empty(data)


def breadcrumb(items: Iterable[tuple[str, str]], *, node_id: str = "") -> dict:
    """BreadcrumbList from (name, path) pairs; the last item may have an empty path (current page)."""
    elements = []
    for position, (name, path) in enumerate(items, start=1):
        element = {"@type": "ListItem", "position": position, "name": clean_text(name)}
        if path:
            element["item"] = absolute_url(path)
        elements.append(element)
    return _drop_empty({"@type": "BreadcrumbList", "@id": node_id, "itemListElement": elements})


def logo_url() -> str:
    return absolute_url(static(LOGO_STATIC))


def organization() -> dict:
    return {
        "@type": "Organization",
        "@id": site_id("organization"),
        "name": PUBLISHER_NAME,
        "url": absolute_url("/"),
        "logo": {"@type": "ImageObject", "url": logo_url(), "width": LOGO_SIZE, "height": LOGO_SIZE},
    }


def website(lang: str = "fr") -> dict:
    return {
        "@type": "WebSite",
        "@id": site_id("website"),
        "name": settings.SITE_NAME,
        "url": absolute_url("/"),
        "inLanguage": lang,
        "publisher": ref(site_id("organization")),
    }


def item_list(profiles: Iterable, *, node_id: str) -> dict:
    elements = [
        {
            "@type": "ListItem",
            "position": position,
            "url": absolute_url(p.get_absolute_url()),
            "name": clean_text(p.display_name),
        }
        for position, p in enumerate(profiles, start=1)
    ]
    return {"@type": "ItemList", "@id": node_id, "numberOfItems": len(elements), "itemListElement": elements}


def page_graph(
    *,
    path: str,
    name: str,
    lang: str = "fr",
    page_type: str = "WebPage",
    entity: dict | None = None,
    crumbs: Iterable[tuple[str, str]] | None = None,
) -> dict:
    """The single @graph of a public page: WebSite, Organization, WebPage, entity?, BreadcrumbList?."""
    url = absolute_url(path)
    page = {
        "@type": page_type,
        "@id": f"{url}#webpage",
        "url": url,
        "name": clean_text(name),
        "inLanguage": lang,
        "isPartOf": ref(site_id("website")),
    }
    nodes = [website(), organization(), page]
    if entity:
        page["mainEntity"] = ref(entity["@id"])
        nodes.append(entity)
    crumbs = list(crumbs or [])
    if len(crumbs) > 1:
        crumb_node = breadcrumb(crumbs, node_id=f"{url}#breadcrumb")
        page["breadcrumb"] = ref(crumb_node["@id"])
        nodes.append(crumb_node)
    return {"@context": SCHEMA_CONTEXT, "@graph": nodes}


# --- validation (tests, seo_audit --crawl) -----------------------------------------------------


def _walk_refs(value, found: list[str], *, top: bool = False) -> None:
    if isinstance(value, dict):
        if not top and set(value) == {"@id"}:
            found.append(value["@id"])
            return
        for child in value.values():
            _walk_refs(child, found)
    elif isinstance(value, list):
        for child in value:
            _walk_refs(child, found)


def unresolved_refs(block: dict) -> list[str]:
    """ "@id" references of a JSON-LD block that point to no node of that block."""
    nodes = block.get("@graph", [block]) if isinstance(block, dict) else []
    defined = {node.get("@id") for node in nodes if isinstance(node, dict) and node.get("@id")}
    refs: list[str] = []
    for node in nodes:
        _walk_refs(node, refs, top=True)
    return [r for r in refs if r not in defined]
