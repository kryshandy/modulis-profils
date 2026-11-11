"""The conftest helper: force_login() staff sessions are 2FA-verified (production code unchanged)."""

import pytest
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY

pytestmark = pytest.mark.django_db


def test_admin_client_is_verified(admin_client):
    assert DEVICE_ID_SESSION_KEY in admin_client.session
    assert admin_client.get(reverse("admin:index")).status_code == 200
    assert admin_client.get(reverse("admin:platform_control_center")).status_code == 200


@pytest.mark.real_2fa
def test_real_2fa_marker_opts_out(client, admin_user):
    client.force_login(admin_user)
    assert DEVICE_ID_SESSION_KEY not in client.session
    assert client.get(reverse("admin:index")).status_code == 302


def test_overview_page(admin_client):
    response = admin_client.get(reverse("admin:security_2fa_overview"))
    assert response.status_code == 200
    assert "Codes de secours" in response.content.decode()
