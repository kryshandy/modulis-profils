"""Seed the four plans with their entitlements and their annual price in Cameroon (XAF)."""

from django.db import migrations

BASE = {
    "hide_branding": False,
    "verified_badge": False,
    "advanced_stats": False,
    "max_profiles": 1,
    "reviews": False,
    "quotes": False,
    "featured": False,
    "free_cards": 0,
}

PLANS = [
    # code, name, order, CM annual price, entitlements, description
    ("free", "Gratuit", 0, 0, {}, "Ta page pro en ligne, gratuitement."),
    (
        "essentiel",
        "Essentiel",
        1,
        12000,
        {"hide_branding": True, "verified_badge": True, "advanced_stats": True},
        "Badge vérifié, statistiques détaillées, sans logo Modulis.",
    ),
    (
        "pro",
        "Pro",
        2,
        30000,
        {
            "hide_branding": True,
            "verified_badge": True,
            "advanced_stats": True,
            "max_profiles": 3,
            "reviews": True,
            "quotes": True,
            "featured": True,
            "free_cards": 1,
        },
        "Tout Essentiel, plusieurs pages, avis clients, devis, mise en avant et une carte offerte.",
    ),
    (
        "team",
        "Équipe",
        3,
        15000,
        {
            "hide_branding": True,
            "verified_badge": True,
            "advanced_stats": True,
            "reviews": True,
            "quotes": True,
            "team": True,
        },
        "Pour les entreprises : prix annuel par membre, gestion centrale des cartes.",
    ),
]


def load(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    PlanPrice = apps.get_model("billing", "PlanPrice")
    Country = apps.get_model("core", "Country")
    cameroon = Country.objects.filter(code="CM").first()
    for code, name, order, amount, extra, description in PLANS:
        plan, _ = Plan.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "order": order,
                "description": description,
                "entitlements": {**BASE, **extra},
                "is_public": True,
            },
        )
        if cameroon is not None:
            PlanPrice.objects.get_or_create(
                plan=plan, country=cameroon, defaults={"amount": amount, "currency": cameroon.currency}
            )


def unload(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Subscription = apps.get_model("billing", "Subscription")
    codes = [p[0] for p in PLANS]
    used = set(Subscription.objects.values_list("plan__code", flat=True))
    Plan.objects.filter(code__in=[c for c in codes if c not in used]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0001_initial"),
        ("core", "0002_seed_cameroon"),
    ]
    operations = [migrations.RunPython(load, unload)]
