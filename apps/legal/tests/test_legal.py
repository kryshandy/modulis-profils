import json
from datetime import timedelta

import pytest
from django.core import checks
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.legal.conf import LEGAL_VERSION, missing_identity_fields
from apps.legal.services import needs_acceptance, purge_expired_records, record_acceptance
from apps.moderation.models import Report
from apps.platform.models import AuditLog
from tests.factories import ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db


# --- Public pages -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "needle"),
    [
        ("legal:terms", "Conditions générales d'utilisation"),
        ("legal:privacy", "Politique de confidentialité"),
        ("legal:notice", "Mentions légales"),
    ],
)
def test_legal_pages_render_indexable_with_version(client, name, needle):
    response = client.get(reverse(name))
    assert response.status_code == 200
    body = response.content.decode()
    assert needle in body
    assert '<meta name="robots" content="index, follow">' in body
    assert "hello@modulis.tech" in body
    assert LEGAL_VERSION in body
    assert 'aria-current="page"' in body


def test_legal_pages_set_no_cookie(client):
    response = client.get(reverse("legal:terms"))
    assert not response.cookies


def test_legal_urls_are_reserved_slugs():
    from apps.profiles.services import SYSTEM_RESERVED_SLUGS

    for slug in ("cgu", "confidentialite", "mentions-legales"):
        assert slug in SYSTEM_RESERVED_SLUGS


@override_settings(LEGAL_RCCM="RC/DLA/2026/B/1234", LEGAL_NIU="M012600001234X", LEGAL_ADDRESS="Akwa, Douala")
def test_notice_shows_identity_when_configured(client):
    body = client.get(reverse("legal:notice")).content.decode()
    assert "RC/DLA/2026/B/1234" in body
    assert "M012600001234X" in body
    assert "Akwa, Douala" in body


@override_settings(LEGAL_RCCM="")
def test_notice_hides_empty_fields(client):
    body = client.get(reverse("legal:notice")).content.decode()
    assert "RCCM" not in body


def test_footer_and_pro_site_link_to_legal_pages(client):
    profile = ProfileFactory()
    home = client.get("/").content.decode()
    assert reverse("legal:terms") in home and reverse("legal:privacy") in home and reverse("legal:notice") in home
    page = client.get(f"/{profile.slug}").content.decode()
    assert "/mentions-legales" in page


def test_login_page_states_acceptance(client):
    body = client.get(reverse("dashboard:login")).content.decode()
    assert 'href="/cgu"' in body and 'href="/confidentialite"' in body


# --- System check -------------------------------------------------------------------------------


@override_settings(DEBUG=False, LEGAL_RCCM="", LEGAL_HOST_NAME="")
def test_system_check_warns_on_missing_identity_in_production():
    from apps.legal.checks import legal_identity

    warnings = legal_identity(None)
    assert [w.id for w in warnings] == ["legal.W001"]
    assert isinstance(warnings[0], checks.Warning)
    assert "LEGAL_RCCM" in missing_identity_fields()


@override_settings(DEBUG=True, LEGAL_RCCM="")
def test_system_check_silent_in_development():
    from apps.legal.checks import legal_identity

    assert legal_identity(None) == []


# --- Acceptance ---------------------------------------------------------------------------------


def test_needs_acceptance_rules():
    assert needs_acceptance(UserFactory(terms_version="")) is True
    assert needs_acceptance(UserFactory(terms_version="2000-01-01")) is True
    assert needs_acceptance(UserFactory()) is False
    assert needs_acceptance(UserFactory(terms_version="", is_staff=True)) is False


def test_pro_space_locked_until_current_version_accepted(client):
    user = UserFactory(terms_version="2000-01-01")
    ProfileFactory(user=user)
    client.force_login(user)
    response = client.get(reverse("dashboard:settings"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("legal:accept"))
    assert "next=%2Fespace%2Fparametres" in response["Location"]

    page = client.get(response["Location"])
    assert page.status_code == 200
    assert "Nos conditions ont évolué" in page.content.decode()

    refused = client.post(reverse("legal:accept"), {"next": "/espace/parametres"})
    assert refused.status_code == 400
    user.refresh_from_db()
    assert user.terms_version == "2000-01-01"

    accepted = client.post(reverse("legal:accept"), {"accept": "1", "next": "/espace/parametres"})
    assert accepted["Location"] == "/espace/parametres"
    user.refresh_from_db()
    assert user.terms_version == LEGAL_VERSION and user.terms_accepted_at is not None
    assert client.get(reverse("dashboard:settings")).status_code == 200


def test_accept_rejects_external_next(client):
    user = UserFactory(terms_version="")
    client.force_login(user)
    response = client.post(reverse("legal:accept"), {"accept": "1", "next": "https://evil.example/"})
    assert response["Location"] == "/espace/"


def test_htmx_requests_get_hx_redirect(client):
    user = UserFactory(terms_version="")
    ProfileFactory(user=user)
    client.force_login(user)
    response = client.get(reverse("dashboard:stats"), HTTP_HX_REQUEST="true")
    assert response.status_code == 204
    assert response["HX-Redirect"].startswith(reverse("legal:accept"))


def test_logout_and_export_stay_open_without_acceptance(client):
    user = UserFactory(terms_version="")
    ProfileFactory(user=user)
    client.force_login(user)
    assert client.get(reverse("dashboard:data_export")).status_code == 200
    assert client.post(reverse("dashboard:logout")).status_code == 302


def test_accept_requires_login(client):
    response = client.get(reverse("legal:accept"))
    assert response.status_code == 302
    assert reverse("dashboard:login") in response["Location"]


def test_public_pages_never_gated(client):
    profile = ProfileFactory(user=UserFactory(terms_version=""))
    client.force_login(profile.user)
    assert client.get(f"/{profile.slug}").status_code == 200


def test_record_acceptance():
    user = UserFactory(terms_version="")
    record_acceptance(user)
    user.refresh_from_db()
    assert user.terms_version == LEGAL_VERSION


def test_first_login_records_acceptance(client, sms_outbox, django_capture_on_commit_callbacks):
    from apps.dashboard.tests.helpers import code_from

    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("dashboard:login"), {"phone": "690 00 00 77"})
    client.post(reverse("dashboard:verify"), {"action": "verify", "code": code_from(sms_outbox)})
    user = User.objects.get(phone="+237690000077")
    assert user.terms_version == LEGAL_VERSION
    assert user.terms_accepted_at is not None


def test_login_does_not_silently_accept_a_new_version(client, sms_outbox, django_capture_on_commit_callbacks):
    from apps.dashboard.tests.helpers import code_from

    user = UserFactory(phone="+237690000078", terms_version="2000-01-01")
    ProfileFactory(user=user)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("dashboard:login"), {"phone": "690 00 00 78"})
    client.post(reverse("dashboard:verify"), {"action": "verify", "code": code_from(sms_outbox)})
    user.refresh_from_db()
    assert user.terms_version == "2000-01-01"  # the explicit screen is required
    assert client.get(reverse("dashboard:home"))["Location"].startswith(reverse("legal:accept"))


# --- Data export --------------------------------------------------------------------------------


def test_data_export_contains_account_and_pages(logged_client, profile):
    client = logged_client
    profile.services.create(title="Débouchage", price_label="5 000 FCFA")
    profile.links.create(kind="facebook", url="https://facebook.com/exemple")
    response = client.get(reverse("dashboard:data_export"))
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith('attachment; filename="modulis-mes-donnees-')
    assert response["Cache-Control"] == "no-store"
    data = json.loads(response.content)
    assert data["format"] == "modulis-profils/export-v1"
    assert data["compte"]["phone"] == profile.user.phone
    assert "password" not in data["compte"] and "is_superuser" not in data["compte"]
    page = data["pages"][0]
    assert page["page"]["slug"] == profile.slug
    assert page["prestations"][0]["title"] == "Débouchage"
    assert page["liens"][0]["url"] == "https://facebook.com/exemple"
    assert AuditLog.objects.filter(action="data_export").exists()


def test_data_export_excludes_other_users(logged_client):
    client = logged_client
    other = ProfileFactory(display_name="Quelqu'un d'autre")
    data = json.loads(client.get(reverse("dashboard:data_export")).content)
    assert all(p["page"]["slug"] != other.slug for p in data["pages"])


def test_data_export_requires_login(client):
    assert client.get(reverse("dashboard:data_export")).status_code == 302


def test_settings_offers_data_download(logged_client):
    client = logged_client
    body = client.get(reverse("dashboard:settings")).content.decode()
    assert reverse("dashboard:data_export") in body


# --- Retention ----------------------------------------------------------------------------------


def test_purge_expired_records_respects_retention():
    profile = ProfileFactory()
    old = timezone.now() - timedelta(days=3 * 365 + 5)
    recent_log = AuditLog.objects.create(action="recent")
    old_log = AuditLog.objects.create(action="old")
    AuditLog.objects.filter(pk=old_log.pk).update(created_at=old)
    open_old = Report.objects.create(profile=profile, reason="spam")
    handled_old = Report.objects.create(profile=profile, reason="spam", status=Report.Status.DISMISSED)
    Report.objects.filter(pk__in=[open_old.pk, handled_old.pk]).update(created_at=old)

    result = purge_expired_records()

    assert result == {"audit_log": 1, "reports": 1}
    assert AuditLog.objects.filter(pk=recent_log.pk).exists()
    assert Report.objects.filter(pk=open_old.pk).exists()  # still to be handled: never purged
    assert not Report.objects.filter(pk=handled_old.pk).exists()
