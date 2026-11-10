"""Card services: batch generation, activation, linking, disabling.

Rules (ADR-0005): the activation code is checked BEFORE any SMS is sent; attempts are limited per
(card, IP); codes are random, unguessable, never change; an active card always has a profile.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.profiles.models import Profile

from .models import Card, CardActivationAttempt, CardBatch


class CardError(Exception):
    """User-facing error."""


def generate_code(length: int | None = None) -> str:
    alphabet = settings.CARD_CODE_ALPHABET
    return "".join(secrets.choice(alphabet) for _ in range(length or settings.CARD_CODE_LENGTH))


def normalize_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "").replace("-", "")


def hash_activation_code(public_code: str, activation_code: str) -> str:
    """HMAC-SHA256 keyed with the server secret.

    A slow password hash (PBKDF2) would take minutes for a 1 000-card batch. Brute force is already
    prevented online by attempt limits and offline by the secret key (30^8 ≈ 6.6e11 codes).
    """
    message = f"{public_code}:{normalize_code(activation_code)}".encode()
    return hmac.new(settings.CARD_ACTIVATION_KEY.encode(), message, hashlib.sha256).hexdigest()


@transaction.atomic
def create_batch(
    reference: str, quantity: int, *, kind=CardBatch.Kind.STANDARD, created_by=None, supplier: str = ""
) -> tuple[CardBatch, list[tuple[str, str]]]:
    """Create a batch and its cards. Returns the (public_code, activation_code) pairs in clear.

    The clear activation codes exist ONLY in this return value: they go to the printer export and
    are never stored (only their hash is).
    """
    if quantity < 1 or quantity > 20000:
        raise CardError(_("La quantité doit être comprise entre 1 et 20 000."))
    batch = CardBatch.objects.create(
        reference=reference, quantity=quantity, kind=kind, created_by=created_by, supplier=supplier
    )
    pairs: list[tuple[str, str]] = []
    while len(pairs) < quantity:
        public = generate_code()
        activation = generate_code(settings.CARD_ACTIVATION_CODE_LENGTH)
        try:
            with transaction.atomic():
                Card.objects.create(
                    public_code=public, activation_code_hash=hash_activation_code(public, activation), batch=batch
                )
        except IntegrityError:
            continue  # astronomically rare collision: draw again
        pairs.append((public, activation))
    return batch, pairs


def get_card(code: str) -> Card | None:
    return Card.objects.select_related("profile").filter(public_code=normalize_code(code)).first()


def activation_attempts_left(card: Card, ip_hash: str) -> int:
    since = timezone.now() - timedelta(hours=1)
    used = CardActivationAttempt.objects.filter(
        card=card, ip_hash=ip_hash, created_at__gte=since, success=False
    ).count()
    return max(settings.CARD_ACTIVATION_MAX_ATTEMPTS_PER_IP_HOUR - used, 0)


def check_activation_code(card: Card, activation_code: str, ip_hash: str) -> bool:
    """Step 1 of activation (before any OTP). Records the attempt.

    The card row is locked so that parallel POSTs cannot exceed the attempt limit (code review #7).
    Errors are raised BEFORE the attempt is recorded, never after (ATOMIC_REQUESTS rule).
    """
    with transaction.atomic():
        card = Card.objects.select_for_update().get(pk=card.pk)
        if card.status in (Card.Status.ACTIVE, Card.Status.DISABLED):
            raise CardError(_("Cette carte est déjà activée ou désactivée."))
        if activation_attempts_left(card, ip_hash) <= 0:
            raise CardError(_("Trop d'essais. Réessaie dans une heure."))
        ok = hmac.compare_digest(card.activation_code_hash, hash_activation_code(card.public_code, activation_code))
        CardActivationAttempt.objects.create(card=card, ip_hash=ip_hash, success=ok)
    return ok


@transaction.atomic
def activate_card(card: Card, profile: Profile) -> Card:
    card = Card.objects.select_for_update().get(pk=card.pk)
    if card.status in (Card.Status.ACTIVE, Card.Status.DISABLED):
        raise CardError(_("Cette carte est déjà activée ou désactivée."))
    card.status = Card.Status.ACTIVE
    card.profile = profile
    card.activated_at = timezone.now()
    card.sold_at = card.sold_at or card.activated_at
    card.save()
    return card


@transaction.atomic
def disable_card(card: Card, reason: str = Card.DisabledReason.LOST) -> Card:
    card = Card.objects.select_for_update().get(pk=card.pk)
    card.status = Card.Status.DISABLED
    card.disabled_at = timezone.now()
    card.disabled_reason = reason
    card.save()
    return card


def disable_cards_for_profile(profile: Profile, reason: str = Card.DisabledReason.OTHER) -> int:
    return (
        Card.objects.filter(profile=profile)
        .exclude(status=Card.Status.DISABLED)
        .update(status=Card.Status.DISABLED, disabled_at=timezone.now(), disabled_reason=reason)
    )


def record_scan(card: Card) -> None:
    Card.objects.filter(pk=card.pk).update(scan_count=F("scan_count") + 1, last_scan_at=timezone.now())


def mark_sold(card: Card) -> bool:
    """Stock → sold (sale by an agent or a shop). Returns False if the card is not in stock."""
    return bool(
        Card.objects.filter(pk=card.pk, status=Card.Status.STOCK).update(
            status=Card.Status.SOLD, sold_at=timezone.now()
        )
    )


def batch_export_rows(pairs: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Rows of the printer export: (public_code, printed URL, activation code in clear)."""
    base = f"{settings.SITE_URL}/c/"
    return [(public, base + public, activation) for public, activation in pairs]


from apps.core.turnstile import TURNSTILE_VERIFY_URL, verify_turnstile  # noqa: E402,F401  (re-export)


def active_card_code(profile: Profile) -> str | None:
    """Public code of the profile's first active card (QR target, plan §4), or None."""
    card = (
        Card.objects.filter(profile=profile, status=Card.Status.ACTIVE)
        .order_by("activated_at", "pk")
        .only("public_code")
        .first()
    )
    return card.public_code if card else None
