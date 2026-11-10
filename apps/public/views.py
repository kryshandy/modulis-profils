"""Public, server-rendered pages (plan §4, §6): home, cities, directory, profile and its resources."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import translation
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext as _
from django.views.decorators.http import require_safe

from apps.profiles.models import Profile, SlugRegistry
from apps.profiles.services import resolve_slug
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
_DIGITS_RE = re.compile(r"\D+")


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


def _city_crumb(city, minimum: int) -> tuple[str, str]:
    """The city level is linked only when /villes/<city> is indexable (like the home `linked`)."""
    return (city.name, city_path(city) if selectors.city_count(city) >= minimum else "")


# --- home, cities, directory -----------------------------------------------------------------


@require_safe
@language_independent
def home(request):
    minimum = selectors.directory_min()
    cities = selectors.city_stats()
    combos = selectors.directory_combos()
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
        crumbs.append(_city_crumb(city, minimum))
        if profile.trade:
            linked = selectors.directory_count(profile.trade, city) >= minimum
            crumbs.append(
                (
                    _("%(plural)s à %(city)s") % {"plural": profile.trade.plural_name, "city": city.name},
                    directory_path(profile.trade, city) if linked else "",
                )
            )
    crumbs.append((name, ""))
    return crumbs


def _gallery(media, alt: str) -> list[dict]:
    gallery = []
    for index, m in enumerate(media):
        if not m.image:
            continue
        width, height = m.width or 800, m.height or 600
        image = responsive.responsive_image(
            m.image,
            display_width=320,
            width=width,
            height=height,
            sizes=responsive.GALLERY_SIZES,
            original_width=m.width or None,
        )
        gallery.append({**image, "url": image["src"], "alt": clean_text(m.caption) or alt, "lazy": index > 0})
    return gallery


def _profile_context(request, profile: Profile, *, owner_private: bool) -> dict:
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
    meta = profile_meta(profile, indexable=False if owner_private else None, og_version=og_version)

    crumbs = _profile_breadcrumb(profile, name)
    photo = None
    if profile.photo:
        photo = responsive.responsive_image(
            profile.photo, display_width=responsive.AVATAR_SIZE, max_width=responsive.AVATAR_MAX_VARIANT
        )
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
    return {
        "profile": profile,
        "meta": meta,
        "jsonld": jsonld.dumps(graph),
        "job": job,
        "subtitle": job_at_city(job, city.name if city else ""),
        "breadcrumb": crumbs,
        "services": services,
        "gallery": _gallery(media, alt),
        "photo": photo,
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


@require_safe
@language_independent
def profile(request, slug):
    profile_obj, outcome = _lookup(request, slug)
    if outcome == "gone":
        return gone(request)
    if outcome == "old" or slug != slug.lower():
        return HttpResponsePermanentRedirect(profile_obj.get_absolute_url())
    profile_obj = (
        Profile.objects.select_related("trade", "city", "city__country")
        .prefetch_related("services", "media", "links")
        .get(pk=profile_obj.pk)
    )
    owner_private = outcome == "owner_private"
    lang = profile_obj.language or settings.LANGUAGE_CODE
    with translation.override(lang):
        context = _profile_context(request, profile_obj, owner_private=owner_private)
        response = render(request, "public/profile.html", context)
    mark_language_independent(response, lang)  # the language comes from the profile, not the browser
    if owner_private:
        response["X-Robots-Tag"] = NOINDEX
    return _set_public_cache(request, response, private=owner_private)


@require_safe
def profile_trailing_slash(request, slug):
    return HttpResponsePermanentRedirect(f"/{slug.lower()}")


# --- profile resources (never indexed) --------------------------------------------------------


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
