"""Regression tests of the security review of 3be2527..e346dcc (platform / admin side)."""

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.platform import services
from apps.platform.models import AuditLog, BlockedPhone, SiteSettings
from apps.themes.models import Theme
from tests.factories import ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db

BLOCK_ADD = "/gestion/platform_settings/blockedphone/add/"
USERS = "/gestion/accounts/user/"


def _staff(*codenames):
    staff = UserFactory(is_staff=True)
    staff.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return staff


def _sessions_of(user) -> int:
    return sum(1 for s in Session.objects.all() if s.get_decoded().get("_auth_user_id") == str(user.pk))


# --- 1. blocking a number cannot deactivate a superuser / staff / oneself ------------------


class TestBlockPhoneGuard:
    def test_staff_cannot_block_superuser_through_blockedphone_admin(self, client, admin_user):
        staff = _staff("add_blockedphone", "view_blockedphone")
        client.force_login(staff)
        response = client.post(BLOCK_ADD, {"phone": admin_user.phone, "reason": "x"})
        assert response.status_code == 200  # form redisplayed with the error
        assert "super-administrateur" in response.content.decode()
        admin_user.refresh_from_db()
        assert admin_user.is_active and not BlockedPhone.objects.exists()

    def test_staff_cannot_block_other_staff(self, admin_user):
        staff, other = _staff("add_blockedphone"), UserFactory(is_staff=True)
        with pytest.raises(PermissionDenied):
            services.block_phone(other.phone, reason="x", actor=staff)
        other.refresh_from_db()
        assert other.is_active and not BlockedPhone.objects.exists()

    def test_nobody_blocks_own_number(self, admin_user):
        with pytest.raises(PermissionDenied):
            services.block_phone(admin_user.phone, reason="x", actor=admin_user)
        assert not BlockedPhone.objects.exists()

    def test_superuser_may_block_staff_and_system_may_block_anyone(self, admin_user):
        other = UserFactory(is_staff=True)
        services.block_phone(other.phone, reason="x", actor=admin_user)
        other.refresh_from_db()
        assert not other.is_active
        boss = UserFactory(is_staff=True, is_superuser=True)
        services.block_phone(boss.phone, reason="x", actor=None)
        boss.refresh_from_db()
        assert not boss.is_active

    def test_staff_still_blocks_a_pro(self, client):
        staff = _staff("add_blockedphone", "view_blockedphone")
        pro = UserFactory(phone="+237677001133")
        client.force_login(staff)
        assert client.post(BLOCK_ADD, {"phone": pro.phone, "reason": "fraude"}).status_code == 302
        pro.refresh_from_db()
        assert not pro.is_active

    def test_user_action_reports_refused_staff_without_500(self, client):
        staff = _staff("view_user", "change_user", "add_blockedphone")
        other = UserFactory(is_staff=True)
        client.force_login(staff)
        response = client.post(USERS, {"action": "block_phones", ACTION_CHECKBOX_NAME: [other.pk]}, follow=True)
        assert response.status_code == 200
        assert not BlockedPhone.objects.exists()


# --- 2. privilege escalation through the user change form -----------------------------------


class TestPrivilegeFields:
    def _change_url(self, user):
        return reverse("admin:accounts_user_change", args=[user.pk])

    def test_staff_cannot_make_himself_superuser(self, client):
        staff = _staff("view_user", "change_user")
        client.force_login(staff)
        form = client.get(self._change_url(staff)).context["adminform"].form
        for name in ("is_superuser", "is_staff", "groups", "user_permissions"):
            assert name not in form.fields
        data = {
            "phone": staff.phone,
            "full_name": "x",
            "email": "",
            "country": "",
            "is_active": "on",
            "is_superuser": "on",
            "user_permissions": [p.pk for p in Permission.objects.all()[:5]],
            "date_joined_0": "2026-01-01",
            "date_joined_1": "10:00:00",
            "profiles-TOTAL_FORMS": "0",
            "profiles-INITIAL_FORMS": "0",
        }
        client.post(self._change_url(staff), data)
        staff.refresh_from_db()
        assert not staff.is_superuser
        assert staff.user_permissions.count() == 2

    def test_staff_cannot_promote_another_user(self, client):
        staff = _staff("view_user", "change_user")
        target = UserFactory()
        client.force_login(staff)
        form = client.get(self._change_url(target)).context["adminform"].form
        assert "is_staff" not in form.fields and "groups" not in form.fields

    def test_superuser_edits_others_but_not_his_own_privileges(self, client, admin_user):
        client.force_login(admin_user)
        target = UserFactory(is_staff=True)
        assert "is_superuser" in client.get(self._change_url(target)).context["adminform"].form.fields
        own = client.get(self._change_url(admin_user)).context["adminform"].form.fields
        assert "is_superuser" not in own and "is_staff" not in own
        Group.objects.create(name="x")  # (groups readonly too: no accidental lock-out)
        assert "groups" not in own


# --- 9. settings cache invalidated after commit ---------------------------------------------


def test_settings_cache_invalidated_on_commit(django_capture_on_commit_callbacks):
    services.get_settings()
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        obj = SiteSettings.objects.get(pk=1)
        obj.reports_enabled = False
        obj.save()
        services.get_settings()  # a concurrent reader re-caches before our commit…
    assert services.invalidate in callbacks
    for callback in callbacks:
        callback()
    assert services.feature("reports") is False  # …and the commit hook drops that stale copy


# --- 10. sessions decoded once for a batch --------------------------------------------------


def test_terminate_sessions_batches_users():
    users = [UserFactory() for _ in range(3)]
    keep = UserFactory()
    for user in [*users, keep]:
        Client().force_login(user)
    with CaptureQueriesContext(connection) as queries:
        assert services.terminate_sessions([u.pk for u in users]) == 3
    selects = [q for q in queries.captured_queries if q["sql"].startswith("SELECT") and "django_session" in q["sql"]]
    assert len(selects) == 1  # one pass over the active sessions, whatever the number of users
    assert all(_sessions_of(u) == 0 for u in users) and _sessions_of(keep) == 1


def test_deactivate_action_is_batched_and_audited(client, admin_user):
    users = [UserFactory() for _ in range(2)]
    for user in users:
        Client().force_login(user)
    client.force_login(admin_user)
    client.post(USERS, {"action": "deactivate_accounts", ACTION_CHECKBOX_NAME: [u.pk for u in users]})
    assert User.objects.filter(pk__in=[u.pk for u in users], is_active=False).count() == 2
    assert AuditLog.objects.filter(action="user.deactivate").count() == 2
    assert all(_sessions_of(u) == 0 for u in users)


# --- 13. admin deletions and theme changes are audited --------------------------------------


class TestAdminAudit:
    def test_user_deletion_is_audited(self, client, admin_user):
        target = UserFactory()
        client.force_login(admin_user)
        client.post(reverse("admin:accounts_user_delete", args=[target.pk]), {"post": "yes"})
        assert not User.objects.filter(pk=target.pk).exists()
        assert AuditLog.objects.filter(action="user.delete", target=target.phone, actor=admin_user).exists()

    def test_bulk_user_deletion_is_audited(self, client, admin_user):
        targets = [UserFactory(), UserFactory()]
        client.force_login(admin_user)
        client.post(USERS, {"action": "delete_selected", "post": "yes", ACTION_CHECKBOX_NAME: [t.pk for t in targets]})
        assert AuditLog.objects.filter(action="user.delete").count() == 2

    def test_profile_erasure_is_audited(self, client, admin_user):
        profile = ProfileFactory()
        slug = profile.slug
        client.force_login(admin_user)
        client.post(
            "/gestion/profiles/profile/",
            {"action": "erase_permanently", "confirm_erase": "yes", ACTION_CHECKBOX_NAME: [profile.pk]},
        )
        assert AuditLog.objects.filter(action="profile.erase", target=f"/{slug}").exists()

    def test_theme_change_and_bulk_actions_are_audited(self, client, admin_user):
        client.force_login(admin_user)
        theme = Theme.objects.exclude(code="signature").first()
        if theme is None:
            theme = Theme.objects.create(code="essai", name="Essai")
        client.post("/gestion/themes/theme/", {"action": "make_premium", ACTION_CHECKBOX_NAME: [theme.pk]})
        assert AuditLog.objects.filter(action="theme.bulk_update", target=theme.code).exists()
        from django.contrib import admin as django_admin

        request = type("R", (), {"user": admin_user})()
        form = type("F", (), {"changed_data": ["name"]})()
        django_admin.site._registry[Theme].save_model(request, theme, form, change=True)
        assert AuditLog.objects.filter(action="theme.update", target=theme.code, details__fields=["name"]).exists()


# --- 14. control center: channel table fits its card ----------------------------------------


def test_unconfigured_channel_uses_short_badge_and_help_line(client, admin_user):
    client.force_login(admin_user)
    html = client.get(reverse("admin:platform_control_center")).content.decode()
    assert 'class="mp-table mp-table--channels"' in html
    assert ">non configuré</span>" in html
    assert '<span class="mp-table__help">variables d' in html
    assert "non configuré (variables" not in html
