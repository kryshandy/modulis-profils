from unittest import mock

import pytest

from apps.platform import health

pytestmark = pytest.mark.django_db


def test_storage_check_ok():
    check = health._storage()
    assert check.state == health.OK


def test_storage_check_reports_permission_error():
    """Regression 2026-11-11: root-owned media volume → every upload failed."""
    with mock.patch(
        "django.core.files.storage.default_storage.save",
        side_effect=PermissionError("[Errno 13] Permission denied: '/app/media/profiles'"),
    ):
        check = health._storage()
    assert check.state == health.ERROR
    assert "Permission denied" in check.detail


def test_storage_is_part_of_the_report():
    labels = [c.label for c in health.report()]
    assert "Stockage des fichiers" in labels
