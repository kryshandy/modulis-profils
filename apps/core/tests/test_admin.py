import csv
import io

import pytest
from django.contrib import admin
from django.template import Context, Template
from django.urls import reverse

from apps.accounts.models import OTPChallenge, User
from apps.analytics.models import DailyStat, Event
from apps.billing.models import Payment, Plan, Subscription
from apps.cards import services as card_services
from apps.cards.models import Card, CardActivationAttempt, CardBatch
from apps.core.admin_dashboard import get_kpis
from apps.core.models import City, Trade
from apps.moderation.models import Report
from apps.profiles.models import Profile, ProfileService, SlugRegistry
from apps.seo.models import IndexingLog, IndexingQueue
from tests.factories import CardFactory, ProfileFactory, cameroon

pytestmark = pytest.mark.django_db


@pytest.fixture
def sample_data(admin_user):
    profile = ProfileFactory()
    ProfileService.objects.create(profile=profile, title="Réparation")
    profile.links.create(kind="website", url="https://exemple.test")
    card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
    CardActivationAttempt.objects.create(card=card, ip_hash="x", success=True)
    Event.objects.create(profile=profile, card=card, kind="scan")
    DailyStat.objects.create(profile=profile, day="2026-11-01", kind="visit", total=3)
    Report.objects.create(profile=profile, reason="spam")
    plan = Plan.objects.get(code="essentiel")
    sub = Subscription.objects.create(
        profile=profile, plan=plan, ends_at="2027-11-01T00:00:00Z", starts_at="2026-11-01T00:00:00Z"
    )
    Payment.objects.create(
        reference="PAY-1", provider="manual", profile=profile, plan=plan, amount=12000, subscription=sub
    )
    IndexingQueue.objects.create(url="https://profils.test/x")
    IndexingLog.objects.create(provider="indexnow", success=False, error="HTTP 500", status_code=500)
    OTPChallenge.objects.create(phone="+237690000001", purpose="login", code_hmac="x", expires_at="2030-01-01T00:00Z")
    return profile


def _registered():
    return [(model, model_admin) for model, model_admin in admin.site._registry.items()]


def test_every_model_of_the_project_is_registered():
    from django.apps import apps

    inline_only = {
        "profiles.ProfileLink",
        "profiles.ProfileService",
        "profiles.ProfileMedia",
        "blocks.BlockImage",
    }  # inlines
    missing = [
        f"{m._meta.app_label}.{m.__name__}"
        for m in apps.get_models()
        if m.__module__.startswith("apps.") and m not in admin.site._registry
    ]
    missing = [m for m in missing if m not in inline_only]
    assert not missing, missing


def test_admin_index_with_kpis(admin_client, sample_data):
    response = admin_client.get(reverse("admin:index"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "mp-kpis" in content and "Signalements à traiter" in content
    assert "HTTP 500" in content  # last indexing failure
    assert "app-profiles" in content  # app list kept


@pytest.mark.parametrize("model_admin_pair", _registered(), ids=lambda p: p[0]._meta.label)
def test_changelist_add_change_pages_load(admin_client, sample_data, model_admin_pair):
    model, _model_admin = model_admin_pair
    info = model._meta.app_label, model._meta.model_name
    response = admin_client.get(reverse("admin:{}_{}_changelist".format(*info)), follow=True)  # SiteSettings: 302
    assert response.status_code == 200
    response = admin_client.get(reverse("admin:{}_{}_changelist".format(*info)), {"q": "test"}, follow=True)
    assert response.status_code == 200
    add = admin_client.get(reverse("admin:{}_{}_add".format(*info)))
    assert add.status_code in (200, 403)
    obj = model._default_manager.first()
    if obj is not None:
        response = admin_client.get(reverse("admin:{}_{}_change".format(*info), args=[obj.pk]), follow=True)
        assert response.status_code == 200


def test_kpis_values(sample_data):
    CardFactory()  # stock
    kpis = get_kpis()
    assert kpis["profiles_total"] == 1
    assert kpis["profiles_last_7"] == 1
    cards = {row["status"]: row["count"] for row in kpis["cards"]}
    assert cards["active"] == 1 and cards["stock"] == 1 and cards["sold"] == 0
    assert kpis["open_reports"] == 1
    assert kpis["subscriptions"] == [{"plan": "Essentiel", "count": 1}]
    assert len(kpis["indexing_failures"]) == 1


def test_kpi_tag_renders(sample_data):
    html = Template("{% load admin_kpis %}{% admin_kpis %}").render(Context({}))
    assert "mp-kpis" in html and "Pages pros" in html


# --- Cards -----------------------------------------------------------------------------------


class TestCardAdmin:
    def test_generate_batch_returns_csv_once(self, admin_client, admin_user, settings):
        url = reverse("admin:cards_cardbatch_generate")
        assert admin_client.get(url).status_code == 200
        response = admin_client.post(url, {"reference": "LOT-2026-01", "quantity": 5, "kind": "standard"})
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert 'filename="lot-LOT-2026-01.csv"' in response["Content-Disposition"]
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        assert rows[0] == ["public_code", "url", "activation_code"]
        assert len(rows) == 6
        batch = CardBatch.objects.get(reference="LOT-2026-01")
        assert batch.exported_at is not None and batch.created_by == admin_user and batch.cards.count() == 5
        for public, link, activation in rows[1:]:
            assert link == f"{settings.SITE_URL}/c/{public}"
            card = Card.objects.get(public_code=public)
            assert activation not in card.activation_code_hash
            assert card.activation_code_hash == card_services.hash_activation_code(public, activation)
        # Same reference refused.
        response = admin_client.post(url, {"reference": "lot-2026-01", "quantity": 1, "kind": "standard"})
        assert response.status_code == 200 and "existe déjà" in response.content.decode()

    def test_generate_link_on_changelist(self, admin_client):
        response = admin_client.get(reverse("admin:cards_cardbatch_changelist"))
        assert reverse("admin:cards_cardbatch_generate") in response.content.decode()

    def test_disable_and_sell_actions(self, admin_client):
        active = CardFactory(status=Card.Status.ACTIVE, profile=ProfileFactory())
        stock = CardFactory()
        changelist = reverse("admin:cards_card_changelist")
        admin_client.post(changelist, {"action": "disable_lost", "_selected_action": [active.pk]})
        admin_client.post(changelist, {"action": "mark_sold", "_selected_action": [stock.pk]})
        active.refresh_from_db()
        stock.refresh_from_db()
        assert active.status == Card.Status.DISABLED and active.disabled_reason == "lost"
        assert stock.status == Card.Status.SOLD

    def test_search_by_profile(self, admin_client):
        profile = ProfileFactory(slug="carte-cherchee")
        card = CardFactory(status=Card.Status.ACTIVE, profile=profile)
        response = admin_client.get(reverse("admin:cards_card_changelist"), {"q": "carte-cherchee"})
        assert card.public_code in response.content.decode()


# --- Profiles --------------------------------------------------------------------------------


class TestProfileAdmin:
    def _action(self, client, action, profiles):
        return client.post(
            reverse("admin:profiles_profile_changelist"),
            {"action": action, "_selected_action": [p.pk for p in profiles]},
        )

    def test_changelist_columns(self, admin_client, sample_data):
        response = admin_client.get(reverse("admin:profiles_profile_changelist"))
        content = response.content.decode()
        assert f'href="/{sample_data.slug}"' in content
        assert sample_data.user.phone in content
        assert "essentiel" in content

    def test_search_by_phone(self, admin_client):
        profile = ProfileFactory()
        response = admin_client.get(reverse("admin:profiles_profile_changelist"), {"q": profile.user.phone})
        assert profile.slug in response.content.decode()

    def test_plan_filter(self, admin_client, sample_data):
        free = ProfileFactory()
        response = admin_client.get(reverse("admin:profiles_profile_changelist"), {"plan": "free"})
        content = response.content.decode()
        assert free.slug in content and f"/{sample_data.slug}<" not in content

    def test_verify_suspend_reactivate(self, admin_client):
        profile = ProfileFactory()
        self._action(admin_client, "verify", [profile])
        profile.refresh_from_db()
        assert profile.verified_at is not None
        self._action(admin_client, "unverify", [profile])
        self._action(admin_client, "suspend", [profile])
        profile.refresh_from_db()
        assert profile.verified_at is None and profile.status == Profile.Status.SUSPENDED
        self._action(admin_client, "reactivate", [profile])
        profile.refresh_from_db()
        assert profile.status == Profile.Status.ACTIVE

    def test_grant_plans(self, admin_client, admin_user):
        from apps.billing.services import current_plan_code

        profile = ProfileFactory()
        self._action(admin_client, "grant_pro", [profile])
        sub = Subscription.objects.get(profile=profile)
        assert current_plan_code(profile) == "pro"
        assert sub.source == Subscription.Source.MANUAL and sub.created_by == admin_user
        assert (sub.ends_at - sub.starts_at).days == 365
        self._action(admin_client, "grant_essentiel", [profile])
        assert Subscription.objects.filter(profile=profile).count() == 2

    def test_recompute_seo_and_queue_indexing(self, admin_client, complete_profile):
        Profile.objects.filter(pk=complete_profile.pk).update(completeness_score=0, is_indexable=False)
        self._action(admin_client, "recompute_seo", [complete_profile])
        complete_profile.refresh_from_db()
        assert complete_profile.is_indexable and complete_profile.completeness_score >= 70
        IndexingQueue.objects.all().delete()
        self._action(admin_client, "queue_indexing", [complete_profile])
        assert IndexingQueue.objects.filter(url=complete_profile.absolute_url).exists()

    def test_edit_recomputes_seo_and_keeps_slug(self, admin_client):
        profile = ProfileFactory()
        url = reverse("admin:profiles_profile_change", args=[profile.pk])
        page = admin_client.get(url)
        assert reverse("admin:profiles_profile_change_slug", args=[profile.pk]) in page.content.decode()
        form = page.context["adminform"].form
        data = {k: v for k, v in form.initial.items() if v is not None and k in form.fields}
        data.update(
            {
                "user": profile.user.pk,
                "display_name": "Nouveau Nom",
                "bio": "x" * 130,
                "slug": "tentative-pirate",
                "trade": profile.trade.pk,
                "city": profile.city.pk,
            }
        )
        for prefix in ("services", "links", "media", "cards", "subscriptions"):
            data.update({f"{prefix}-TOTAL_FORMS": 0, f"{prefix}-INITIAL_FORMS": 0})
        response = admin_client.post(url, data)
        assert response.status_code == 302, response.context["adminform"].form.errors
        profile.refresh_from_db()
        assert profile.display_name == "Nouveau Nom"
        assert profile.slug.startswith("pro-test-")  # slug not editable through the form
        assert profile.completeness_score > 0

    def test_change_slug_view(self, admin_client):
        profile = ProfileFactory()
        old = profile.slug
        url = reverse("admin:profiles_profile_change_slug", args=[profile.pk])
        assert admin_client.get(url).status_code == 200
        response = admin_client.post(url, {"new_slug": "c"})  # reserved
        assert response.status_code == 200
        response = admin_client.post(url, {"new_slug": "nouvelle-adresse-pro"})
        assert response.status_code == 302
        profile.refresh_from_db()
        assert profile.slug == "nouvelle-adresse-pro"
        assert SlugRegistry.objects.get(slug=old).kind == SlugRegistry.Kind.OLD

    def test_no_add_no_delete(self, admin_client):
        assert admin_client.get(reverse("admin:profiles_profile_add")).status_code == 403


# --- Reference data --------------------------------------------------------------------------


class TestReferenceDataAdmin:
    def test_city_slug_owned_by_profile_refused(self, admin_client):
        ProfileFactory(slug="nouvelle-ville")
        response = admin_client.post(
            reverse("admin:core_city_add"),
            {"country": cameroon().pk, "name": "Nouvelle Ville", "slug": "nouvelle-ville", "is_active": "on"},
        )
        assert response.status_code == 200
        assert "appartient déjà à une page pro" in response.content.decode()
        assert not City.objects.filter(slug="nouvelle-ville").exists()

    def test_city_creation_reserves_slug(self, admin_client):
        response = admin_client.post(
            reverse("admin:core_city_add"),
            {"country": cameroon().pk, "name": "Obala", "slug": "obala", "is_active": "on"},
        )
        assert response.status_code == 302
        assert SlugRegistry.objects.get(slug="obala").kind == SlugRegistry.Kind.RESERVED

    def test_trade_plural_slug_owned_by_profile_refused(self, admin_client):
        ProfileFactory(slug="soudeurs-pro")
        response = admin_client.post(
            reverse("admin:core_trade_add"),
            {
                "name": "Vitrier test",
                "slug": "vitrier-test",
                "plural_slug": "soudeurs-pro",
                "plural_name": "Soudeurs",
                "segment": "craft",
                "schema_type": "LocalBusiness",
                "is_active": "on",
            },
        )
        assert response.status_code == 200
        assert not Trade.objects.filter(slug="vitrier-test").exists()


# --- Users -----------------------------------------------------------------------------------


class TestUserAdmin:
    def test_add_staff_account(self, admin_client):
        response = admin_client.post(
            reverse("admin:accounts_user_add"),
            {
                "phone": "690 11 22 33",
                "full_name": "Agent Support",
                "email": "",
                "password1": "un-mot-de-passe-solide-42",
                "password2": "un-mot-de-passe-solide-42",
            },
        )
        assert response.status_code == 302, response.context["adminform"].form.errors
        user = User.objects.get(phone="+237690112233")
        assert user.is_staff and user.check_password("un-mot-de-passe-solide-42")

    def test_duplicate_phone_refused(self, admin_client):
        ProfileFactory(user__phone="+237690112244")
        response = admin_client.post(
            reverse("admin:accounts_user_add"),
            {"phone": "690112244", "password1": "un-mot-de-passe-solide-42", "password2": "un-mot-de-passe-solide-42"},
        )
        assert response.status_code == 200
        assert User.objects.filter(phone="+237690112244").count() == 1

    def test_user_change_page_shows_profiles(self, admin_client):
        profile = ProfileFactory()
        response = admin_client.get(reverse("admin:accounts_user_change", args=[profile.user.pk]))
        assert response.status_code == 200
        assert f"/{profile.slug}" in response.content.decode()

    def test_search_by_phone(self, admin_client):
        profile = ProfileFactory()
        response = admin_client.get(reverse("admin:accounts_user_changelist"), {"q": profile.user.phone})
        assert profile.user.phone in response.content.decode()
