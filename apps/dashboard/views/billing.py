"""Subscription and plans screen in /espace/."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.billing.models import Plan
from apps.billing.services import current_plan_code, current_subscription, grant_plan

from .common import dash_render, profile_required


def _plan_features(plan: Plan) -> list[str]:
    """Return human-readable feature highlights for a plan."""
    ent = plan.entitlements or {}
    features = [_("Page pro en ligne et QR code")]
    if ent.get("hide_branding"):
        features.append(_("Sans logo Modulis en bas de page"))
    if ent.get("verified_badge"):
        features.append(_("Badge « Profil vérifié »"))
    if ent.get("advanced_stats"):
        features.append(_("Statistiques détaillées"))
    max_profiles = ent.get("max_profiles") or 1
    if max_profiles > 1:
        features.append(_("Jusqu'à %(n)s pages pro") % {"n": max_profiles})
    if ent.get("reviews"):
        features.append(_("Avis clients sur ta page"))
    if ent.get("quotes"):
        features.append(_("Demandes de devis"))
    if ent.get("featured"):
        features.append(_("Mise en avant dans l'annuaire"))
    free_cards = ent.get("free_cards") or 0
    if free_cards:
        features.append(_("%(n)s carte NFC offerte") % {"n": free_cards})
    if ent.get("team"):
        features.append(_("Gestion centralisée des cartes d'équipe"))
    return features


@profile_required
@require_http_methods(["GET", "POST"])
def billing_view(request):
    profile = request.profile
    active_code = current_plan_code(profile)

    if request.method == "POST":
        plan_code = (request.POST.get("plan_code") or "").strip()
        plan = Plan.objects.filter(code=plan_code, is_public=True).first()
        if plan is None:
            messages.error(request, _("Cette offre n'est pas disponible."))
            return redirect("dashboard:billing")
        if plan.code == active_code:
            messages.info(request, _("Tu utilises déjà l'offre %(plan)s.") % {"plan": plan.name})
            return redirect("dashboard:billing")
        grant_plan(
            profile,
            plan,
            created_by=request.user,
            note=_("Activation depuis l'espace pro (mode démo)"),
        )
        messages.success(request, _("Offre %(plan)s activée ✓") % {"plan": plan.name})
        return redirect("dashboard:billing")

    sub = current_subscription(profile)
    country = profile.city.country if profile.city_id else request.user.country
    plans = Plan.objects.filter(is_public=True).prefetch_related("prices").order_by("order")

    plan_cards = []
    for plan in plans:
        prices = list(plan.prices.all())
        price = next((p for p in prices if country and p.country_id == country.pk), None)
        if price is None and prices:
            price = prices[0]
        plan_cards.append(
            {
                "plan": plan,
                "price": price,
                "is_current": plan.code == active_code,
                "is_featured": plan.code == Plan.Code.PRO,
                "features": _plan_features(plan),
            }
        )

    current_plan = next((c["plan"] for c in plan_cards if c["is_current"]), None)
    return dash_render(
        request,
        "dashboard/billing.html",
        {
            "current_subscription": sub,
            "current_plan_code": active_code,
            "current_plan": current_plan,
            "plan_cards": plan_cards,
        },
    )
