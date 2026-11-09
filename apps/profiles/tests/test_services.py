import pytest
from django.core.exceptions import ValidationError

from apps.profiles import services
from apps.profiles.models import Profile, SlugRegistry
from apps.seo.models import IndexingQueue
from tests.factories import COMPLETE_BIO, CityFactory, ProfileFactory, TradeFactory, UserFactory

pytestmark = pytest.mark.django_db


class TestSlugGeneration:
    def test_name_then_trade_then_city(self):
        trade, city = TradeFactory(), CityFactory()
        assert services.generate_slug("Ange Kenmogne", trade, city) == "ange-kenmogne"
        SlugRegistry.objects.create(slug="ange-kenmogne", kind="reserved")
        assert services.generate_slug("Ange Kenmogne", trade, city) == "ange-kenmogne-plombier"
        SlugRegistry.objects.create(slug="ange-kenmogne-plombier", kind="reserved")
        assert services.generate_slug("Ange Kenmogne", trade, city) == "ange-kenmogne-plombier-douala"
        SlugRegistry.objects.create(slug="ange-kenmogne-plombier-douala", kind="reserved")
        assert services.generate_slug("Ange Kenmogne", trade, city) == "ange-kenmogne-plombier-douala-2"

    def test_accents_and_case(self):
        assert services.generate_slug("Hélène ÉTOÉ") == "helene-etoe"

    def test_one_word_name_never_auto_assigned(self):
        slug = services.generate_slug("Paul", TradeFactory())
        assert slug == "paul-plombier"

    def test_reserved_trade_and_city_slugs(self):
        TradeFactory()
        CityFactory()
        services.sync_reserved_slugs()
        for slug in ["plombier", "plombiers", "douala", "espace", "gestion", "c"]:
            assert not services.is_slug_available(slug)


class TestAutomaticCreation:
    def test_get_or_create_profile_never_duplicates(self):
        user, profile, created = services.get_or_create_profile("+237690000010", "Marie Ngo", city=CityFactory())
        assert created
        user2, profile2, created2 = services.get_or_create_profile("+237690000010", "Autre Nom")
        assert not created2
        assert profile2.pk == profile.pk and user2.pk == user.pk
        assert Profile.objects.count() == 1

    def test_slug_is_registered_as_current(self):
        _user, profile, _ = services.get_or_create_profile("+237690000011", "Jean Talla")
        entry = SlugRegistry.objects.get(slug=profile.slug)
        assert entry.kind == "current" and entry.profile == profile

    def test_contact_prefilled_with_verified_phone(self):
        _user, profile, _ = services.get_or_create_profile("+237690000012", "Paul Mbida")
        assert profile.whatsapp == "+237690000012"


class TestSlugChange:
    def test_old_slug_kept_for_301(self):
        profile = ProfileFactory(slug="ancien-nom")
        services.change_slug(profile, "nouveau-nom")
        assert SlugRegistry.objects.get(slug="ancien-nom").kind == "old"
        kind, target = services.resolve_slug("ancien-nom")
        assert kind == "old" and target == profile
        assert services.resolve_slug("nouveau-nom") == ("current", profile)

    def test_taken_slug_refused(self):
        ProfileFactory(slug="deja-pris")
        other = ProfileFactory()
        with pytest.raises(ValidationError):
            services.change_slug(other, "deja-pris")

    def test_old_slug_never_reassigned(self):
        first = ProfileFactory(slug="nom-libere")
        services.change_slug(first, "nom-nouveau")
        with pytest.raises(ValidationError):
            services.change_slug(ProfileFactory(), "nom-libere")

    def test_max_changes_per_year(self, settings):
        settings.SLUG_MAX_CHANGES_PER_YEAR = 1
        profile = ProfileFactory(slug="nom-un")
        services.change_slug(profile, "nom-deux")
        with pytest.raises(ValidationError):
            services.change_slug(profile, "nom-trois")

    def test_generic_slug_refused_for_incomplete_profile(self):
        with pytest.raises(ValidationError):
            services.change_slug(ProfileFactory(), "boss")

    @pytest.mark.parametrize("bad", ["ab", "-abc", "abc-", "a b c", "ABC", "a--b", "x" * 51, "é-a"])
    def test_format(self, bad):
        with pytest.raises(ValidationError):
            services.validate_slug_format(bad)


class TestSeoState:
    def test_complete_profile_is_indexable(self, complete_profile):
        assert complete_profile.completeness_score >= 70
        assert complete_profile.is_indexable, services.indexability_blockers(complete_profile)

    def test_score_without_bio_is_not_enough(self):
        """Review item #2: photo + trade/city + services + contact = 70 but no own text → noindex."""
        profile = ProfileFactory(bio="")
        profile.services.create(title="A")
        profile.services.create(title="B")
        services.refresh_seo_state(profile)
        assert not profile.is_indexable

    def test_duplicated_bio_blocks_indexing(self, complete_profile):
        from tests.factories import make_complete_profile

        copy = make_complete_profile(bio=COMPLETE_BIO)
        assert not copy.is_indexable
        assert any("identique" in r for r in services.indexability_blockers(copy))

    def test_private_profile_not_indexable(self, complete_profile):
        complete_profile.visibility = Profile.Visibility.PRIVATE
        complete_profile.save()
        services.refresh_seo_state(complete_profile)
        assert not complete_profile.is_indexable

    def test_indexing_queued_on_change(self, complete_profile, django_capture_on_commit_callbacks):
        IndexingQueue.objects.all().delete()
        with django_capture_on_commit_callbacks(execute=True):
            services.refresh_seo_state(complete_profile)
        assert IndexingQueue.objects.filter(url=complete_profile.absolute_url).exists()


class TestLifecycle:
    def test_delete_profile_erases_and_keeps_hash(self, django_capture_on_commit_callbacks):
        profile = ProfileFactory(slug="jean-a-effacer", bio="texte")
        with django_capture_on_commit_callbacks(execute=True):
            services.delete_profile(profile)
        profile.refresh_from_db()
        assert profile.status == Profile.Status.DELETED
        assert profile.bio == "" and profile.display_name == "—"
        assert not SlugRegistry.objects.filter(slug="jean-a-effacer").exists()
        kind, _ = services.resolve_slug("jean-a-effacer")
        assert kind == "erased"
        assert not services.is_slug_available("jean-a-effacer")

    def test_suspend_removes_indexability(self, complete_profile):
        services.suspend_profile(complete_profile, "arnaque")
        complete_profile.refresh_from_db()
        assert not complete_profile.is_indexable

    def test_user_can_own_several_profiles(self):
        user = UserFactory()
        services.create_profile(user, "Atelier Talla")
        services.create_profile(user, "Talla Consulting")
        assert user.profiles.count() == 2
