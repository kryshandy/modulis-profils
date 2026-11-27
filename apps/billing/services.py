"""Entitlements, subscriptions and payments (Point d'équipe §3)."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.profiles.models import Profile

from .models import Payment, Plan, PlanPrice, Subscription
from .providers import PaymentError, get_provider

logger = logging.getLogger(__name__)

FREE_ENTITLEMENTS = {
    "hide_branding": False,
    "verified_badge": False,
    "advanced_stats": False,
    "max_profiles": 1,
    "reviews": False,
    "quotes": False,
    "featured": False,
    "free_cards": 0,
}


def current_subscription(profile: Profile) -> Subscription | None:
    now = timezone.now()
    return (
        profile.subscriptions.select_related("plan")
        .filter(status=Subscription.Status.ACTIVE, starts_at__lte=now, ends_at__gt=now)
        .order_by("-ends_at")
        .first()
    )


def current_plan_code(profile: Profile) -> str:
    sub = current_subscription(profile)
    return sub.plan.code if sub else Plan.Code.FREE


def entitlements(profile: Profile) -> dict:
    sub = current_subscription(profile)
    if sub is None:
        return dict(FREE_ENTITLEMENTS)
    return {**FREE_ENTITLEMENTS, **sub.plan.entitlements}


def has(profile: Profile, entitlement: str) -> bool:
    return bool(entitlements(profile).get(entitlement))


@transaction.atomic
def grant_plan(
    profile: Profile, plan: Plan, *, days: int = 365, source=Subscription.Source.MANUAL, created_by=None, note: str = ""
) -> Subscription:
    """Start or extend a subscription. Renewal before expiry extends from the current end date."""
    current = current_subscription(profile)
    start = current.ends_at if current and current.plan_id == plan.pk else timezone.now()
    return Subscription.objects.create(
        profile=profile,
        plan=plan,
        starts_at=start,
        ends_at=start + timedelta(days=days),
        source=source,
        created_by=created_by,
        note=note,
    )


def expire_subscriptions() -> int:
    """Daily job: mark ended subscriptions as expired. Content is never deleted (back to free)."""
    return Subscription.objects.filter(status=Subscription.Status.ACTIVE, ends_at__lte=timezone.now()).update(
        status=Subscription.Status.EXPIRED
    )


def initiate_payment(
    profile: Profile,
    plan: Plan,
    provider: str = "sandbox",
    *,
    callback_url: str = "",
) -> Payment:
    """Create a pending Payment for `plan` at the profile's country price and initiate it via `provider`."""
    if plan.code == Plan.Code.FREE:
        raise PaymentError(_("L'offre gratuite ne nécessite pas de paiement."))

    country = profile.user.country
    if country is None:
        raise PaymentError(_("Aucun tarif disponible pour cette offre dans ton pays."))

    price = PlanPrice.objects.filter(plan=plan, country=country).first()
    if price is None or price.amount <= 0:
        raise PaymentError(_("Aucun tarif disponible pour cette offre dans ton pays."))

    provider_impl = get_provider(provider)
    reference = f"PAY-{uuid.uuid4().hex[:16].upper()}"

    with transaction.atomic():
        payment = Payment.objects.create(
            reference=reference,
            provider=provider_impl.name,
            profile=profile,
            plan=plan,
            amount=price.amount,
            currency=price.currency,
            status=Payment.Status.PENDING,
        )
        init_data = provider_impl.initiate(payment, callback_url)
        payment.provider_reference = init_data.get("provider_reference", "")
        payment.raw_payload = init_data.get("raw", {})
        payment.save(update_fields=["provider_reference", "raw_payload", "updated_at"])

    return payment


@transaction.atomic
def confirm_payment(reference: str, provider_reference: str = "", payload: dict | None = None) -> Payment:
    """Idempotently confirm a payment after locking its row and verifying its status with the provider."""
    try:
        payment = Payment.objects.select_for_update().select_related("profile", "plan").get(reference=reference)
    except Payment.DoesNotExist as exc:
        raise PaymentError(_("Paiement introuvable.")) from exc

    if payment.status == Payment.Status.SUCCEEDED:
        return payment

    if payment.status in (Payment.Status.FAILED, Payment.Status.REFUNDED):
        raise PaymentError(_("Ce paiement ne peut plus être confirmé."))

    if payload:
        if "amount" in payload and int(payload["amount"]) != payment.amount:
            raise PaymentError(_("Montant du paiement incohérent."))
        if "currency" in payload and payload["currency"] != payment.currency:
            raise PaymentError(_("Devise du paiement incohérente."))
        payment.raw_payload = {**payment.raw_payload, **payload}

    provider_impl = get_provider(payment.provider)
    verification = provider_impl.verify(payment)

    if verification.get("amount") != payment.amount or verification.get("currency") != payment.currency:
        raise PaymentError(_("Montant ou devise de vérification incohérent."))

    verified_status = verification["status"]
    resolved_provider_ref = provider_reference or verification.get("provider_reference") or payment.provider_reference

    if verified_status == Payment.Status.SUCCEEDED:
        payment.status = Payment.Status.SUCCEEDED
        payment.provider_reference = resolved_provider_ref
        if payment.plan is not None:
            payment.subscription = grant_plan(
                payment.profile,
                payment.plan,
                source=Subscription.Source.PAYMENT,
                note=f"Paiement {payment.reference}",
            )
        payment.save(update_fields=["status", "provider_reference", "raw_payload", "subscription", "updated_at"])
    elif verified_status == Payment.Status.FAILED:
        payment.status = Payment.Status.FAILED
        payment.provider_reference = resolved_provider_ref
        payment.save(update_fields=["status", "provider_reference", "raw_payload", "updated_at"])
    elif payload:
        payment.save(update_fields=["raw_payload", "updated_at"])

    return payment


def reconcile_pending_payments(*, older_than_minutes: int = 15, max_age_hours: int = 72) -> dict:
    """Verify pending payments with their provider and finalize any that succeeded or failed."""
    now = timezone.now()
    pending = Payment.objects.filter(
        status=Payment.Status.PENDING,
        created_at__lte=now - timedelta(minutes=older_than_minutes),
        created_at__gte=now - timedelta(hours=max_age_hours),
    ).order_by("created_at")

    stats = {"checked": 0, "confirmed": 0, "failed": 0, "still_pending": 0, "errors": 0}
    for payment in pending:
        stats["checked"] += 1
        try:
            provider_impl = get_provider(payment.provider)
            verification = provider_impl.verify(payment)
            status = verification["status"]
            if status == Payment.Status.SUCCEEDED:
                updated = confirm_payment(
                    payment.reference,
                    provider_reference=verification.get("provider_reference", ""),
                    payload=verification.get("raw"),
                )
                if updated.status == Payment.Status.SUCCEEDED:
                    stats["confirmed"] += 1
            elif status == Payment.Status.FAILED:
                with transaction.atomic():
                    locked = Payment.objects.select_for_update().get(pk=payment.pk)
                    if locked.status == Payment.Status.PENDING:
                        locked.status = Payment.Status.FAILED
                        locked.save(update_fields=["status", "updated_at"])
                        stats["failed"] += 1
            else:
                stats["still_pending"] += 1
        except PaymentError:
            logger.warning("Failed to reconcile payment %s", payment.reference, exc_info=True)
            stats["errors"] += 1

    return stats
