"""Status of the host-side backups (docker/backup, docs/SAUVEGARDES.md), shown on the admin index.

The backup service writes last_success.json / last_verify.json in the backup folder of the host; the
web container mounts that folder read-only at BACKUP_STATUS_DIR. Never raises: a broken or missing
status file is reported as such.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from django.conf import settings


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def backup_status(now: float | None = None) -> dict:
    """{"state": "disabled"|"missing"|"ok"|"late", "age_hours", "last", "verify"}."""
    folder = settings.BACKUP_STATUS_DIR
    if not folder:
        return {"state": "disabled"}
    root = Path(folder)
    last = _read(root / "last_success.json")
    verify = _read(root / "last_verify.json")
    if not last or not isinstance(last.get("epoch"), int):
        return {"state": "missing", "verify": verify}
    age_hours = max(0.0, ((now or time.time()) - last["epoch"]) / 3600)
    state = "ok" if age_hours <= settings.BACKUP_MAX_AGE_HOURS else "late"
    return {"state": state, "age_hours": round(age_hours, 1), "last": last, "verify": verify}
