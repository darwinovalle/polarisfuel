#!/usr/bin/env sh
set -eu

python - <<'PY'
import os
import socket
import time

host = os.getenv("DB_HOST", "db")
port = int(os.getenv("DB_PORT", "5432"))
deadline = time.time() + 60

while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            break
    except OSError:
        if time.time() >= deadline:
            raise SystemExit(f"Timed out waiting for database at {host}:{port}")
        time.sleep(1)
PY

uv run python manage.py migrate --noinput

if [ "${AUTO_IMPORT_ON_STARTUP:-1}" = "1" ] && [ -n "${EXCEL_SOURCE_PATH:-}" ] && [ -f "${EXCEL_SOURCE_PATH}" ]; then
    uv run python manage.py run_import \
        --file "${EXCEL_SOURCE_PATH}" \
        --skip-if-imported
fi

exec uv run python manage.py runserver 0.0.0.0:8000
