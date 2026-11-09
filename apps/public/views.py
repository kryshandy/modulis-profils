"""Public, server-rendered pages (plan §4, §6): home, cities, directory, profile and its resources."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
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
    clean_text,
    job_at_city,
    page_meta,
    profile_alt,
    profile_meta,
    truncate,
)

from . import images
from .vcard import build_vcard

logger = logging.getLogger(__name__)

DIRECTORY_PAGE_SIZE = 24
NOINDEX = "noindex"
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
    response = render(request, "410.html", status=410)
    response["X-Robots-Tag"] = NOINDEX
    return response


def _set_public_cache(request, response, *, private: bool = False) -> HttpResponse:
    if private:
        patch_cache_control(response, private=True, no_store=True)
    else:
        patch_cache_control(response, public=True, max_age=300)
    return response


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
    try:
        from apps.billing.services import has

        return has(profile, "hide_branding")
    except Exception:  # billing unavailable: keep the growth banner
        logger.exception("hide_branding lookup failed for profile %s", profile.pk)
        return False


# --- home, cities, directory -----------------------------------------------------------------


@require_safe
def home(request):
    minimum = selectors.directory_min()
    cities = selectors.city_stats()
    combos = selectors.directory_combos()
    context = {
        "meta": page_meta(
            title=_("Crée ta page pro gratuite – %(site)s") % {"site": settings.SITE_NAME},
            description=_(
                "Artisans, commerçants, freelances : crée gratuitement ta page professionnelle, "
                "partage-la sur WhatsApp et sois trouvé sur Google par tes clients, dans ta ville."
            ),
            path="/",
            indexable=True,
        ),
        "jsonld": jsonld.dumps(jsonld.website()),
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
    number = _page_number(request)
    paginator = Paginator(queryset, DIRECTORY_PAGE_SIZE)
    try:
        return paginator.page(number)
    except (EmptyPage, PageNotAnInteger):
        if number == 1:
            return paginator.page(1)  # empty first page is still a page (allow_empty_first_page)
        raise Http404 from None


def _paged_path(path: str, page) -> str:
    return path if page.number == 1 else f"{path}?page={page.number}"


@require_safe
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
    context = {
        "meta": page_meta(
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
        ),
        "city": city_obj,
        "page": page,
        "trades": [
            {**c, "linked": c["count"] >= minimum, "url": directory_path(c["trade"], c["city"])}
            for c in selectors.trades_in_city(city_obj)
        ],
        "breadcrumb": [(_("Accueil"), "/"), (city_obj.name, "")],
    }
    context["jsonld"] = jsonld.dumps(jsonld.breadcrumb(context["breadcrumb"]))
    return _set_public_cache(request, render(request, "public/city.html", context))


@require_safe
def directory(request, trade_plural, city):
    trade = selectors.find_trade_by_plural(trade_plural)
    city_obj = selectors.find_city(city) if trade else None
    if trade is None or city_obj is None:
        raise Http404
    path = directory_path(trade, city_obj)
    if request.path != path:
        return HttpResponsePermanentRedirect(path + (f"?{request.GET.urlencode()}" if request.GET else ""))
    page = _paginate(selectors.directory_profiles(trade, city_obj), request)
    indexable = page.paginator.count >= selectors.directory_min()
    heading = _("%(plural)s à %(city)s") % {"plural": trade.plural_name, "city": city_obj.name}
    title = heading if page.number == 1 else _("%(title)s – page %(n)d") % {"title": heading, "n": page.number}
    context = {
        "meta": page_meta(
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
        ),
        "heading": heading,
        "trade": trade,
        "city": city_obj,
        "page": page,
        "breadcrumb": [(_("Accueil"), "/"), (city_obj.name, city_path(city_obj)), (heading, "")],
    }
    context["jsonld"] = jsonld.dumps(jsonld.breadcrumb(context["breadcrumb"]))
    return _set_public_cache(request, render(request, "public/directory.html", context))


# --- profile page ----------------------------------------------------------------------------


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
    gallery = [
        {
            "url": m.image.url,
            "alt": clean_text(m.caption) or alt,
            "width": m.width or 800,
            "height": m.height or 600,
            "lazy": index > 0,
        }
        for index, m in enumerate(media)
        if m.image
    ]
    og_version = images.og_fingerprint(profile)[:8]
    meta = profile_meta(profile, indexable=False if owner_private else None, og_version=og_version)

    crumbs = [(_("Accueil"), "/")]
    if city:
        crumbs.append((city.name, city_path(city)))
        if profile.trade:
            crumbs.append(
                (
                    _("%(plural)s à %(city)s") % {"plural": profile.trade.plural_name, "city": city.name},
                    directory_path(profile.trade, city),
                )
            )
    crumbs.append((name, ""))
    crumbs_ld = [*crumbs[:-1], (name, profile.get_absolute_url())]

    image_url = profile.photo.url if profile.photo else f"/{profile.slug}/og.png"
    graph = [jsonld.profile_entity(profile, image_url=image_url), jsonld.breadcrumb(crumbs_ld)]

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
        "gallery": gallery,
        "links": links,
        "phone": profile.phone_public,
        "whatsapp_url": f"https://wa.me/{whatsapp}" if whatsapp else "",
        "email": profile.email_public,
        "maps_url": _maps_url(profile),
        "share_url": "https://wa.me/?text=" + quote(share_text),
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
    with translation.override(profile_obj.language or settings.LANGUAGE_CODE):
        context = _profile_context(request, profile_obj, owner_private=owner_private)
        response = render(request, "public/profile.html", context)
    if owner_private:
        response["X-Robots-Tag"] = NOINDEX
    return _set_public_cache(request, response, private=owner_private)


@require_safe
def profile_trailing_slash(request, slug):
    return HttpResponsePermanentRedirect(f"/{slug.lower()}")


# --- profile resources (never indexed) --------------------------------------------------------


@require_safe
def vcard(request, slug):
    profile_obj, response = _profile_resource(request, slug, "contact.vcf")
    if response:
        return response
    body = build_vcard(profile_obj, url=profile_obj.absolute_url)
    response = HttpResponse(body.encode(), content_type="text/vcard; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{profile_obj.slug}.vcf"'
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
