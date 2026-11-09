import pytest
from django.db import IntegrityError

from apps.cards import services
from apps.cards.models import Card
from tests.factories import CardFactory, ProfileFactory

pytestmark = pytest.mark.django_db


def test_batch_codes_are_unique_and_well_formed(settings):
    batch, pairs = services.create_batch("LOT-001", 200)
    codes = [p for p, _ in pairs]
    assert len(set(codes)) == 200 == batch.cards.count()
    for public, activation in pairs:
        assert len(public) == settings.CARD_CODE_LENGTH
        assert len(activation) == settings.CARD_ACTIVATION_CODE_LENGTH
        assert set(public) <= set(settings.CARD_CODE_ALPHABET)
    # Clear activation codes are never stored.
    stored = Card.objects.get(public_code=pairs[0][0])
    assert pairs[0][1] not in stored.activation_code_hash


def test_alphabet_has_no_ambiguous_characters(settings):
    assert not set("01OILU") & set(settings.CARD_CODE_ALPHABET)
    assert len(settings.CARD_CODE_ALPHABET) == 30


def test_code_lookup_is_case_insensitive():
    card = CardFactory(public_code="K7M2QXP")
    assert services.get_card("k7m2qxp") == card
    assert services.get_card(" k7m-2qxp ") == card


def test_activation_code_check_and_limit_per_ip(settings):
    card = CardFactory()
    assert services.check_activation_code(card, "abcd2345", "ip-a")  # case-insensitive
    for _ in range(settings.CARD_ACTIVATION_MAX_ATTEMPTS_PER_IP_HOUR):
        assert not services.check_activation_code(card, "WRONG000", "ip-b")
    with pytest.raises(services.CardError):
        services.check_activation_code(card, "ABCD2345", "ip-b")
    # Another IP is not blocked (no DoS on the legitimate owner).
    assert services.check_activation_code(card, "ABCD2345", "ip-c")


def test_activate_then_cannot_reactivate():
    card, profile = CardFactory(), ProfileFactory()
    services.activate_card(card, profile)
    card.refresh_from_db()
    assert card.status == Card.Status.ACTIVE and card.profile == profile
    with pytest.raises(services.CardError):
        services.activate_card(card, ProfileFactory())


def test_active_card_requires_profile_at_db_level():
    card = CardFactory()
    with pytest.raises(IntegrityError):
        Card.objects.filter(pk=card.pk).update(status=Card.Status.ACTIVE)


def test_several_cards_per_profile_and_disable():
    profile = ProfileFactory()
    c1, c2 = CardFactory(), CardFactory()
    services.activate_card(c1, profile)
    services.activate_card(c2, profile)
    assert profile.cards.count() == 2
    services.disable_card(c1, Card.DisabledReason.LOST)
    assert services.disable_cards_for_profile(profile) == 1
