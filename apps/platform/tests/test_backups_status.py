import json
import time

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.platform.backups import backup_status


def _write(tmp_path, name, data):
    (tmp_path / name).write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


@override_settings(BACKUP_STATUS_DIR="")
def test_disabled_without_folder():
    assert backup_status() == {"state": "disabled"}


def test_missing_when_no_status_file(tmp_path):
    with override_settings(BACKUP_STATUS_DIR=str(tmp_path)):
        assert backup_status()["state"] == "missing"


def test_ok_then_late(tmp_path):
    now = time.time()
    _write(tmp_path, "last_success.json", {"epoch": int(now - 3 * 3600), "path": "daily/x", "encrypted": True})
    with override_settings(BACKUP_STATUS_DIR=str(tmp_path), BACKUP_MAX_AGE_HOURS=26):
        status = backup_status(now)
        assert status["state"] == "ok" and status["age_hours"] == 3.0
        assert backup_status(now + 30 * 3600)["state"] == "late"


def test_corrupt_status_file_is_missing(tmp_path):
    _write(tmp_path, "last_success.json", "{pas du json")
    with override_settings(BACKUP_STATUS_DIR=str(tmp_path)):
        assert backup_status()["state"] == "missing"


@pytest.mark.django_db
def test_admin_index_shows_backup_chip(admin_client, tmp_path):
    _write(tmp_path, "last_success.json", {"epoch": int(time.time()), "path": "daily/x", "offsite": "failed"})
    with override_settings(BACKUP_STATUS_DIR=str(tmp_path)):
        body = admin_client.get(reverse("admin:index")).content.decode()
    assert "Sauvegarde : il y a" in body
    assert "Copie hors site en échec" in body
