"""Staff TOTP two-factor authentication on the admin (ADR-0010)."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import struct
import sys
import time
from io import StringIO

import pytest
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User
from apps.platform.models import AuditLog
from apps.security import services

pytestmark = [pytest.mark.django_db, pytest.mark.real_2fa]

PASSWORD = "staff-password-2fa-123"


def totp(key: bytes, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """RFC 6238 (HMAC-SHA1), independent from django-otp."""
    counter = int((time.time() if at is None else at) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**digits
    return f"{value:0{digits}d}"


def make_staff(phone="+237699000001", superuser=True, **extra) -> User:
    if superuser:
        return User.objects.create_superuser(phone, PASSWORD, **extra)
    return User.objects.create_user(phone, PASSWORD, is_staff=True, **extra)


def password_login(client: Client, user: User, **extra):
    return client.post(reverse("admin:login"), {"username": user.phone, "password": PASSWORD}, **extra)


def enrolled(user: User) -> TOTPDevice:
    device = TOTPDevice.objects.create(user=user, name="application", confirmed=True)
    services.regenerate_backup_codes(user)
    return device


def actions(action: str) -> int:
    return AuditLog.objects.filter(action=action).count()


class TestEnrollment:
    def test_first_login_forces_enrollment(self, client):
        user = make_staff()
        response = password_login(client, user)
        assert response.status_code == 302
        response = client.get(reverse("admin:index"))
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("admin:security_2fa_enroll"))

    def test_enrollment_page_shows_inline_qr_and_secret(self, client):
        user = make_staff()
        password_login(client, user)
        response = client.get(reverse("admin:security_2fa_enroll"))
        assert response.status_code == 200
        body = response.content.decode()
        assert '<svg width="' in body and "mx-2fa-qr__svg" in body
        svg = body[body.index("<svg") : body.index("</svg>")]
        assert "style" not in svg and "<script" not in svg  # strict CSP: no inline style/script
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        assert services.manual_secret(device) in body
        assert "http" not in svg  # no external QR service
        # Same secret across reloads.
        client.get(reverse("admin:security_2fa_enroll"))
        assert TOTPDevice.objects.filter(user=user).count() == 1
        assert response["Cache-Control"].startswith("max-age=0") or "no-cache" in response["Cache-Control"]

    def test_wrong_code_refused(self, client):
        user = make_staff()
        password_login(client, user)
        client.get(reverse("admin:security_2fa_enroll"))
        response = client.post(reverse("admin:security_2fa_enroll"), {"code": "000000"})
        assert response.status_code == 200
        assert "Code incorrect" in response.content.decode()
        assert not TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        assert actions("2fa.verify_failed") == 1
        assert client.get(reverse("admin:index")).status_code == 302

    def test_confirm_creates_device_backup_codes_and_unlocks_admin(self, client):
        user = make_staff()
        password_login(client, user)
        client.get(reverse("admin:security_2fa_enroll"))
        device = TOTPDevice.objects.get(user=user)
        cc = reverse("admin:platform_control_center")
        response = client.post(reverse("admin:security_2fa_enroll"), {"code": totp(device.bin_key), "next": cc})
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("admin:security_2fa_backup_codes"))
        device.refresh_from_db()
        assert device.confirmed
        assert StaticToken.objects.filter(device__user=user).count() == 10
        assert actions("2fa.enroll") == 1

        page = client.get(response["Location"])
        codes = [services.format_backup_code(t.token) for t in StaticToken.objects.filter(device__user=user)]
        body = page.content.decode()
        assert all(code in body for code in codes)

        download = client.get(reverse("admin:security_2fa_backup_codes_download"))
        assert download.status_code == 200
        assert download["Content-Disposition"].startswith("attachment;")
        assert "no-store" in download["Cache-Control"]
        assert all(code in download.content.decode() for code in codes)

        done = client.post(reverse("admin:security_2fa_backup_codes"), {"next": cc})
        assert done["Location"] == cc
        assert client.get(cc).status_code == 200
        # Shown once: the codes are gone from the session.
        assert client.get(reverse("admin:security_2fa_backup_codes_download")).status_code == 404
        assert codes[0] not in client.get(reverse("admin:security_2fa_backup_codes")).content.decode()

    def test_external_next_is_ignored(self, client):
        user = make_staff()
        password_login(client, user)
        client.get(reverse("admin:security_2fa_enroll"))
        device = TOTPDevice.objects.get(user=user)
        response = client.post(
            reverse("admin:security_2fa_enroll"), {"code": totp(device.bin_key), "next": "https://evil.example/"}
        )
        assert "evil" not in response["Location"]

    def test_enrolled_user_cannot_reenroll(self, client):
        user = make_staff()
        enrolled(user)
        password_login(client, user)
        response = client.get(reverse("admin:security_2fa_enroll"))
        assert response["Location"].startswith(reverse("admin:security_2fa_verify"))

    def test_pages_refuse_anonymous_and_pros(self, client):
        response = client.get(reverse("admin:security_2fa_enroll"))
        assert response["Location"].startswith(reverse("admin:login"))
        pro = User.objects.create_user("+237699000009")
        client.force_login(pro)
        response = client.get(reverse("admin:security_2fa_verify"))
        assert response["Location"].startswith(reverse("admin:login"))


class TestVerificationRequired:
    URLS = (
        "admin:index",
        "admin:platform_control_center",
        "admin:accounts_user_changelist",
        "admin:platform_settings_auditlog_changelist",
        "admin:jsi18n",
        "admin:security_2fa_overview",
        "admin:security_2fa_backup_codes",
    )

    @pytest.mark.parametrize("name", URLS)
    def test_every_admin_url_redirects_to_verification(self, client, name):
        user = make_staff()
        enrolled(user)
        password_login(client, user)
        response = client.get(reverse(name))
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("admin:security_2fa_verify"))

    def test_post_to_admin_is_not_processed(self, client):
        user = make_staff()
        other = make_staff("+237699000002", superuser=False)
        enrolled(user)
        password_login(client, user)
        url = reverse("admin:accounts_user_changelist")
        response = client.post(url, {"action": "deactivate_accounts", "_selected_action": [other.pk]})
        assert response.status_code == 302
        other.refresh_from_db()
        assert other.is_active

    def test_has_permission_is_a_second_lock(self, client, settings):
        """Even without the middleware, admin views refuse an unverified staff session."""
        settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if not m.endswith("StaffTwoFactorMiddleware")]
        user = make_staff()
        enrolled(user)
        password_login(client, user)
        for name in ("admin:index", "admin:platform_control_center", "admin:accounts_user_changelist"):
            response = client.get(reverse(name))
            assert response.status_code == 302, name
            assert response["Location"].startswith(reverse("admin:login"))

    def test_unverified_staff_can_log_out(self, client):
        user = make_staff()
        enrolled(user)
        password_login(client, user)
        response = client.post(reverse("admin:logout"))
        assert response.status_code in (200, 302)
        assert "_auth_user_id" not in client.session

    def test_valid_code_grants_access_and_rotates_session(self, client):
        user = make_staff()
        device = enrolled(user)
        password_login(client, user)
        before = client.session.session_key
        url = reverse("admin:security_2fa_verify") + "?next=" + reverse("admin:platform_control_center")
        response = client.post(url, {"code": totp(device.bin_key)})
        assert response["Location"] == reverse("admin:platform_control_center")
        assert client.session.session_key != before
        assert not Session.objects.filter(session_key=before).exists()
        assert client.get(reverse("admin:platform_control_center")).status_code == 200

    def test_code_replay_is_refused(self, client):
        user = make_staff()
        device = enrolled(user)
        code = totp(device.bin_key)
        password_login(client, user)
        assert client.post(reverse("admin:security_2fa_verify"), {"code": code}).status_code == 302
        other = Client()
        password_login(other, user)
        response = other.post(reverse("admin:security_2fa_verify"), {"code": code})
        assert response.status_code == 200 and "Code incorrect" in response.content.decode()

    def test_new_password_login_requires_a_new_verification(self, client):
        user = make_staff()
        device = enrolled(user)
        password_login(client, user)
        client.post(reverse("admin:security_2fa_verify"), {"code": totp(device.bin_key)})
        assert client.get(reverse("admin:index")).status_code == 200
        password_login(client, user)
        assert DEVICE_ID_SESSION_KEY not in client.session
        assert client.get(reverse("admin:index")).status_code == 302

    def test_get_login_page_while_unverified_goes_to_verification(self, client):
        user = make_staff()
        enrolled(user)
        password_login(client, user)
        response = client.get(reverse("admin:login"))
        assert response["Location"].startswith(reverse("admin:security_2fa_verify"))

    def test_disabled_in_dev(self, client, settings):
        settings.STAFF_2FA_REQUIRED = False
        user = make_staff()
        password_login(client, user)
        assert client.get(reverse("admin:index")).status_code == 200


class TestBackupCodes:
    def test_backup_code_works_once(self, client):
        user = make_staff()
        enrolled(user)
        code = StaticToken.objects.filter(device__user=user).first().token
        password_login(client, user)
        response = client.post(reverse("admin:security_2fa_verify"), {"code": services.format_backup_code(code)})
        assert response.status_code == 302
        assert client.get(reverse("admin:index")).status_code == 200
        assert StaticToken.objects.filter(device__user=user).count() == 9
        assert AuditLog.objects.get(action="2fa.backup_code_used").details["remaining"] == 9

        other = Client()
        password_login(other, user)
        response = other.post(reverse("admin:security_2fa_verify"), {"code": code})
        assert response.status_code == 200 and "Code incorrect" in response.content.decode()

    def test_regenerate_keeps_backup_verified_session(self, client):
        user = make_staff()
        enrolled(user)
        code = StaticToken.objects.filter(device__user=user).first().token
        password_login(client, user)
        client.post(reverse("admin:security_2fa_verify"), {"code": code})
        response = client.post(reverse("admin:security_2fa_backup_codes_regenerate"))
        assert response.status_code == 302
        assert not StaticToken.objects.filter(token=code).exists()
        assert StaticToken.objects.filter(device__user=user).count() == 10
        assert client.get(reverse("admin:index")).status_code == 200
        assert actions("2fa.backup_codes_regenerated") == 1


class TestLockout:
    def test_locked_after_five_attempts_even_with_valid_code(self, client):
        user = make_staff()
        device = enrolled(user)
        password_login(client, user)
        url = reverse("admin:security_2fa_verify")
        for _ in range(5):
            assert client.post(url, {"code": "000000"}).status_code == 200
        response = client.post(url, {"code": totp(device.bin_key)})
        assert response.status_code == 429
        assert "Trop de codes incorrects" in response.content.decode()
        assert actions("2fa.locked") == 1
        assert actions("2fa.verify_failed") == 5
        assert client.get(reverse("admin:index")).status_code == 302

    def test_lock_is_per_ip(self, client):
        user = make_staff()
        device = enrolled(user)
        password_login(client, user)
        url = reverse("admin:security_2fa_verify")
        for _ in range(6):
            client.post(url, {"code": "000000"})
        device.throttling_failure_count = 0  # isolate our limiter from django-otp's own backoff
        device.save()
        response = client.post(url, {"code": totp(device.bin_key)}, REMOTE_ADDR="10.9.9.9")
        assert response.status_code == 302


class TestReset:
    def _reset(self, client, target):
        return client.post(
            reverse("admin:accounts_user_changelist"),
            {"action": "reset_two_factor", "_selected_action": [target.pk]},
        )

    def test_superuser_resets_another_staff(self, client):
        admin_user = make_staff()
        target = make_staff("+237699000002", superuser=False)
        enrolled(target)
        target_client = Client()
        target_client.force_login(target)
        admin_device = enrolled(admin_user)
        password_login(client, admin_user)
        client.post(reverse("admin:security_2fa_verify"), {"code": totp(admin_device.bin_key)})

        self._reset(client, target)
        assert not TOTPDevice.objects.filter(user=target).exists()
        assert not StaticDevice.objects.filter(user=target).exists()
        assert actions("2fa.reset") == 1
        assert target_client.get(reverse("admin:index"))["Location"].startswith(reverse("admin:login"))

        target_client = Client()
        password_login(target_client, target)
        response = target_client.get(reverse("admin:index"))
        assert response["Location"].startswith(reverse("admin:security_2fa_enroll"))

    def test_never_on_self(self, client):
        admin_user = make_staff()
        device = enrolled(admin_user)
        password_login(client, admin_user)
        client.post(reverse("admin:security_2fa_verify"), {"code": totp(device.bin_key)})
        self._reset(client, admin_user)
        assert TOTPDevice.objects.filter(user=admin_user).exists()
        assert actions("2fa.reset") == 0

    def test_staff_without_superuser_cannot_reset(self, client):
        from django.contrib.auth.models import Permission

        staff = make_staff("+237699000003", superuser=False)
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_user", "change_user"]))
        target = make_staff("+237699000004", superuser=False)
        enrolled(target)
        device = enrolled(staff)
        password_login(client, staff)
        client.post(reverse("admin:security_2fa_verify"), {"code": totp(device.bin_key)})
        page = client.get(reverse("admin:accounts_user_changelist"))
        assert page.status_code == 200
        assert "reset_two_factor" not in page.content.decode()
        self._reset(client, target)
        assert TOTPDevice.objects.filter(user=target).exists()

    def test_service_refuses_self_and_non_superuser(self):
        from django.core.exceptions import PermissionDenied

        admin_user = make_staff()
        staff = make_staff("+237699000005", superuser=False)
        with pytest.raises(PermissionDenied):
            services.reset_two_factor(admin_user, actor=admin_user)
        with pytest.raises(PermissionDenied):
            services.reset_two_factor(admin_user, actor=staff)


def test_two_factor_summary():
    with_2fa = make_staff()
    enrolled(with_2fa)
    without = make_staff("+237699000006", superuser=False, full_name="Awa")
    TOTPDevice.objects.create(user=without, name="pending", confirmed=False)
    User.objects.create_user("+237699000007")  # a pro: not counted
    make_staff("+237699000008", superuser=False, is_active=False)  # disabled: not counted
    summary = services.two_factor_summary()
    assert summary["required"] is True
    assert summary["staff_total"] == 2
    assert summary["staff_enrolled"] == 1
    assert [s["phone"] for s in summary["staff_without_2fa"]] == [without.phone]


def test_device_admins_hidden():
    from django.contrib import admin

    assert not admin.site.is_registered(TOTPDevice)
    assert not admin.site.is_registered(StaticDevice)


class TestCreateStaffCommand:
    def test_non_interactive(self, monkeypatch):
        monkeypatch.setenv("DJANGO_STAFF_PASSWORD", PASSWORD)
        out = StringIO()
        call_command(
            "create_staff", "--phone", "690 00 02 00", "--full-name", "Awa Ndi", "--superuser", "--no-input", stdout=out
        )
        user = User.objects.get(phone="+237690000200")
        assert user.is_staff and user.is_superuser and user.full_name == "Awa Ndi"
        assert user.check_password(PASSWORD)
        assert "scannez le QR code" in out.getvalue() and "/gestion/" in out.getvalue()
        assert actions("user.create_staff") == 1

    def test_weak_password_refused(self, monkeypatch):
        monkeypatch.setenv("DJANGO_STAFF_PASSWORD", "short")
        with pytest.raises(CommandError):
            call_command("create_staff", "--phone", "+237690000201", "--no-input", stdout=StringIO())
        assert not User.objects.filter(phone="+237690000201").exists()

    def test_existing_phone_and_missing_password(self, monkeypatch):
        make_staff("+237690000202")
        monkeypatch.setenv("DJANGO_STAFF_PASSWORD", PASSWORD)
        with pytest.raises(CommandError, match="existe déjà"):
            call_command("create_staff", "--phone", "+237690000202", "--no-input", stdout=StringIO())
        monkeypatch.delenv("DJANGO_STAFF_PASSWORD")
        with pytest.raises(CommandError):
            call_command("create_staff", "--phone", "+237690000203", "--no-input", stdout=StringIO())

    def test_interactive(self, monkeypatch):
        answers = iter(["Awa", "n"])
        monkeypatch.setattr("builtins.input", lambda *_: next(answers))
        passwords = iter(["short", "short", PASSWORD, PASSWORD])
        monkeypatch.setattr("getpass.getpass", lambda *_: next(passwords))
        call_command("create_staff", "--phone", "+237690000204", stdout=StringIO(), stderr=StringIO())
        user = User.objects.get(phone="+237690000204")
        assert user.is_staff and not user.is_superuser


class TestProdSettings:
    GOOD = {
        "CACHE_URL": "rediscache://redis:6379/0",
        "SMS_BACKEND": "apps.accounts.sms.DisabledSmsBackend",
        "OTP_HMAC_KEY": "o" * 40,
        "ANALYTICS_SALT": "a" * 40,
        "CARD_ACTIVATION_KEY": "c" * 40,
        "SLUG_HASH_KEY": "s" * 40,
        "STAFF_2FA_REQUIRED": "True",
        "ADMIN_URL": "gestion-7k2m9q4x8p3z/",
    }

    def _load(self, monkeypatch, **overrides):
        for key, value in {**self.GOOD, **overrides}.items():
            monkeypatch.setenv(key, value)
        sys.modules.pop("config.settings.prod", None)
        try:
            return importlib.import_module("config.settings.prod")
        finally:
            sys.modules.pop("config.settings.prod", None)

    def test_valid(self, monkeypatch):
        prod = self._load(monkeypatch)
        assert prod.STAFF_2FA_REQUIRED is True
        assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE and prod.SECURE_HSTS_SECONDS > 0

    def test_2fa_cannot_be_disabled(self, monkeypatch):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured, match="STAFF_2FA_REQUIRED"):
            self._load(monkeypatch, STAFF_2FA_REQUIRED="False")

    @pytest.mark.parametrize(
        "value",
        [
            "gestion/",
            "admin/",
            "",
            "gestion",
            "/gestion-7k2m9q4x8p3z/",
            "gestion-abc/",
            "gestion-abcdefghijklmn/",
            "x y/",
        ],
    )
    def test_admin_url_must_be_secret(self, monkeypatch, value):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured, match="ADMIN_URL"):
            self._load(monkeypatch, ADMIN_URL=value)
