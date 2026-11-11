import sys
import time
import types

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.platform import health, services
from apps.platform.forms import SECTIONS_BY_CODE
from apps.platform.models import AuditLog, SiteSettings
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/gestion/centre-de-controle/"

ALL_ON = {
    "auth-otp_whatsapp_enabled": "on",
    "auth-otp_firebase_sms_enabled": "on",
    "auth-otp_default_channel": "whatsapp",
    "auth-login_enabled": "on",
    "auth-signups_enabled": "on",
}


@pytest.fixture
def manager(db):
    user = UserFactory(is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="manage_platform"))
    return user


@pytest.fixture
def manager_client(client, manager):
    client.force_login(manager)
    return client


@pytest.fixture
def no_registry(monkeypatch):
    monkeypatch.setitem(sys.modules, "apps.accounts.otp.registry", None)  # import fails


def test_url_is_mounted_under_admin():
    assert reverse("admin:platform_control_center") == URL


class TestPermissions:
    def test_anonymous_redirected_to_admin_login(self, client):
        response = client.get(URL)
        assert response.status_code == 302
        assert "/gestion/login/" in response["Location"]

    def test_staff_without_permission_gets_403(self, client):
        client.force_login(UserFactory(is_staff=True))
        assert client.get(URL).status_code == 403
        assert client.post(URL, {"section": "cards"}).status_code == 403
        assert client.get(reverse("admin:platform_maintenance_preview")).status_code == 403

    def test_staff_without_permission_cannot_toggle(self, client):
        client.force_login(UserFactory(is_staff=True))
        client.post(URL, {"section": "cards"})
        assert services.feature("card_activation") is True

    def test_manager_and_superuser_allowed(self, manager_client, client, admin_user, no_registry):
        assert manager_client.get(URL).status_code == 200
        client.force_login(admin_user)
        assert client.get(URL).status_code == 200

    def test_settings_changelist_redirects_to_control_center(self, manager_client):
        response = manager_client.get(reverse("admin:platform_settings_sitesettings_changelist"))
        assert response.status_code == 302
        assert response["Location"] == URL


class TestPage:
    def test_renders_every_section_and_unknown_configuration(self, manager_client, no_registry):
        content = manager_client.get(URL).content.decode()
        for anchor in ("auth", "cards", "pages", "directory", "reports", "seo", "maintenance", "announcement"):
            assert f'id="section-{anchor}"' in content
        assert "configuration inconnue" in content
        assert "Notifier les moteurs maintenant" in content
        assert 'id="section-health"' in content

    def test_shows_registry_configuration(self, manager_client, monkeypatch):
        fake = types.ModuleType("apps.accounts.otp.registry")
        fake.channel_status = lambda: [
            {"code": "whatsapp", "label": "WhatsApp", "enabled": True, "configured": True, "kind": "whatsapp"},
            {"code": "firebase_sms", "label": "SMS", "enabled": True, "configured": False, "kind": "sms"},
        ]
        monkeypatch.setitem(sys.modules, "apps.accounts.otp.registry", fake)
        response = manager_client.get(URL)
        rows = {row["code"]: row for row in response.context["otp_channels"]}
        assert rows["whatsapp"]["configured"] is True
        assert rows["firebase_sms"]["configured"] is False
        assert rows["sms_gateway"]["configured"] is None

    def test_registry_crash_never_breaks_the_page(self, manager_client, monkeypatch):
        fake = types.ModuleType("apps.accounts.otp.registry")

        def boom():
            raise RuntimeError("provider down")

        fake.channel_status = boom
        monkeypatch.setitem(sys.modules, "apps.accounts.otp.registry", fake)
        assert manager_client.get(URL).status_code == 200

    def test_maintenance_preview(self, manager_client):
        response = manager_client.get(reverse("admin:platform_maintenance_preview"))
        assert response.status_code == 200
        assert "Aperçu réservé" in response.content.decode()


class TestToggles:
    @pytest.mark.parametrize(
        ("section", "field", "feature"),
        [
            ("cards", "card_activation_enabled", "card_activation"),
            ("pages", "page_creation_enabled", "page_creation"),
            ("pages", "themes_enabled", "themes"),
            ("directory", "directory_enabled", "directory"),
            ("reports", "reports_enabled", "reports"),
            ("seo", "indexing_notifications_enabled", "indexing"),
            ("seo", "instant_publish_enabled", "instant_publish"),
        ],
    )
    def test_switch_off_persists_audits_and_invalidates(self, manager_client, manager, section, field, feature):
        assert services.feature(feature) is True  # cached now
        others = {f"{section}-{name}": "on" for name in SECTIONS_BY_CODE[section].fields if name != field}
        response = manager_client.post(URL, {"section": section, **others})
        assert response.status_code == 302
        assert services.feature(feature) is False  # cache invalidated: visible at once
        assert getattr(SiteSettings.objects.get(pk=1), field) is False
        log = AuditLog.objects.get(action="settings.update", target=section)
        assert log.actor == manager
        assert field in log.details["changes"]
        assert SiteSettings.objects.get(pk=1).updated_by == manager

    def test_switch_back_on(self, manager_client):
        services.update_settings(None, "cards", {"card_activation_enabled": False})
        manager_client.post(URL, {"section": "cards", "cards-card_activation_enabled": "on"})
        assert services.feature("card_activation") is True

    def test_no_change_no_audit(self, manager_client):
        manager_client.post(URL, {"section": "cards", "cards-card_activation_enabled": "on"})
        assert not AuditLog.objects.exists()

    def test_announcement(self, manager_client):
        manager_client.post(URL, {"section": "announcement", "announcement-announcement": "Nouveautés !"})
        assert services.get_settings().announcement == "Nouveautés !"

    def test_unknown_section(self, manager_client):
        response = manager_client.post(URL, {"section": "nope"})
        assert response.status_code == 302
        assert not AuditLog.objects.exists()

    def test_otp_channel_switch_and_default(self, manager_client):
        data = {**ALL_ON, "section": "auth", "auth-otp_sms_gateway_enabled": "on"}
        data["auth-otp_default_channel"] = "sms_gateway"
        data.pop("auth-otp_whatsapp_enabled")
        manager_client.post(URL, data)
        assert services.enabled_otp_channels() == ["sms_gateway", "firebase_sms"]

    def test_default_channel_must_be_enabled(self, manager_client):
        data = {**ALL_ON, "section": "auth"}
        data.pop("auth-otp_whatsapp_enabled")  # default stays whatsapp
        response = manager_client.post(URL, data)
        assert response.status_code == 200
        assert response.context["sections"][0][1].errors
        assert SiteSettings.objects.get(pk=1).otp_whatsapp_enabled is True

    def test_all_channels_off_warns(self, manager_client):
        data = {"section": "auth", "auth-otp_default_channel": "whatsapp", "auth-login_enabled": "on"}
        data["auth-signups_enabled"] = "on"
        response = manager_client.post(URL, data, follow=True)
        assert services.enabled_otp_channels() == []
        assert "Aucun canal OTP" in response.content.decode()


class TestDangerousChanges:
    def test_maintenance_requires_confirmation(self, manager_client):
        data = {
            "section": "maintenance",
            "maintenance-maintenance_mode": "on",
            "maintenance-maintenance_message": "Hop",
        }
        response = manager_client.post(URL, data)
        assert response.status_code == 200
        assert "admin/platform/confirm.html" in [t.name for t in response.templates]
        assert services.feature("maintenance") is False
        assert not AuditLog.objects.exists()

        response = manager_client.post(URL, {**data, "confirm": "1"})
        assert response.status_code == 302
        assert services.feature("maintenance") is True
        assert services.get_settings().maintenance_message == "Hop"
        assert AuditLog.objects.filter(target="maintenance").count() == 1

    @pytest.mark.parametrize("field", ["login_enabled", "signups_enabled"])
    def test_closing_login_or_signups_requires_confirmation(self, manager_client, field):
        data = {**ALL_ON, "section": "auth"}
        data.pop(f"auth-{field}")
        manager_client.post(URL, data)
        assert getattr(SiteSettings.objects.get(pk=1), field) is True
        manager_client.post(URL, {**data, "confirm": "1"})
        assert getattr(SiteSettings.objects.get(pk=1), field) is False

    def test_turning_maintenance_off_needs_no_confirmation(self, manager_client):
        services.update_settings(None, "maintenance", {"maintenance_mode": True})
        response = manager_client.post(URL, {"section": "maintenance", "maintenance-maintenance_message": "x"})
        assert response.status_code == 302
        assert services.feature("maintenance") is False


class TestSeoFlush:
    def test_flush_button_runs_task_and_audits(self, manager_client, monkeypatch):
        from apps.seo import notifier

        calls = []
        monkeypatch.setattr(notifier, "flush_queue", lambda: calls.append(1) or 0)
        response = manager_client.post(URL, {"section": "seo_flush"})
        assert response.status_code == 302
        assert calls == [1]
        assert AuditLog.objects.filter(action="seo.flush").exists()


class TestHealth:
    def test_heartbeat_task_records_timestamp(self):
        from apps.platform.tasks import huey_heartbeat

        assert services.heartbeat_age() is None
        huey_heartbeat()
        assert services.heartbeat_age() < 5
        check = next(c for c in health.report() if "Huey" in c.label)
        assert check.state == health.OK

    def test_heartbeat_late(self):
        from django.core.cache import cache

        cache.set(services.HEARTBEAT_KEY, time.time() - 10 * 60, 60)
        check = next(c for c in health.report() if "Huey" in c.label)
        assert check.state == health.ERROR
        assert check.value == "en retard"

    def test_report_contents(self, settings):
        settings.DEBUG = True
        labels = [c.label for c in health.report()]
        assert "Base de données" in labels
        assert "Cache" in labels
        assert "Mode DEBUG" in labels
        assert all(c.state == health.OK for c in health.report() if c.label in ("Base de données", "Cache"))
