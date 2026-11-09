"""Shared factory_boy factories. Fake data only — never real people (CLAUDE.md)."""

import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.cards.models import Card, CardBatch
from apps.core.models import City, Country, Trade
from apps.profiles.models import Profile, ProfileService, SlugRegistry


def cameroon() -> Country:
    return Country.objects.get_or_create(
        code="CM", defaults={"name": "Cameroun", "phone_prefix": "+237", "currency": "XAF", "is_active": True}
    )[0]


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("phone",)

    phone = factory.Sequence(lambda n: f"+2376{n:08d}")
    full_name = factory.Faker("name", locale="fr_FR")
    phone_verified_at = factory.LazyFunction(timezone.now)
    country = factory.LazyFunction(cameroon)


class CityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = City
        django_get_or_create = ("country", "slug")

    country = factory.LazyFunction(cameroon)
    name = "Douala"
    slug = "douala"


class TradeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Trade
        django_get_or_create = ("slug",)

    name = "Plombier"
    name_feminine = "Plombière"
    slug = "plombier"
    plural_slug = "plombiers"
    plural_name = "Plombiers"
    segment = Trade.Segment.CRAFT
    schema_type = "Plumber"


class ProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Profile
        skip_postgeneration_save = True

    user = factory.SubFactory(UserFactory)
    display_name = factory.Faker("name", locale="fr_FR")
    slug = factory.Sequence(lambda n: f"pro-test-{n}")
    trade = factory.SubFactory(TradeFactory)
    city = factory.SubFactory(CityFactory)
    whatsapp = factory.SelfAttribute("user.phone")
    phone_public = factory.SelfAttribute("user.phone")

    @factory.post_generation
    def register_slug(obj, create, extracted, **kwargs):
        if create:
            SlugRegistry.objects.get_or_create(slug=obj.slug, defaults={"kind": "current", "profile": obj})


COMPLETE_BIO = (
    "Plombier depuis douze ans à Douala, j'interviens rapidement pour les fuites, l'installation de "
    "chauffe-eau, la pose de sanitaires et la rénovation complète de salles de bain. Devis gratuit, "
    "travail propre et garanti, disponible six jours sur sept dans tous les quartiers de la ville. "
    "Je travaille avec des pièces de qualité et je conseille chaque client sur la solution la plus durable."
)


def make_complete_profile(**kwargs) -> Profile:
    """A profile that satisfies every indexing condition except the photo (score 80)."""
    from apps.profiles.services import refresh_seo_state

    profile = ProfileFactory(bio=kwargs.pop("bio", COMPLETE_BIO), **kwargs)
    ProfileService.objects.create(profile=profile, title="Réparation de fuites", description="Intervention rapide")
    ProfileService.objects.create(profile=profile, title="Pose de chauffe-eau", description="Toutes marques")
    for i in range(2):
        profile.links.create(kind="website", url=f"https://exemple.test/{i}")
    refresh_seo_state(profile)
    profile.refresh_from_db()
    return profile


class CardBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CardBatch

    reference = factory.Sequence(lambda n: f"LOT-TEST-{n:03d}")
    quantity = 1


class CardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Card

    public_code = factory.Sequence(lambda n: f"TST{n:04d}".replace("0", "2").replace("1", "3"))
    batch = factory.SubFactory(CardBatchFactory)
    activation_code_hash = factory.LazyAttribute(
        lambda o: __import__("apps.cards.services", fromlist=["x"]).hash_activation_code(o.public_code, "ABCD2345")
    )
