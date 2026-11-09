#!/usr/bin/env bash
set -euo pipefail

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
