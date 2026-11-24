#!/bin/sh
# Container entrypoint for F1 Control Room.
# - Waits for the database (the stack's postgres service; sslmode defaults to prefer).
# - Runs migrations once, only on the service that sets RUN_MIGRATIONS=1 (web).
# - Then execs the service command (uvicorn, celery worker, beat, flower).
set -e

wait_for_db() {
  python - <<'PY'
import os, sys, time
import dj_database_url, psycopg2
url = os.getenv("DATABASE_URL", "")
if not url or url.startswith("sqlite"):
    sys.exit(0)
cfg = dj_database_url.parse(url)
for attempt in range(30):
    try:
        psycopg2.connect(
            dbname=cfg["NAME"], user=cfg["USER"], password=cfg["PASSWORD"],
            host=cfg["HOST"], port=cfg["PORT"] or 5432,
            sslmode=cfg.get("OPTIONS", {}).get("sslmode", "prefer"),
            connect_timeout=5,
        ).close()
        print("database is reachable")
        sys.exit(0)
    except Exception as exc:
        print(f"waiting for database ({attempt + 1}/30): {exc}")
        time.sleep(2)
sys.exit("database not reachable")
PY
}

wait_for_db

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-0}" = "1" ]; then
  python manage.py collectstatic --noinput --settings="${DJANGO_SETTINGS_MODULE}" \
    || echo "collectstatic skipped (STATIC_ROOT not configured)"
fi

exec "$@"
