#!/usr/bin/env bash
set -euo pipefail

# Start as root ONLY to make the writable volumes belong to `app`, then drop privileges for good.
# Named Docker volumes (media) are created root-owned: without this, uploads fail with
# "Permission denied: /app/media/…" (bug seen on 2026-11-11 in onboarding / photo).
if [[ "$(id -u)" == "0" ]]; then
  for dir in /app/media; do
    mkdir -p "$dir"
    # Only fix entries with the wrong owner (cheap on large volumes).
    find "$dir" ! -user app -exec chown app:app {} + 2>/dev/null || true
  done
  exec setpriv --reuid=app --regid=app --init-groups --inh-caps=-all "$0" "$@"
fi

# Wait for PostgreSQL when DATABASE_URL points to it.
if [[ "${DATABASE_URL:-}" == postgres* ]]; then
  python - <<'PY'
import os, sys, time
import psycopg
url = os.environ["DATABASE_URL"]
for attempt in range(30):
    try:
        psycopg.connect(url, connect_timeout=2).close()
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("PostgreSQL unreachable", file=sys.stderr)
sys.exit(1)
PY
fi

if [[ "${RUN_MIGRATIONS:-0}" == "1" ]]; then
  python manage.py migrate --noinput
fi

exec "$@"
