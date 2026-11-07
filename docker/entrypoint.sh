#!/bin/bash
# Container start: back up the database if migrations are pending, migrate,
# then serve the ASGI app with Daphne.
set -uo pipefail

cd /app
source /app/.venv/bin/activate

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-10}"

log() { echo "[entrypoint] $*"; }

# Wait for the database (the container may start before Postgres is reachable).
for attempt in $(seq 1 30); do
    if python manage.py shell -c "from django.db import connection; connection.ensure_connection()" >/dev/null 2>&1; then
        break
    fi
    log "database not reachable yet (attempt $attempt/30)"
    sleep 2
done

if python manage.py migrate --check >/dev/null 2>&1; then
    log "no pending migrations"
else
    log "pending migrations; backing up database first"
    mkdir -p "$BACKUP_DIR"
    backup="$BACKUP_DIR/${DB_NAME:-db}-$(date +%Y%m%d-%H%M%S).sql.gz"
    if PGPASSWORD="${DB_PASSWORD:-}" pg_dump -h "${DB_HOST:-localhost}" -U "${DB_USER:-postgres}" "${DB_NAME:-postgres}" | gzip > "$backup"; then
        log "backup written to $backup"
        ls -1t "$BACKUP_DIR"/*.sql.gz 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | xargs -r rm -f
    else
        log "ERROR: database backup failed; not migrating"
        rm -f "$backup"
        exit 1
    fi
    python manage.py migrate --noinput || { log "ERROR: migrate failed"; exit 1; }
fi

exec daphne --proxy-headers -b 0.0.0.0 -p "${PORT:-8000}" BlackDiamondHub.asgi:application
