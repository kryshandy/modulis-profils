"""Page editor: one section per screen, saved with HTMX (or a plain POST/redirect without JS)."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_http_methods, require_POST

from apps.profiles.services import refresh_seo_state

from ..content import bio_suggestions, service_examples
from ..forms import (
    AppearanceForm,
    BioForm,
    CaptionForm,
    ContactForm,
    IdentityForm,
    LinkForm,
    MediaUploadForm,
    ServiceForm,
    TradeCityForm,
)
from ..services import (
    COVER_COLORS,
    MAX_LINKS,
    MAX_MEDIA,
    MAX_SERVICES,
    add_link,
    add_media,
    add_service,
    delete_media,
    move_item,
    remove_profile_photo,
    set_profile_photo,
)
from .common import dash_render, edit_url, profile_required, with_toast

SECTIONS = [
    ("identite", gettext_lazy("Identité"), "user"),
    ("metier", gettext_lazy("Métier et zone"), "briefcase"),
    ("contact", gettext_lazy("Contact"), "phone"),
    ("presentation", gettext_lazy("Présentation"), "text"),
    ("prestations", gettext_lazy("Prestations"), "list"),
    ("galerie", gettext_lazy("Galerie"), "image"),
    ("liens", gettext_lazy("Liens"), "link"),
    ("apparence", gettext_lazy("Apparence"), "palette"),
]
SECTION_SLUGS = [s for s, _label, _icon in SECTIONS]

FORM_SECTIONS = {
    "identite": IdentityForm,
    "metier": TradeCityForm,
    "contact": ContactForm,
    "presentation": BioForm,
    "apparence": AppearanceForm,
}

# Checklist item key (profiles.services.completeness_items) -> editor section.
ITEM_SECTIONS = {
    "photo": "identite",
    "trade_city": "metier",
    "bio": "presentation",
    "services": "prestations",
    "contact": "contact",
    "gallery": "galerie",
}


def _section_context(request, section: str, form=None, **extra) -> dict:
    profile = request.profile
    ctx = {
        "section": section,
        "sections": SECTIONS,
        "form": form,
        "panel_template": f"dashboard/edit/_{section}.html",
        "section_label": {s: label for s, label, _icon in SECTIONS}[section],
        **extra,
    }
    if section == "presentation":
        ctx["suggestions"] = bio_suggestions(profile)
    elif section == "prestations":
        ctx.update(
            services=list(profile.services.all()),
            service_form=extra.get("service_form") or ServiceForm(),
            max_items=MAX_SERVICES,
            examples=service_examples(profile),
        )
    elif section == "galerie":
        ctx.update(media=list(profile.media.all()), upload_form=MediaUploadForm(), max_items=MAX_MEDIA)
    elif section == "liens":
        ctx.update(
            links=list(profile.links.all()),
            link_form=extra.get("link_form") or LinkForm(),
            max_items=MAX_LINKS,
        )
    elif section == "apparence":
        ctx["colors"] = COVER_COLORS
    return ctx


def _respond(request, section: str, *, ok: bool = True, message: str | None = None, **extra):
    """HTMX: re-render only the section panel with a toast. Otherwise: flash + redirect (PRG)."""
    if request.htmx:
        ctx = _section_context(request, section, **extra)
        response = dash_render(request, f"dashboard/edit/_{section}.html", ctx)
        kind = "success" if ok else "error"
        return with_toast(
            response, message or (_("Enregistré ✓") if ok else _("Vérifie les champs en rouge.")), kind=kind
        )
    if ok:
        messages.success(request, message or _("Enregistré ✓"))
        return redirect(edit_url(section))
    ctx = _section_context(request, section, **extra)
    return dash_render(request, "dashboard/edit/section.html", ctx)


def _make_form(section: str, profile, data=None):
    cls = FORM_SECTIONS[section]
    return cls(data, instance=profile)


@profile_required
@require_http_methods(["GET", "POST"])
def edit(request, section: str):
    if section not in SECTION_SLUGS:
        raise Http404
    profile = request.profile
    if request.method == "GET":
        form = _make_form(section, profile) if section in FORM_SECTIONS else None
        return dash_render(request, "dashboard/edit/section.html", _section_context(request, section, form=form))

    action = request.POST.get("action", "save")
    if section == "identite" and action in ("photo", "remove_photo"):
        return _photo(request, action)
    if section not in FORM_SECTIONS:
        raise Http404
    form = _make_form(section, profile, request.POST)
    if form.is_valid():
        form.save()
        refresh_seo_state(profile)
        profile.refresh_from_db()
        return _respond(request, section, form=_make_form(section, profile))
    return _respond(request, section, ok=False, form=form)


def _photo(request, action: str):
    profile = request.profile
    form = IdentityForm(instance=profile)
    if action == "remove_photo":
        remove_profile_photo(profile)
        return _respond(request, "identite", form=form, message=_("Photo retirée."))
    uploaded = next((f for f in request.FILES.getlist("photo") if f), None)
    try:
        set_profile_photo(profile, uploaded)
    except ValidationError as exc:
        return _respond(request, "identite", ok=False, form=form, photo_error=exc.messages[0], message=exc.messages[0])
    return _respond(request, "identite", form=form, message=_("Photo enregistrée ✓"))


# --- Services ---------------------------------------------------------------------------------


@profile_required
@require_POST
def service_add(request):
    form = ServiceForm(request.POST)
    if not form.is_valid():
        return _respond(request, "prestations", ok=False, service_form=form)
    try:
        add_service(request.profile, **form.cleaned_data)
    except ValidationError as exc:
        return _respond(request, "prestations", ok=False, message=exc.messages[0], service_form=form)
    return _respond(request, "prestations", message=_("Prestation ajoutée ✓"))


@profile_required
@require_POST
def service_update(request, pk: int):
    service = get_object_or_404(request.profile.services, pk=pk)
    form = ServiceForm(request.POST, instance=service)
    if not form.is_valid():
        return _respond(request, "prestations", ok=False, message=_("Le nom de la prestation est obligatoire."))
    form.save()
    refresh_seo_state(request.profile)
    return _respond(request, "prestations")


@profile_required
@require_POST
def service_delete(request, pk: int):
    service = get_object_or_404(request.profile.services, pk=pk)
    service.delete()
    refresh_seo_state(request.profile)
    return _respond(request, "prestations", message=_("Prestation supprimée."))


@profile_required
@require_POST
def service_move(request, pk: int):
    service = get_object_or_404(request.profile.services, pk=pk)
    move_item(request.profile.services.all(), service, request.POST.get("direction", "up"))
    return _respond(request, "prestations", message=_("Ordre enregistré ✓"))


# --- Gallery ----------------------------------------------------------------------------------


@profile_required
@require_POST
def media_add(request):
    files = [f for f in request.FILES.getlist("images") if f]
    caption = request.POST.get("caption", "")
    if not files:
        return _respond(request, "galerie", ok=False, message=_("Choisis au moins une photo."))
    added, errors = 0, []
    for uploaded in files:
        try:
            add_media(request.profile, uploaded, caption if len(files) == 1 else "")
            added += 1
        except ValidationError as exc:
            errors.append(f"{uploaded.name[:40]} : {exc.messages[0]}")
            if request.profile.media.count() >= MAX_MEDIA:
                break
    if errors:
        message = _("%(ok)d photo(s) ajoutée(s). Problème : %(err)s") % {"ok": added, "err": " ; ".join(errors[:3])}
        return _respond(request, "galerie", ok=added > 0, message=message, upload_errors=errors)
    return _respond(request, "galerie", message=_("%(n)d photo(s) ajoutée(s) ✓") % {"n": added})


@profile_required
@require_POST
def media_update(request, pk: int):
    media = get_object_or_404(request.profile.media, pk=pk)
    form = CaptionForm(request.POST)
    if form.is_valid():
        media.caption = form.cleaned_data["caption"].strip()
        media.save(update_fields=["caption"])
    return _respond(request, "galerie")


@profile_required
@require_POST
def media_delete(request, pk: int):
    media = get_object_or_404(request.profile.media, pk=pk)
    delete_media(media)
    return _respond(request, "galerie", message=_("Photo supprimée."))


@profile_required
@require_POST
def media_move(request, pk: int):
    media = get_object_or_404(request.profile.media, pk=pk)
    move_item(request.profile.media.all(), media, request.POST.get("direction", "up"))
    return _respond(request, "galerie", message=_("Ordre enregistré ✓"))


# --- Links ------------------------------------------------------------------------------------


@profile_required
@require_POST
def link_add(request):
    form = LinkForm(request.POST)
    if not form.is_valid():
        return _respond(request, "liens", ok=False, link_form=form)
    try:
        add_link(request.profile, form.cleaned_data["kind"], form.cleaned_data["url"])
    except ValidationError as exc:
        return _respond(request, "liens", ok=False, message=exc.messages[0], link_form=form)
    return _respond(request, "liens", message=_("Lien ajouté ✓"))


@profile_required
@require_POST
def link_delete(request, pk: int):
    link = get_object_or_404(request.profile.links, pk=pk)
    link.delete()
    refresh_seo_state(request.profile)
    return _respond(request, "liens", message=_("Lien supprimé."))


@profile_required
@require_POST
def link_move(request, pk: int):
    link = get_object_or_404(request.profile.links, pk=pk)
    move_item(request.profile.links.all(), link, request.POST.get("direction", "up"))
    return _respond(request, "liens", message=_("Ordre enregistré ✓"))
