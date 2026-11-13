"""Pro space › Ma page › Blocs: page outline (order, show/hide) and block editing (ADR-0012)."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.dashboard.views.common import dash_render, profile_required
from apps.themes import services as themes

from . import services
from .models import PageBlock
from .registry import BLOCK_TYPES, MAX_BLOCK_IMAGES, MAX_BLOCKS, STYLE_CHOICES, STYLE_DEFAULTS

# Fixed sections of the page -> the editor tab where their content is written.
SECTION_EDITORS = {
    "about": "presentation",
    "services": "prestations",
    "gallery": "galerie",
    "hours": "horaires",
    "area": "metier",
    "links": "liens",
    "contact": "contact",
}
EMPTY_ROWS = 2  # blank rows offered under the filled items (up to the maximum)


def outline_context(profile) -> dict:
    """Context of the "Blocs" tab: the page plan and the block library."""
    category = themes.resolve(profile).theme.category
    blocks = {b.key: b for b in PageBlock.objects.filter(profile=profile).prefetch_related("images")}
    outline = themes.page_outline(profile)
    rows = []
    for index, item in enumerate(outline):
        key = item["key"]
        row = {"key": key, "visible": item["visible"], "first": index == 0, "last": index == len(outline) - 1}
        if themes.is_block_key(key):
            block = blocks.get(key)
            if block is None:
                continue
            row.update(
                block=block,
                label=(block.data or {}).get("title") or str(block.block_type.label),
                kind_label=block.block_type.label,
                icon=block.block_type.icon,
                complete=services.is_renderable(block),
                edit_url=reverse("dashboard:block_edit", args=[block.pk]),
            )
        else:
            row.update(
                label=themes.section_label(key, category),
                locked=key in themes.LOCKED_SECTIONS,
                edit_url=reverse("dashboard:edit", args=[SECTION_EDITORS[key]]),
            )
        row["pinned"] = key == "contact"
        rows.append(row)
    for i, row in enumerate(rows):
        row["can_up"] = i > 0 and not row["pinned"]
        row["can_down"] = i < len(rows) - 1 and not row["pinned"] and not rows[i + 1]["pinned"]
    return {
        "outline": rows,
        "library": list(BLOCK_TYPES.values()),
        "block_count": len(blocks),
        "max_blocks": MAX_BLOCKS,
        "room": len(blocks) < MAX_BLOCKS,
    }


def _panel(request, message: str = "", ok: bool = True):
    from apps.dashboard.views.editor import _respond

    return _respond(request, "blocs", ok=ok, message=message or None)


@profile_required
@require_POST
@ratelimit(key="user", rate="60/m", block=False)
def block_add(request):
    if getattr(request, "limited", False):
        return _panel(request, _("Doucement ! Attends quelques secondes et réessaie."), ok=False)
    try:
        block = services.add_block(request.profile, request.POST.get("kind", ""))
    except ValidationError as exc:
        return _panel(request, exc.messages[0], ok=False)
    messages.success(request, _("Bloc ajouté : remplis-le, il apparaîtra sur ta page dès qu'il est complet."))
    url = reverse("dashboard:block_edit", args=[block.pk])
    if request.htmx:
        response = _panel(request)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def _owned_block(request, pk: int) -> PageBlock:
    return get_object_or_404(PageBlock.objects.select_related("profile"), pk=pk, profile=request.profile)


def _form_rows(block: PageBlock, post=None, errors=None) -> dict:
    """Field rows of the edit form: current (or posted) values and errors, image slots with previews."""
    errors = errors or {}
    data = block.data or {}
    block_type = block.block_type
    images = {img.slot: img for img in block.images.all()}

    def value(name, saved):
        return post.get(name, "") if post is not None else saved

    def shown(spec, saved):
        if spec.kind == "video" and isinstance(saved, dict):
            return saved.get("url", "")
        return saved or ""

    fields = []
    for spec in block_type.fields:
        name = f"f_{spec.name}"
        fields.append(
            {
                "spec": spec,
                "name": name,
                "value": value(name, shown(spec, data.get(spec.name))),
                "error": errors.get(name),
            }
        )
    block_images = [
        {
            "slot": slot,
            "label": label,
            "name": f"img_{slot}",
            "current": images.get(slot),
            "error": errors.get(f"img_{slot}"),
        }
        for slot, label in block_type.images
    ]
    items = []
    if block_type.items:
        saved_items = data.get("items", [])
        count = min(block_type.items.max_items, max(len(saved_items) + EMPTY_ROWS, block_type.items.min_items))
        by_slot = {row.get("_slot", i): row for i, row in enumerate(saved_items)}
        for index in range(count):
            saved = by_slot.get(index, {})
            items.append(
                {
                    "index": index,
                    "number": index + 1,
                    "fields": [
                        {
                            "spec": spec,
                            "name": f"i{index}_{spec.name}",
                            "value": value(f"i{index}_{spec.name}", saved.get(spec.name, "")),
                            "error": errors.get(f"i{index}_{spec.name}"),
                        }
                        for spec in block_type.items.fields
                    ],
                    "images": [
                        {
                            "slot": f"{slot}_{index}",
                            "label": label,
                            "name": f"img_{slot}_{index}",
                            "current": images.get(f"{slot}_{index}"),
                            "error": errors.get(f"img_{slot}_{index}"),
                        }
                        for slot, label in block_type.items.images
                    ],
                    "filled": bool(saved),
                }
            )
    style = block.style or {}
    style_rows = [
        {
            "key": key,
            "name": f"s_{key}",
            "label": {"background": _("Fond"), "spacing": _("Espacement"), "align": _("Alignement")}[key],
            "choices": choices,
            "value": (post.get(f"s_{key}") if post is not None else style.get(key)) or STYLE_DEFAULTS[key],
        }
        for key, choices in STYLE_CHOICES.items()
        if key != "align" or block_type.alignable
    ]
    return {"fields": fields, "block_images": block_images, "items": items, "style_rows": style_rows}


@profile_required
@require_http_methods(["GET", "POST"])
@ratelimit(key="user", rate="30/m", method="POST", block=False)
def block_edit(request, pk: int):
    from apps.dashboard.views.editor import _section_context

    block = _owned_block(request, pk)
    errors = {}
    if request.method == "POST":
        if getattr(request, "limited", False):
            errors = {"form": _("Doucement ! Attends quelques secondes et réessaie.")}
        else:
            try:
                errors = services.update_block(block, request.POST, request.FILES)
            except ValidationError as exc:
                errors = {"form": exc.messages[0]}
            if not errors:
                block.refresh_from_db()
                if services.is_renderable(block):
                    messages.success(request, _("Bloc enregistré ✓ Il est visible sur ta page."))
                else:
                    messages.info(request, _("Bloc enregistré. Complète-le pour qu'il apparaisse sur ta page."))
                return redirect("dashboard:block_edit", pk=block.pk)
    ctx = _section_context(request, "blocs")
    ctx.update(
        panel_template="blocks/editor/_form.html",
        page_block=block,  # not "block": inside {% block %} tags Django binds that name to the BlockNode
        block_type=block.block_type,
        form_error=errors.get("form") or errors.get("images"),
        has_errors=bool(errors),
        complete=services.is_renderable(block),
        max_block_images=MAX_BLOCK_IMAGES,
        **_form_rows(block, request.POST if errors else None, errors),
    )
    return dash_render(request, "dashboard/edit/section.html", ctx, status=400 if errors else 200)


@profile_required
@require_POST
def block_delete(request, pk: int):
    block = _owned_block(request, pk)
    services.delete_block(block)
    if request.htmx:
        return _panel(request, _("Bloc supprimé."))
    messages.info(request, _("Bloc supprimé."))
    return redirect("dashboard:edit", section="blocs")


def _check_key(request, key: str) -> None:
    if key in themes.SECTION_KEYS:
        return
    if themes.is_block_key(key) and PageBlock.objects.filter(pk=int(key[1:]), profile=request.profile).exists():
        return
    raise Http404


@profile_required
@require_POST
@ratelimit(key="user", rate="120/m", block=False)
def outline_move(request, key: str):
    _check_key(request, key)
    if getattr(request, "limited", False):
        return _panel(request, _("Doucement ! Attends quelques secondes et réessaie."), ok=False)
    themes.move_section(request.profile, key, "down" if request.POST.get("direction") == "down" else "up")
    return _panel(request, _("Ordre enregistré ✓"))


@profile_required
@require_POST
def outline_visible(request, key: str):
    _check_key(request, key)
    visible = request.POST.get("visible") == "1"
    themes.set_section_visible(request.profile, key, visible)
    return _panel(request, _("Affiché sur ta page ✓") if visible else _("Masqué de ta page."))
