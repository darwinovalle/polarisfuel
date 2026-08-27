#!/usr/bin/env sh
set -eu

# CONTAINER_ROLE controls what this container runs.
# Valid values: web (default), worker, beat
CONTAINER_ROLE="${CONTAINER_ROLE:-web}"

# Wait for the database to accept connections before proceeding.
# Applies to all roles so migrations/tasks don't race the DB.
if [ "${SKIP_DB_WAIT:-0}" != "1" ]; then
    python - <<'PY'
import os
import socket
import time

host = os.getenv("DB_HOST", "")
port = int(os.getenv("DB_PORT", "5432"))
deadline = time.time() + 60

if not host:
    raise SystemExit("DB_HOST environment variable is not set")

while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"Database ready at {host}:{port}")
            break
    except OSError:
        if time.time() >= deadline:
            raise SystemExit(f"Timed out waiting for database at {host}:{port}")
        time.sleep(1)
PY
fi

# Migrations run explicitly (RUN_MIGRATIONS=1) as a one-off task,
# never automatically on every container boot.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "Running database migrations..."
    python manage.py migrate --noinput
fi

# Optional one-shot fuel import (only when explicitly enabled).
if [ "${AUTO_IMPORT_ON_STARTUP:-0}" = "1" ] && [ -n "${EXCEL_SOURCE_PATH:-}" ] && [ -f "${EXCEL_SOURCE_PATH}" ]; then
    echo "Importing fuel data from ${EXCEL_SOURCE_PATH}..."
    python manage.py run_import \
        --file "${EXCEL_SOURCE_PATH}" \
        --skip-if-imported
fi

case "${CONTAINER_ROLE}" in
    web)
        echo "Starting Gunicorn (web)..."
        exec gunicorn route_fuel_v2.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-2}" \
            --threads "${GUNICORN_THREADS:-4}" \
            --timeout "${GUNICORN_TIMEOUT:-60}" \
            --access-logfile - \
            --error-logfile -
        ;;
    worker)
        echo "Starting Celery worker..."
        exec celery -A route_fuel_v2 worker \
            --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
            --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
        ;;
    beat)
        echo "Starting Celery beat..."
        exec celery -A route_fuel_v2 beat \
            --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
            --schedule="${CELERYBEAT_SCHEDULE:-/tmp/celerybeat-schedule}"
        ;;
    *)
        echo "Unknown CONTAINER_ROLE: ${CONTAINER_ROLE}" >&2
        exit 1
        ;;
esac
