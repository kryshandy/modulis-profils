"""Paid plans unlock the premium themes: entitlement "premium_themes" (free plan: non-premium themes only)."""

from django.db import migrations

PAID = ("essentiel", "pro", "team")


def grant(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.filter(code__in=PAID):
        plan.entitlements = {**(plan.entitlements or {}), "premium_themes": True}
        plan.save(update_fields=["entitlements"])
    for plan in Plan.objects.filter(code="free"):
        plan.entitlements = {**(plan.entitlements or {}), "premium_themes": False}
        plan.save(update_fields=["entitlements"])


def revoke(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for plan in Plan.objects.all():
        if "premium_themes" in (plan.entitlements or {}):
            plan.entitlements = {k: v for k, v in plan.entitlements.items() if k != "premium_themes"}
            plan.save(update_fields=["entitlements"])


class Migration(migrations.Migration):
    dependencies = [
        ("themes", "0002_seed_themes"),
        ("billing", "0002_seed_plans"),
    ]
    operations = [migrations.RunPython(grant, revoke)]
