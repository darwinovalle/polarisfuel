# Route Fuel v2

This project is a Django monolith that:
- imports fuel station pricing data from CSV or Excel into PostgreSQL,
- stores truck stops, racks, current prices, import jobs, and import issues,
- exposes a UI to optimize a route between an origin and destination based on fuel prices.

## Docker architecture

Docker Compose runs five services:

| Service | Purpose |
| --- | --- |
| `web` | Django migrations, automatic import, and web UI on `http://localhost:8000` |
| `db` | PostgreSQL database |
| `redis` | Celery broker and result backend |
| `celery_worker` | Executes asynchronous Celery tasks |
| `celery_beat` | Schedules periodic tasks, including the daily import |

The PostgreSQL data is stored in the named `postgres_data` volume, so rebuilding
containers does not delete the database.

Celery Beat stores its small schedule database at `/tmp/celerybeat-schedule`
inside its container. This prevents its SQLite sidecar files from appearing in
the project directory.

## Run with Docker

### 1. Create environment file

```bash
cp .env.example .env
```

Set `TOMTOM_API_KEY` in `.env` to the API key from your TomTom developer
account. The key is required for location suggestions and live route
calculation.

### 2. Start all services

```bash
docker compose up --build
```

Services started:
- `web`: Django app on `http://localhost:8000`
- `db`: PostgreSQL
- `redis`: Redis broker/backend for Celery
- `celery_worker`: async task worker
- `celery_beat`: scheduled task runner

### Automatic startup behavior

Every time the `web` container starts:

1. It waits for PostgreSQL to become available.
2. It runs all pending Django migrations.
3. It checks `EXCEL_SOURCE_PATH`.
4. If the configured file exists, it imports it.
5. If that filename already has a successful `ImportJob`, the import is skipped
   to prevent duplicate price records.
6. Django starts on port 8000.

The default `.env.example` configuration imports the bundled file:

```env
EXCEL_SOURCE_PATH=/app/fuel-prices.csv
AUTO_IMPORT_ON_STARTUP=1
```

Set `AUTO_IMPORT_ON_STARTUP=0` to disable the startup import. The variable name
`EXCEL_SOURCE_PATH` is kept for compatibility with the existing Celery task,
but CSV files are supported as well.

After changing `.env`, recreate the web container so Django reads the new
environment values:

```bash
docker compose up -d --force-recreate web celery_worker celery_beat
```

### 3. Stop services

```bash
docker compose down
```

To also remove persisted database data:

```bash
docker compose down -v
```

## Running import manually

Once containers are up, run:

```bash
docker compose exec web uv run python manage.py run_import --file /app/fuel-prices.csv
```

Supported formats are `.csv`, `.xlsx`, `.xlsm`, `.xltx`, and `.xltm`.

The import validates required headers, parses numeric values, removes duplicate
station/rack rows, persists valid records, and records failures in `ImportIssue`.
Each execution creates an `ImportJob`.

## Django admin

Create an administrator:

```bash
docker compose exec web uv run python manage.py createsuperuser
```

Open the admin interface at:

```text
http://localhost:8000/admin/
```

The admin interface can be used to inspect `Truckstop`, `Rack`, `CurrentPrice`,
`ImportJob`, and `ImportIssue` records.

To verify database counts from the command line:

```bash
docker compose exec web uv run python manage.py shell -c "from stations.models import Truckstop, Rack, CurrentPrice, ImportJob; print({'truckstops': Truckstop.objects.count(), 'racks': Rack.objects.count(), 'prices': CurrentPrice.objects.count(), 'jobs': ImportJob.objects.count()})"
```

## Resetting the database

Stopping containers preserves database data:

```bash
docker compose down
```

To delete the PostgreSQL volume and trigger a fresh migration/import on the next
startup:

```bash
docker compose down -v
docker compose up --build
```

This permanently removes the local Docker database contents.