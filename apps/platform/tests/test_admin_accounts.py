"""Account & site management from the admin: user actions, blocked phones, audit log, profiles, index."""

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.platform import services
from apps.platform.models import AuditLog, BlockedPhone
from apps.profiles.models import Profile
from tests.factories import ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db

USERS = "/gestion/accounts/user/"
PROFILES = "/gestion/profiles/profile/"


def _sessions_of(user) -> int:
    return sum(1 for s in Session.objects.all() if s.get_decoded().get("_auth_user_id") == str(user.pk))


def _login_elsewhere(user, n=2):
    for _ in range(n):
        Client().force_login(user)


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def _act(client, url, action, objs):
    return client.post(url, {"action": action, ACTION_CHECKBOX_NAME: [o.pk for o in objs]}, follow=True)


class TestServices:
    def test_terminate_sessions_only_targets_user(self):
        a, b = UserFactory(), UserFactory()
        _login_elsewhere(a, 2)
        _login_elsewhere(b, 1)
        assert services.terminate_sessions(a) == 2
        assert _sessions_of(a) == 0
        assert _sessions_of(b) == 1

    def test_block_phone_deactivates_and_logs_out(self, admin_user):
        user = UserFactory()
        _login_elsewhere(user)
        services.block_phone(user.phone, reason="fraude", actor=admin_user)
        user.refresh_from_db()
        assert not user.is_active
        assert _sessions_of(user) == 0
        assert services.is_phone_blocked(user.phone)
        assert AuditLog.objects.filter(action="phone.block", target=user.phone, actor=admin_user).exists()

    def test_unblock_reactivates(self, admin_user):
        user = UserFactory()
        services.block_phone(user.phone, reason="x", actor=admin_user)
        assert services.unblock_phone(user.phone, actor=admin_user)
        user.refresh_from_db()
        assert user.is_active
        assert not services.is_phone_blocked(user.phone)


class TestUserActions:
    def test_changelist_shows_blocked_badge_and_filter(self, admin_client):
        user = UserFactory()
        BlockedPhone.objects.create(phone=user.phone, reason="x")
        response = admin_client.get(USERS + "?blocked=yes")
        assert response.status_code == 200
        assert user.phone in response.content.decode()
        assert list(response.context["cl"].result_list) == [user]

    def test_deactivate_deletes_sessions(self, admin_client, admin_user):
        user = UserFactory()
        _login_elsewhere(user)
        _act(admin_client, USERS, "deactivate_accounts", [user])
        user.refresh_from_db()
        assert not user.is_active
        assert _sessions_of(user) == 0
        assert AuditLog.objects.filter(action="user.deactivate", target=user.phone, actor=admin_user).exists()

    def test_reactivate(self, admin_client):
        user = UserFactory(is_active=False)
        _act(admin_client, USERS, "reactivate_accounts", [user])
        user.refresh_from_db()
        assert user.is_active

    def test_logout_everywhere_keeps_account_active(self, admin_client):
        user = UserFactory()
        _login_elsewhere(user, 3)
        _act(admin_client, USERS, "logout_everywhere", [user])
        user.refresh_from_db()
        assert user.is_active
        assert _sessions_of(user) == 0
        assert AuditLog.objects.get(action="user.logout_everywhere").details["sessions"] == 3

    def test_block_and_unblock(self, admin_client):
        user = UserFactory()
        _act(admin_client, USERS, "block_phones", [user])
        assert BlockedPhone.objects.filter(phone=user.phone).exists()
        user.refresh_from_db()
        assert not user.is_active
        _act(admin_client, USERS, "unblock_phones", [user])
        assert not BlockedPhone.objects.filter(phone=user.phone).exists()

    def test_admin_never_acts_on_itself(self, admin_client, admin_user):
        _act(admin_client, USERS, "deactivate_accounts", [admin_user])
        admin_user.refresh_from_db()
        assert admin_user.is_active

    def test_non_superuser_cannot_touch_superuser(self, client, admin_user):
        staff = UserFactory(is_staff=True)
        staff.user_permissions.add(
            *Permission.objects.filter(codename__in=["view_user", "change_user", "add_blockedphone"])
        )
        client.force_login(staff)
        _act(client, USERS, "deactivate_accounts", [admin_user])
        _act(client, USERS, "block_phones", [admin_user])
        admin_user.refresh_from_db()
        assert admin_user.is_active
        assert not BlockedPhone.objects.exists()
        # nor through the change form
        assert (
            client.get(reverse("admin:accounts_user_change", args=[admin_user.pk])).context["has_change_permission"]
            is False
        )

    def test_block_needs_blockedphone_permission(self, client):
        staff = UserFactory(is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_user", "change_user"]))
        client.force_login(staff)
        target = UserFactory()
        response = client.get(USERS)
        assert "block_phones" not in response.content.decode()
        _act(client, USERS, "block_phones", [target])
        assert not BlockedPhone.objects.exists()

    def test_deactivating_from_change_form_logs_out(self, admin_user, rf):
        from django.contrib import admin

        user = UserFactory()
        _login_elsewhere(user)
        user.is_active = False
        request = rf.post("/")
        request.user = admin_user
        form = type("F", (), {"changed_data": ["is_active"]})()
        admin.site._registry[User].save_model(request, user, form, change=True)
        assert _sessions_of(user) == 0
        assert AuditLog.objects.filter(action="user.deactivate", target=user.phone).exists()


class TestBlockedPhoneAndAuditAdmin:
    def test_add_blocked_phone_normalises_and_deactivates(self, admin_client, admin_user):
        user = UserFactory(phone="+237677001122")
        response = admin_client.post(
            "/gestion/platform_settings/blockedphone/add/", {"phone": "677 00 11 22", "reason": "arnaque"}
        )
        assert response.status_code == 302
        blocked = BlockedPhone.objects.get()
        assert blocked.phone == "+237677001122"
        assert blocked.created_by == admin_user
        user.refresh_from_db()
        assert not user.is_active

    def test_audit_log_is_read_only(self, admin_client):
        services.audit(None, "x.test", "cible")
        assert admin_client.get("/gestion/platform_settings/auditlog/").status_code == 200
        assert admin_client.get("/gestion/platform_settings/auditlog/add/").status_code == 403
        log = AuditLog.objects.get()
        response = admin_client.post(f"/gestion/platform_settings/auditlog/{log.pk}/delete/", {"post": "yes"})
        assert response.status_code == 403
        assert AuditLog.objects.exists()

    def test_search_audit_log(self, admin_client):
        services.audit(None, "phone.block", "+237600000001")
        response = admin_client.get("/gestion/platform_settings/auditlog/?q=%2B237600000001")
        assert response.context["cl"].result_count == 1


class TestProfileAdmin:
    def test_take_offline_and_back(self, admin_client):
        profile = ProfileFactory()
        _act(admin_client, PROFILES, "take_offline", [profile])
        profile.refresh_from_db()
        assert profile.visibility == Profile.Visibility.PRIVATE
        assert AuditLog.objects.filter(action="profile.visibility.private").exists()
        _act(admin_client, PROFILES, "put_online", [profile])
        profile.refresh_from_db()
        assert profile.visibility == Profile.Visibility.PUBLIC

    def test_suspend_is_audited(self, admin_client):
        profile = ProfileFactory()
        _act(admin_client, PROFILES, "suspend", [profile])
        assert AuditLog.objects.filter(action="profile.suspend").exists()

    def test_changelist_has_site_and_theme_columns(self, admin_client):
        profile = ProfileFactory()
        content = admin_client.get(PROFILES).content.decode()
        assert f"/{profile.slug}" in content
        assert "Modèle de site" in content


class TestAdminIndex:
    def test_index_renders_hero_kpis_and_audit(self, admin_client):
        services.audit(None, "settings.update", "cards")
        response = admin_client.get("/gestion/")
        content = response.content.decode()
        assert response.status_code == 200
        assert reverse("admin:platform_control_center") in content
        assert "OTP WhatsApp" in content
        assert "settings.update" in content
        assert "mp-kpis" in content

    def test_index_shows_maintenance_chip(self, admin_client):
        services.update_settings(None, "maintenance", {"maintenance_mode": True})
        assert "Maintenance en cours" in admin_client.get("/gestion/").content.decode()

    def test_staff_without_permission_has_no_shortcut(self, client):
        client.force_login(UserFactory(is_staff=True))
        content = client.get("/gestion/").content.decode()
        assert reverse("admin:platform_control_center") not in content
