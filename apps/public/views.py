"""Public, server-rendered pages (plan §4, §6): home, cities, directory, profile and its resources."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse
from django.utils import timezone, translation
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_safe

from apps.profiles.models import Profile, SlugRegistry
from apps.profiles.services import OPENING_DAYS, resolve_slug
from apps.seo import jsonld, selectors
from apps.seo.meta import (
    absolute_url,
    clean_text,
    job_at_city,
    page_meta,
    profile_alt,
    profile_meta,
    truncate,
)
from apps.themes import services as themes

from . import images, responsive
from .http import (
    language_independent,
    mark_language_independent,
    set_error_cache,
    set_private_no_store,
    set_public_cache,
)
from .vcard import build_vcard

logger = logging.getLogger(__name__)

DIRECTORY_PAGE_SIZE = 24
NOINDEX = "noindex"
CONTACT_REL = "nofollow noopener"  # WhatsApp / maps / share: outbound, not UGC, passes no equity
USER_LINK_REL = "ugc nofollow noopener"  # links typed by the pro
VCARD_MAX_AGE = 300
THEME_CSS_MAX_AGE = 365 * 86400  # versioned URL (?v=<hash>): immutable
THEME_CSS_UNVERSIONED_MAX_AGE = 300
DAY_LABELS = {
    "mo": gettext_lazy("Lundi"),
    "tu": gettext_lazy("Mardi"),
    "we": gettext_lazy("Mercredi"),
    "th": gettext_lazy("Jeudi"),
    "fr": gettext_lazy("Vendredi"),
    "sa": gettext_lazy("Samedi"),
    "su": gettext_lazy("Dimanche"),
}
_DIGITS_RE = re.compile(r"\D+")
_SENTENCE_END_RE = re.compile(r"[.!?…](?=\s+[A-ZÀ-ÖØ-Þ0-9«“\"])")
PAGE_TZ = ZoneInfo("Africa/Douala")  # opening hours are local to the pros (Cameroon, UTC+1, no DST)


# --- helpers ---------------------------------------------------------------------------------


def signup_url() -> str:
    try:
        return reverse("dashboard:login")
    except NoReverseMatch:  # dashboard routes not wired yet
        return "/espace/"


def report_url(slug: str) -> str:
    return f"/signaler/{slug}"  # moderation:report, plain path to avoid an import-time dependency


def city_path(city) -> str:
    return reverse("public:city", kwargs={"city": city.slug})


def directory_path(trade, city) -> str:
    return reverse("public:directory", kwargs={"trade_plural": trade.plural_slug, "city": city.slug})


def directory_enabled() -> bool:
    """Platform switch for /villes/<city> and /<trades>/<city> (control center)."""
    from apps.platform.services import feature

    try:
        with transaction.atomic():
            return feature("directory")
    except (DatabaseError, KeyError):  # platform tables unavailable: keep the directory on
        return True


def gone(request) -> HttpResponse:
    with translation.override(settings.LANGUAGE_CODE):
        response = render(request, "410.html", status=410)
    response["X-Robots-Tag"] = NOINDEX
    mark_language_independent(response)
    return set_error_cache(response)


def _set_public_cache(request, response, *, private: bool = False) -> HttpResponse:
    if private:
        return set_private_no_store(response)
    return set_public_cache(response)


def _is_owner(request, profile: Profile) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and profile.user_id == user.pk)


def _lookup(request, slug: str):
    """Resolve a first-level segment for the profile page and its resources.

    Returns (profile, outcome) with outcome in {"ok", "owner_private", "old", "gone"};
    raises Http404 for anything that must not be served (suspended, private, reserved, unknown).
    """
    kind, profile = resolve_slug(slug)
    if kind == SlugRegistry.Kind.ERASED:
        return None, "gone"
    if profile is None or kind not in (SlugRegistry.Kind.CURRENT, SlugRegistry.Kind.OLD):
        raise Http404
    if profile.status == Profile.Status.DELETED:
        return None, "gone"
    if profile.status != Profile.Status.ACTIVE:
        raise Http404  # suspended: never serve any content, not even to the owner
    if profile.is_publicly_visible:
        outcome = "ok"
    elif _is_owner(request, profile):
        outcome = "owner_private"
    else:
        raise Http404
    if kind == SlugRegistry.Kind.OLD:
        return profile, "old"
    return profile, outcome


def _noindex(response: HttpResponse) -> HttpResponse:
    response["X-Robots-Tag"] = NOINDEX
    return response


def _profile_resource(request, slug: str, suffix: str):
    """Common gate for /<slug>/<resource>; returns (profile, None) or (None, response)."""
    profile, outcome = _lookup(request, slug)
    if outcome == "gone":
        return None, gone(request)
    if outcome == "old" or slug != slug.lower():
        return None, HttpResponsePermanentRedirect(f"/{profile.slug}/{suffix}")
    return profile, None


def _digits(phone: str) -> str:
    return _DIGITS_RE.sub("", phone or "")


def _http_url(url: str) -> str:
    return url if url and url.lower().startswith(("https://", "http://")) else ""


def _maps_url(profile: Profile) -> str:
    if _http_url(profile.maps_url):
        return profile.maps_url
    parts = [p for p in (profile.address, profile.district, profile.city.name if profile.city else "") if p]
    if not parts or not (profile.address or profile.district):
        return ""
    return "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": ", ".join(parts)})


def _hide_branding(profile: Profile) -> bool:
    """Paid entitlement lookup. Under ATOMIC_REQUESTS a failed query must not poison the request
    transaction: it runs in a savepoint, and only the expected failures are swallowed."""
    try:
        from apps.billing.services import has
    except ImportError:  # billing not installed: keep the growth banner
        return False
    try:
        with transaction.atomic():
            return bool(has(profile, "hide_branding"))
    except (DatabaseError, LookupError) as exc:  # billing tables or plan data unavailable
        logger.warning("hide_branding lookup failed for profile %s: %s", profile.pk, exc.__class__.__name__)
        return False


def _crumbs_for_jsonld(crumbs: list[tuple[str, str]], current_path: str) -> list[tuple[str, str]]:
    """BreadcrumbList: the linked levels only (pages meeting the threshold), then the current page."""
    *parents, (name, _path) = crumbs
    return [(n, p) for n, p in parents if p] + [(name, current_path)]


def _city_crumb(city, minimum: int, *, enabled: bool = True) -> tuple[str, str]:
    """The city level is linked only when /villes/<city> is indexable (like the home `linked`)."""
    return (city.name, city_path(city) if enabled and selectors.city_count(city) >= minimum else "")


# --- home, cities, directory -----------------------------------------------------------------


@require_safe
@language_independent
def home(request):
    minimum = selectors.directory_min()
    listed = directory_enabled()  # off: no city / directory links at all (those pages answer 404)
    cities = selectors.city_stats() if listed else []
    combos = selectors.directory_combos() if listed else []
    meta = page_meta(
        title=_("Crée ta page pro gratuite – %(site)s") % {"site": settings.SITE_NAME},
        description=_(
            "Artisans, commerçants, freelances : crée gratuitement ta page professionnelle, "
            "partage-la sur WhatsApp et sois trouvé sur Google par tes clients, dans ta ville."
        ),
        path="/",
        indexable=True,
    )
    context = {
        "meta": meta,
        "jsonld": jsonld.dumps(jsonld.page_graph(path="/", name=meta["title"])),
        "signup_url": signup_url(),
        "cities": [{**c, "linked": c["count"] >= minimum, "url": city_path(c["city"])} for c in cities],
        "combos": [
            {**c, "linked": c["count"] >= minimum, "url": directory_path(c["trade"], c["city"])} for c in combos
        ],
        "recent": list(selectors.indexable_profiles().order_by("-content_updated_at", "-pk")[:12]),
    }
    return _set_public_cache(request, render(request, "public/home.html", context))


def _page_number(request) -> int:
    raw = request.GET.get("page", "1")
    if not raw.isdigit() or int(raw) < 1:
        raise Http404
    return int(raw)


def _paginate(queryset, request):
    """A listing with no indexable profile is a soft 404: answer a real 404 (SEO audit 2026-11-10 #3)."""
    number = _page_number(request)
    paginator = Paginator(queryset, DIRECTORY_PAGE_SIZE, allow_empty_first_page=False)
    try:
        return paginator.page(number)
    except (EmptyPage, PageNotAnInteger):
        raise Http404 from None


def _paged_path(path: str, page) -> str:
    return path if page.number == 1 else f"{path}?page={page.number}"


def _listing_jsonld(path: str, name: str, page, crumbs) -> str:
    url = absolute_url(path)
    entity = jsonld.item_list(page.object_list, node_id=f"{url}#list")
    graph = jsonld.page_graph(
        path=path,
        name=name,
        page_type="CollectionPage",
        entity=entity,
        crumbs=_crumbs_for_jsonld(crumbs, path),
    )
    return jsonld.dumps(graph)


@require_safe
@language_independent
def city(request, city):
    if not directory_enabled():
        raise Http404
    city_obj = selectors.find_city(city)
    if city_obj is None:
        raise Http404
    if city != city_obj.slug:
        return HttpResponsePermanentRedirect(city_path(city_obj))
    minimum = selectors.directory_min()
    page = _paginate(selectors.city_profiles(city_obj), request)
    indexable = page.paginator.count >= minimum
    path = city_path(city_obj)
    title = _("Professionnels à %(city)s") % {"city": city_obj.name}
    if page.number > 1:
        title = _("%(title)s – page %(n)d") % {"title": title, "n": page.number}
    meta = page_meta(
        title=truncate(f"{title} – {settings.SITE_NAME}", 60),
        description=truncate(
            _(
                "Trouve un professionnel à %(city)s : artisans, commerçants et freelances, avec leurs "
                "services, leurs réalisations et un contact direct par WhatsApp ou par téléphone."
            )
            % {"city": city_obj.name},
            160,
        ),
        path=_paged_path(path, page),
        indexable=indexable,
    )
    breadcrumb = [(_("Accueil"), "/"), (city_obj.name, "")]
    context = {
        "meta": meta,
        "city": city_obj,
        "page": page,
        "trades": [
            {**c, "linked": c["count"] >= minimum, "url": directory_path(c["trade"], c["city"])}
            for c in selectors.trades_in_city(city_obj)
        ],
        "breadcrumb": breadcrumb,
        "jsonld": _listing_jsonld(_paged_path(path, page), title, page, breadcrumb),
    }
    return _set_public_cache(request, render(request, "public/city.html", context))


@require_safe
@language_independent
def directory(request, trade_plural, city):
    if not directory_enabled():
        raise Http404
    trade = selectors.find_trade_by_plural(trade_plural)
    city_obj = selectors.find_city(city) if trade else None
    if trade is None or city_obj is None:
        raise Http404
    path = directory_path(trade, city_obj)
    if request.path != path:
        return HttpResponsePermanentRedirect(path + (f"?{request.GET.urlencode()}" if request.GET else ""))
    minimum = selectors.directory_min()
    page = _paginate(selectors.directory_profiles(trade, city_obj), request)
    indexable = page.paginator.count >= minimum
    heading = _("%(plural)s à %(city)s") % {"plural": trade.plural_name, "city": city_obj.name}
    title = heading if page.number == 1 else _("%(title)s – page %(n)d") % {"title": heading, "n": page.number}
    meta = page_meta(
        title=truncate(f"{title} – {settings.SITE_NAME}", 60),
        description=truncate(
            _(
                "%(plural)s à %(city)s : compare les profils, les prestations et les réalisations, puis "
                "contacte directement le professionnel de ton choix par WhatsApp ou par téléphone."
            )
            % {"plural": trade.plural_name, "city": city_obj.name},
            160,
        ),
        path=_paged_path(path, page),
        indexable=indexable,
    )
    city_crumb = _city_crumb(city_obj, minimum)
    breadcrumb = [(_("Accueil"), "/"), city_crumb, (heading, "")]
    context = {
        "meta": meta,
        "heading": heading,
        "trade": trade,
        "city": city_obj,
        "city_url": city_crumb[1],
        "page": page,
        "breadcrumb": breadcrumb,
        "jsonld": _listing_jsonld(_paged_path(path, page), title, page, breadcrumb),
    }
    return _set_public_cache(request, render(request, "public/directory.html", context))


def _query_suffix(request) -> str:
    return f"?{request.GET.urlencode()}" if request.GET else ""


@require_safe
def city_trailing_slash(request, city):
    city_obj = selectors.find_city(city)
    if city_obj is None:
        raise Http404
    return HttpResponsePermanentRedirect(city_path(city_obj) + _query_suffix(request))


@require_safe
def directory_trailing_slash(request, trade_plural, city):
    trade = selectors.find_trade_by_plural(trade_plural)
    city_obj = selectors.find_city(city) if trade else None
    if trade is None or city_obj is None:
        raise Http404
    return HttpResponsePermanentRedirect(directory_path(trade, city_obj) + _query_suffix(request))


# --- profile page ----------------------------------------------------------------------------


def _profile_breadcrumb(profile: Profile, name: str) -> list[tuple[str, str]]:
    """Accueil > Ville > Métiers à Ville > Nom; a level is linked only if that page is indexable."""
    city = profile.city
    crumbs = [(_("Accueil"), "/")]
    if city:
        minimum = selectors.directory_min()
        enabled = directory_enabled()
        crumbs.append(_city_crumb(city, minimum, enabled=enabled))
        if profile.trade:
            linked = enabled and selectors.directory_count(profile.trade, city) >= minimum
            crumbs.append(
                (
                    _("%(plural)s à %(city)s") % {"plural": profile.trade.plural_name, "city": city.name},
                    directory_path(profile.trade, city) if linked else "",
                )
            )
    crumbs.append((name, ""))
    return crumbs


# Cover image (a gallery photo chosen by the pro): where it goes and how wide it is displayed.
COVER_REPLACES_PHOTO = ("magazine", "split_photo")
COVER_SIZES = {
    "cover_color": (480, "(min-width: 48rem) 27rem, 20rem"),  # cover_color.css: the colour slab
    "magazine": (560, "(min-width: 64rem) 36rem, 100vw"),
    "split_photo": (640, "(min-width: 64rem) 40vw, 100vw"),
}


def _cover_image(profile, layout: str) -> dict | None:
    if layout not in COVER_SIZES or not profile.cover_id:
        return None
    media = profile.cover
    if media is None or media.profile_id != profile.pk or not media.image:
        return None
    display, sizes = COVER_SIZES[layout]
    return responsive.responsive_image(
        media.image,
        display_width=display,
        width=media.width or 1200,
        height=media.height or 800,
        sizes=sizes,
        original_width=media.width or None,
    )


def _gallery(media, alt: str) -> list[dict]:
    gallery = []
    media = [m for m in media if m.image]
    for index, m in enumerate(media):
        width, height = m.width or 800, m.height or 600
        image = responsive.responsive_image(
            m.image,
            display_width=400,
            width=width,
            height=height,
            sizes=responsive.gallery_sizes(index, len(media)),
            original_width=m.width or None,
        )
        gallery.append(
            {
                **image,
                "url": image["src"],
                "full": m.image.url,  # lightbox / no-JS link: the largest stored copy
                "alt": clean_text(m.caption) or alt,
                "caption": clean_text(m.caption),
                "lazy": index > 0,
            }
        )
    return gallery


def _day_ranges(hours: dict, day: str) -> list[tuple[str, str]]:
    ranges = (r for r in hours.get(day) or [] if isinstance(r, list | tuple) and len(r) == 2)
    return [(a, b) for a, b in ranges if isinstance(a, str) and isinstance(b, str) and a < b]


def _local_now(now=None) -> datetime:
    return (now or timezone.now()).astimezone(PAGE_TZ)


def opening_state(opening_hours, now=None) -> dict | None:
    """“Ouvert maintenant / Fermé” of a page, computed in Africa/Douala time (None without hours).

    {"open": bool, "label": "Ouvert maintenant", "detail": "Ferme à 18:00"}. Pages are cached a few
    minutes: static/js/site-motion.js recomputes the state in the browser from the same data.
    """
    hours = opening_hours if isinstance(opening_hours, dict) else {}
    if not any(_day_ranges(hours, day) for day in OPENING_DAYS):
        return None
    local = _local_now(now)
    today, clock = local.weekday(), local.strftime("%H:%M")
    for start, end in _day_ranges(hours, OPENING_DAYS[today]):
        if start <= clock < end:
            return {"open": True, "label": _("Ouvert maintenant"), "detail": _("Ferme à %(t)s") % {"t": end}}
    for offset in range(8):
        day = OPENING_DAYS[(today + offset) % 7]
        later = [start for start, _end in _day_ranges(hours, day) if offset or start > clock]
        if not later:
            continue
        if offset == 0:
            detail = _("Ouvre à %(t)s") % {"t": later[0]}
        elif offset == 1:
            detail = _("Ouvre demain à %(t)s") % {"t": later[0]}
        else:
            detail = _("Ouvre %(d)s à %(t)s") % {"d": str(DAY_LABELS[day]).lower(), "t": later[0]}
        return {"open": False, "label": _("Fermé"), "detail": detail}
    return None  # pragma: no cover - unreachable: at least one range exists


def _hours(profile: Profile, now=None) -> list[dict]:
    hours = profile.opening_hours if isinstance(profile.opening_hours, dict) else {}
    if not hours:
        return []
    today = OPENING_DAYS[_local_now(now).weekday()]
    rows = []
    for day in OPENING_DAYS:
        ranges = _day_ranges(hours, day)
        rows.append(
            {
                "key": day,
                "day": str(DAY_LABELS[day]),
                "ranges": " · ".join(f"{a} – {b}" for a, b in ranges),
                "data": ",".join(f"{a}-{b}" for a, b in ranges),
                "today": day == today,
            }
        )
    return rows


def split_bio(bio: str) -> tuple[str, str]:
    """(lede, rest): the first sentence of the bio shown big (editorial lede), the rest as prose.

    Only a clean first sentence (40–220 characters, on the first line) becomes the lede; otherwise
    the whole bio stays in the prose. The text is never altered, only cut in two.
    """
    bio = (bio or "").strip()
    match = _SENTENCE_END_RE.search(bio)
    if not match or not 40 <= match.end() <= min(220, len(bio.split("\n", 1)[0])):
        return "", bio
    lede, rest = bio[: match.end()].strip(), bio[match.end() :].strip()
    return (lede, rest) if rest else ("", bio)


def name_fit(name: str) -> str:
    """Size step of the XXL page title so long words never break mid-word ("" = full size)."""
    words = (name or "").split()
    longest, total = max((len(w) for w in words), default=0), len(name or "")
    if longest >= 11 or total >= 28:
        return "xs"
    if longest >= 9 or total >= 20:
        return "s"
    return "m" if longest >= 7 else ""


def initials(name: str) -> str:
    words = [w for w in re.split(r"[\s\-'’]+", name or "") if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "·"


def _static_or_empty(path: str) -> str:
    if not path:
        return ""
    try:
        return static(path)
    except ValueError:  # missing from the static manifest: system fonts only
        return ""


def font_stylesheet_url(theme: themes.ResolvedTheme | None = None) -> str:
    """Self-hosted @font-face stylesheet of the theme's font pair (Archivo by default)."""
    return _static_or_empty(theme.font_css if theme else "css/fonts.css")


def _theme_context(profile: Profile, theme: themes.ResolvedTheme, stylesheet_url: str) -> dict:
    category = theme.theme.category
    font_css = font_stylesheet_url(theme) if theme.uses_webfont else ""
    hours = _hours(profile)
    return {
        "theme": theme,
        "sections": [{"key": key, "label": themes.section_label(key, category)} for key in theme.visible_sections()],
        "theme_css_url": stylesheet_url,
        "font_css_url": font_css,
        "font_preload_url": _static_or_empty(theme.font_preload) if font_css else "",
        "theme_color": theme.tokens["primary"],
        "cta_label": theme.cta_label or _("Écrire sur WhatsApp"),
        "hours": hours,
        "open_days": sum(1 for h in hours if h["ranges"]),
        "open_state": opening_state(profile.opening_hours),
    }


SECTION_ANCHORS = {
    "about": "presentation",
    "services": "prestations",
    "gallery": "realisations",
    "hours": "horaires",
    "area": "zone",
    "links": "liens",
    "contact": "contact",
}
NAV_SECTIONS = ("about", "services", "gallery", "hours", "contact")


def _nav_sections(context: dict) -> list[dict]:
    """In-page navigation: the main visible sections that actually render (same tests as their templates)."""
    present = {
        "about": bool(context["profile"].bio),
        "services": bool(context["services"]),
        "gallery": bool(context["gallery"]),
        "hours": bool(context["hours"]),
        "contact": True,
    }
    return [
        {"anchor": SECTION_ANCHORS[s["key"]], "label": s["label"]}
        for s in context["sections"]
        if s["key"] in NAV_SECTIONS and present[s["key"]]
    ]


def _profile_context(
    request,
    profile: Profile,
    *,
    owner_private: bool,
    theme: themes.ResolvedTheme | None = None,
    stylesheet_url: str = "",
    preview: bool = False,
) -> dict:
    city = profile.city
    job = profile.title
    name = profile.display_name
    url = profile.absolute_url
    services = list(profile.services.all())
    media = list(profile.media.all())
    links = [
        {"url": link.url, "label": link.get_kind_display(), "kind": link.kind}
        for link in profile.links.all()
        if _http_url(link.url)
    ]
    alt = profile_alt(name, job, city.name if city else "")
    og_version = images.og_fingerprint(profile)[:8]
    meta = profile_meta(profile, indexable=False if (owner_private or preview) else None, og_version=og_version)
    theme = theme or themes.resolve(profile)

    crumbs = _profile_breadcrumb(profile, name)
    photo = None
    if profile.photo:
        display, max_variant, sizes = themes.PHOTO_DISPLAY.get(
            theme.layout, (responsive.AVATAR_SIZE, responsive.AVATAR_MAX_VARIANT, "")
        )
        photo = responsive.responsive_image(profile.photo, display_width=display, max_width=max_variant, sizes=sizes)
    cover = _cover_image(profile, theme.layout)
    if cover and theme.layout in COVER_REPLACES_PHOTO:
        photo = cover  # image-first layouts: the big frame shows the cover instead of the portrait
    # JSON-LD image: the real photo only (og.png is noindex), never a placeholder (audit #1)
    entity = jsonld.profile_entity(profile, image_url=profile.photo.url if profile.photo else "")
    graph = jsonld.page_graph(
        path=profile.get_absolute_url(),
        name=meta["title"],
        lang=profile.language or settings.LANGUAGE_CODE,
        entity=entity,
        crumbs=_crumbs_for_jsonld(crumbs, profile.get_absolute_url()),
    )

    share_text = _("Découvre %(name)s%(job)s : %(url)s") % {
        "name": name,
        "job": f", {job_at_city(job, city.name if city else '')}" if (job or city) else "",
        "url": url,
    }
    whatsapp = _digits(profile.whatsapp)
    similar = selectors.similar_profiles(profile)
    context = {
        **_theme_context(profile, theme, stylesheet_url or f"/{profile.slug}/theme.css?v={theme.version}"),
        "preview": preview,
        "profile": profile,
        "meta": meta,
        "jsonld": jsonld.dumps(graph),
        "job": job,
        "subtitle": job_at_city(job, city.name if city else ""),
        "breadcrumb": crumbs,
        "services": services,
        "gallery": _gallery(media, alt),
        "photo": photo,
        "cover": cover,
        "links": links,
        "phone": profile.phone_public,
        "whatsapp_url": f"https://wa.me/{whatsapp}" if whatsapp else "",
        "email": profile.email_public,
        "maps_url": _maps_url(profile),
        "share_url": "https://wa.me/?text=" + quote(share_text),
        "contact_rel": CONTACT_REL,
        "user_link_rel": USER_LINK_REL,
        "similar": similar,
        "similar_title": (
            _("Autres %(plural)s à %(city)s") % {"plural": profile.trade.plural_name.lower(), "city": city.name}
            if similar and profile.trade and city
            else ""
        ),
        "show_branding": not _hide_branding(profile),
        "signup_url": signup_url(),
        "report_url": report_url(profile.slug),
        "owner_private": owner_private,
        "photo_alt": _("Photo de %(name)s") % {"name": name},
    }
    lede, bio_rest = split_bio(profile.bio)
    context.update(
        {
            "bio_lede": lede,
            "bio_rest": bio_rest,
            "initials": initials(name),
            "name_fit": name_fit(name),
            "prices_count": sum(1 for s in services if s.price_label),
            "nav_sections": _nav_sections(context),
        }
    )
    return context


@require_safe
@language_independent
def profile(request, slug):
    profile_obj, outcome = _lookup(request, slug)
    if outcome == "gone":
        return gone(request)
    if outcome == "old" or slug != slug.lower():
        return HttpResponsePermanentRedirect(profile_obj.get_absolute_url())
    owner_private = outcome == "owner_private"
    response = render_profile_page(request, profile_obj, owner_private=owner_private)
    if owner_private:
        response["X-Robots-Tag"] = NOINDEX
    return _set_public_cache(request, response, private=owner_private)


def render_profile_page(
    request,
    profile_obj: Profile,
    *,
    owner_private: bool = False,
    theme: themes.ResolvedTheme | None = None,
    stylesheet_url: str = "",
    preview: bool = False,
) -> HttpResponse:
    """The profile page rendered with its theme (live by default; the dashboard previews pass another one).

    Every theme template extends public/themes/_base.html: same head, JSON-LD, h1 and breadcrumb.
    """
    profile_obj = (
        Profile.objects.select_related("trade", "city", "city__country")
        .prefetch_related("services", "media", "links")
        .get(pk=profile_obj.pk)
    )
    theme = theme or themes.resolve(profile_obj)
    lang = profile_obj.language or settings.LANGUAGE_CODE
    with translation.override(lang):
        context = _profile_context(
            request,
            profile_obj,
            owner_private=owner_private,
            theme=theme,
            stylesheet_url=stylesheet_url,
            preview=preview,
        )
        response = render(request, theme.template, context)
    mark_language_independent(response, lang)  # the language comes from the profile, not the browser
    return response


@require_safe
def profile_trailing_slash(request, slug):
    return HttpResponsePermanentRedirect(f"/{slug.lower()}")


# --- profile resources (never indexed) --------------------------------------------------------


def theme_css_response(css: str) -> HttpResponse:
    response = HttpResponse(css.encode(), content_type="text/css; charset=utf-8")
    return _noindex(response)


@require_safe
def theme_css(request, slug):
    """/<slug>/theme.css?v=<hash>: the page's colours, fonts and corners as CSS custom properties.

    The URL is versioned by a hash of the settings, so a matching `v` is cached for a year; any other
    `v` (or none) gets a short cache. Publishing a theme changes the hash: the new page links a new URL.
    """
    profile_obj, response = _profile_resource(request, slug, "theme.css")
    if response:
        return response
    theme = themes.resolve(profile_obj)
    response = theme_css_response(theme.css())
    if not profile_obj.is_publicly_visible:
        return set_private_no_store(response)
    if request.GET.get("v") == theme.version:
        patch_cache_control(response, public=True, max_age=THEME_CSS_MAX_AGE, immutable=True)
    else:
        patch_cache_control(response, public=True, max_age=THEME_CSS_UNVERSIONED_MAX_AGE)
    return response


@require_safe
@language_independent
def vcard(request, slug):
    profile_obj, response = _profile_resource(request, slug, "contact.vcf")
    if response:
        return response
    body = build_vcard(profile_obj, url=profile_obj.absolute_url)
    response = HttpResponse(body.encode(), content_type="text/vcard; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{profile_obj.slug}.vcf"'
    if profile_obj.is_publicly_visible:
        patch_cache_control(response, public=True, max_age=VCARD_MAX_AGE)
    else:  # the owner downloading the card of a private page
        set_private_no_store(response)
    return _noindex(response)


def qr_target(profile_obj: Profile) -> str:
    code = selectors.active_card_code(profile_obj)
    if code:
        return f"{settings.SITE_URL}/c/{code}"
    return profile_obj.absolute_url


def _qr(request, slug, kind: str):
    profile_obj, response = _profile_resource(request, slug, f"qr.{kind}")
    if response:
        return response
    target = qr_target(profile_obj)
    if kind == "svg":
        response = HttpResponse(images.qr_svg(target), content_type="image/svg+xml")
    else:
        response = HttpResponse(images.qr_png(target), content_type="image/png")
    response["Content-Disposition"] = f'inline; filename="qr-{profile_obj.slug}.{kind}"'
    if request.GET.get("download"):
        response["Content-Disposition"] = f'attachment; filename="qr-{profile_obj.slug}.{kind}"'
    patch_cache_control(response, private=True, max_age=3600)
    return _noindex(response)


@require_safe
def qr_svg(request, slug):
    return _qr(request, slug, "svg")


@require_safe
def qr_png(request, slug):
    return _qr(request, slug, "png")


@require_safe
def og_image(request, slug):
    profile_obj, response = _profile_resource(request, slug, "og.png")
    if response:
        return response
    profile_obj = Profile.objects.select_related("trade", "city").get(pk=profile_obj.pk)
    with translation.override(profile_obj.language or settings.LANGUAGE_CODE):
        data = images.og_image_for(profile_obj)
    response = HttpResponse(data, content_type="image/png")
    if profile_obj.is_publicly_visible:
        patch_cache_control(response, public=True, max_age=86400)
    else:
        patch_cache_control(response, private=True, no_store=True)
    return _noindex(response)
