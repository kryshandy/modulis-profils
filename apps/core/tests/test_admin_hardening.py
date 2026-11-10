"""Admin hardening: action permissions, login throttling, short staff sessions, N+1, erasure action."""

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.billing.models import Plan
from apps.billing.services import grant_plan
from apps.moderation import services as moderation
from apps.moderation.models import Report
from apps.profiles.models import Profile, SlugRegistry
from tests.factories import ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db


def _staff(*perms):
    user = UserFactory(is_staff=True)
    user.set_password("staff-password-123")
    user.save()
    for codename in perms:
        app_label, code = codename.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=code))
    return user.__class__.objects.get(pk=user.pk)  # fresh permission cache


def _actions(user, model=Profile):
    request = RequestFactory().get("/")
    request.user = user
    return set(admin.site._registry[model].get_actions(request))


class TestActionPermissions:
    def test_every_custom_action_declares_permissions(self):
        missing = []
        for model, model_admin in admin.site._registry.items():
            for name in model_admin.actions or ():
                func = getattr(model_admin, name) if isinstance(name, str) else name
                if not getattr(func, "allowed_permissions", None):
                    missing.append(f"{model.__name__}.{getattr(func, '__name__', name)}")
        assert missing == []

    def test_view_only_staff_sees_no_profile_action(self):
        assert _actions(_staff("profiles.view_profile")) == set()

    def test_grant_and_erase_need_their_own_permission(self):
        editor = _staff("profiles.view_profile", "profiles.change_profile")
        actions = _actions(editor)
        assert {"verify", "suspend", "queue_indexing"} <= actions
        assert not {"grant_pro", "grant_essentiel", "erase_permanently"} & actions
        granted = _staff(
            "profiles.view_profile", "profiles.change_profile", "profiles.grant_subscription", "profiles.erase_profile"
        )
        assert {"grant_pro", "grant_essentiel", "erase_permanently"} <= _actions(granted)

    def test_suspending_from_reports_needs_profile_change(self):
        moderator = _staff("moderation.view_report", "moderation.change_report")
        assert "suspend_profile" not in _actions(moderator, Report)
        assert {"dismiss", "mark_actioned"} <= _actions(moderator, Report)
        both = _staff("moderation.view_report", "moderation.change_report", "profiles.change_profile")
        assert "suspend_profile" in _actions(both, Report)


class TestAdminLogin:
    def test_throttled_after_max_attempts(self, client, settings):
        settings.ADMIN_LOGIN_MAX_ATTEMPTS_PER_HOUR = 3
        url = reverse("admin:login")
        statuses = [client.post(url, {"username": "+237699999998", "password": "bad"}).status_code for _ in range(4)]
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429
        response = client.post(url, {"username": "x", "password": "y"})
        assert response.status_code == 429 and "Trop de tentatives" in response.content.decode()
        assert client.post(url, {"username": "x"}, REMOTE_ADDR="10.0.0.8").status_code == 200  # other IP
        assert client.get(url).status_code == 200  # GET never counted

    def test_staff_session_is_short(self, client, admin_user, settings):
        response = client.post(reverse("admin:login"), {"username": admin_user.phone, "password": "admin-password-123"})
        assert response.status_code == 302
        assert client.session.get_expiry_age() == settings.STAFF_SESSION_AGE

    def test_pro_session_keeps_default_length(self, client, settings):
        pro = UserFactory()
        client.force_login(pro)
        assert client.session.get_expiry_age() == settings.SESSION_COOKIE_AGE


class TestProfileChangelist:
    def _count(self, admin_client):
        with CaptureQueriesContext(connection) as ctx:
            assert admin_client.get(reverse("admin:profiles_profile_changelist")).status_code == 200
        return len(ctx.captured_queries)

    def test_plan_column_without_n_plus_one(self, admin_client, django_assert_max_num_queries):
        pro = Plan.objects.get(code="pro")
        for _ in range(2):
            grant_plan(ProfileFactory(), pro)
        admin_client.get(reverse("admin:profiles_profile_changelist"))  # warm up
        few = self._count(admin_client)
        for _ in range(10):
            grant_plan(ProfileFactory(), pro)
        many = self._count(admin_client)
        assert many == few
        with django_assert_max_num_queries(few):
            response = admin_client.get(reverse("admin:profiles_profile_changelist"))
        assert response.content.decode().count(">pro<") >= 12

    def test_visibility_not_duplicated(self):
        list_display = admin.site._registry[Profile].list_display
        assert len(list_display) == len(set(list_display)) and "visibility" not in list_display


class TestEraseAction:
    def test_confirmation_page_then_erasure(self, admin_client, django_capture_on_commit_callbacks):
        profile = ProfileFactory(slug="page-a-effacer")
        url = reverse("admin:profiles_profile_changelist")
        data = {"action": "erase_permanently", "_selected_action": [profile.pk]}
        response = admin_client.post(url, data)
        assert response.status_code == 200
        body = response.content.decode()
        assert "irréversible" in body and "page-a-effacer" in body
        profile.refresh_from_db()
        assert profile.status == Profile.Status.ACTIVE  # nothing done before confirmation
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(url, {**data, "confirm_erase": "yes"})
        assert response.status_code == 302
        profile.refresh_from_db()
        assert profile.status == Profile.Status.DELETED
        assert not SlugRegistry.objects.filter(slug="page-a-effacer").exists()

    def test_editor_cannot_erase(self, client):
        editor = _staff("profiles.view_profile", "profiles.change_profile")
        client.force_login(editor)
        profile = ProfileFactory()
        client.post(
            reverse("admin:profiles_profile_changelist"),
            {"action": "erase_permanently", "_selected_action": [profile.pk], "confirm_erase": "yes"},
        )
        profile.refresh_from_db()
        assert profile.status == Profile.Status.ACTIVE


class TestReportClosing:
    def test_each_report_closed_exactly_once(self, admin_user, monkeypatch):
        profile = ProfileFactory()
        first = moderation.create_report(profile, "scam")
        second = moderation.create_report(profile, "spam")
        calls = []
        real = moderation.close_report

        def spy(report, status, **kwargs):
            calls.append(report.pk)
            return real(report, status, **kwargs)

        monkeypatch.setattr(moderation, "close_report", spy)
        moderation.suspend_reported_profile(first, by=admin_user)
        assert sorted(calls) == sorted([first.pk, second.pk])
        assert first.status == Report.Status.ACTIONED
        assert first.handled_by == admin_user

    def test_already_dismissed_report_is_actioned_once(self, admin_user):
        profile = ProfileFactory()
        report = moderation.create_report(profile, "scam")
        moderation.close_report(report, Report.Status.DISMISSED)
        moderation.suspend_reported_profile(report, by=admin_user)
        report.refresh_from_db()
        assert report.status == Report.Status.ACTIONED
