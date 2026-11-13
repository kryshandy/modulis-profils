"""Only super-admins create or delete team accounts; the evaluation super-admin (bootstrap_superadmin)."""

import pytest
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.platform.models import AuditLog
from tests.factories import ProfileFactory, UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "Une-phrase-fixe-tres-longue-pour-evaluer-2026!"


def staff(**extra):
    user = User.objects.create_user("+237690001001", "Mot-de-passe-equipe-2026!", is_staff=True, **extra)
    user.user_permissions.add(
        *Permission.objects.filter(codename__in=["add_user", "change_user", "delete_user", "view_user"])
    )
    return user


def superadmin(phone="+237690001002"):
    return User.objects.create_superuser(phone, "Mot-de-passe-super-2026!")


# --- creation -----------------------------------------------------------------------------------


def test_staff_with_add_permission_cannot_create_accounts(client):
    client.force_login(staff())
    assert client.get(reverse("admin:accounts_user_add")).status_code == 403
    response = client.post(
        reverse("admin:accounts_user_add"),
        {"phone": "690 00 20 03", "password1": "Intrus-mot-de-passe-2026!", "password2": "Intrus-mot-de-passe-2026!"},
    )
    assert response.status_code == 403
    assert not User.objects.filter(phone="+237690002003").exists()


def test_superadmin_creates_team_accounts(client):
    client.force_login(superadmin())
    assert client.get(reverse("admin:accounts_user_add")).status_code == 200


def test_otp_login_never_opens_a_team_account(client, sms_outbox, django_capture_on_commit_callbacks):
    team = staff()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("dashboard:login"), {"phone": "690 00 10 01"})
    assert not sms_outbox  # no code is even sent to a team number
    assert "_auth_user_id" not in client.session
    assert team.is_staff


# --- deletion -----------------------------------------------------------------------------------


def test_staff_cannot_delete_superadmin_or_other_staff(client):
    me = staff()
    boss = superadmin()
    colleague = User.objects.create_user("+237690001009", "Mot-de-passe-equipe-2026!", is_staff=True)
    pro = UserFactory()
    client.force_login(me)
    assert client.post(reverse("admin:accounts_user_delete", args=[boss.pk]), {"post": "yes"}).status_code == 403
    assert client.post(reverse("admin:accounts_user_delete", args=[colleague.pk]), {"post": "yes"}).status_code == 403
    assert User.objects.filter(pk__in=[boss.pk, colleague.pk]).count() == 2
    client.post(reverse("admin:accounts_user_delete", args=[pro.pk]), {"post": "yes"})
    assert not User.objects.filter(pk=pro.pk).exists()


def test_nobody_deletes_himself_nor_the_last_superadmin(client):
    only = superadmin()
    client.force_login(only)
    assert client.post(reverse("admin:accounts_user_delete", args=[only.pk]), {"post": "yes"}).status_code == 403
    second = superadmin("+237690001003")
    client.post(reverse("admin:accounts_user_delete", args=[second.pk]), {"post": "yes"})
    assert not User.objects.filter(pk=second.pk).exists()
    assert User.objects.filter(pk=only.pk).exists()


def test_superadmin_deletes_another_superadmin_and_staff(client):
    me, other = superadmin(), superadmin("+237690001004")
    colleague = staff()
    client.force_login(me)
    client.post(reverse("admin:accounts_user_delete", args=[other.pk]), {"post": "yes"})
    client.post(reverse("admin:accounts_user_delete", args=[colleague.pk]), {"post": "yes"})
    assert not User.objects.filter(pk__in=[other.pk, colleague.pk]).exists()
    assert AuditLog.objects.filter(action="user.delete").count() == 2


# --- evaluation super-admin ---------------------------------------------------------------------


@pytest.fixture
def boot_env(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PHONE", "+237699000000")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)


def test_bootstrap_creates_superadmin_with_fixed_password(boot_env):
    call_command("bootstrap_superadmin")
    user = User.objects.get(phone="+237699000000")
    assert user.is_superuser and user.is_staff and user.is_active
    assert user.check_password(PASSWORD)
    user.set_password("autre-chose-tres-longue-2026!")
    user.is_active = False
    user.save()
    call_command("bootstrap_superadmin")  # idempotent: fixed password and access restored
    user.refresh_from_db()
    assert user.check_password(PASSWORD) and user.is_active
    assert AuditLog.objects.filter(action="user.bootstrap_superadmin").count() == 2


def test_bootstrap_requires_long_password(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PHONE", "+237699000000")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "trop-court")
    with pytest.raises(CommandError, match="32"):
        call_command("bootstrap_superadmin")


def test_bootstrap_never_hijacks_a_pro_account(boot_env):
    ProfileFactory(user=UserFactory(phone="+237699000000"))
    with pytest.raises(CommandError, match="pro"):
        call_command("bootstrap_superadmin")
    assert not User.objects.get(phone="+237699000000").is_staff


def test_bootstrap_delete_needs_another_superadmin(boot_env):
    call_command("bootstrap_superadmin")
    with pytest.raises(CommandError, match="dernier"):
        call_command("bootstrap_superadmin", "--delete")
    superadmin()
    call_command("bootstrap_superadmin", "--delete")
    assert not User.objects.filter(phone="+237699000000").exists()


def test_production_check_and_admin_banner_flag_the_evaluation_account(boot_env, client):
    from apps.security.checks import bootstrap_admin

    call_command("bootstrap_superadmin")
    with override_settings(DEBUG=False):
        assert [w.id for w in bootstrap_admin(None)] == ["security.W101"]
    client.force_login(User.objects.get(phone="+237699000000"))
    assert "Super-admin d'évaluation actif" in client.get(reverse("admin:index")).content.decode()
