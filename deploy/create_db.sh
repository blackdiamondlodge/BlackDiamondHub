#!/usr/bin/env bash
# Create (or bring up to date) a hub database and its two logins.
#
#   hub_admin  owns the tables; the container uses it only for the startup
#              backup + migrations (DB_MIGRATE_USER).
#   hub_app    what the running site connects as (DB_USER): read/write rows,
#              no DDL, so a bad request can't drop or alter tables.
#
# Run on the Postgres host as a superuser, passwords in the environment:
#
#   sudo -u postgres env HUB_ADMIN_PASSWORD=... HUB_APP_PASSWORD=... \
#       bash create_db.sh homehub
#
# Safe to re-run: existing roles get their password reset, grants are reapplied.
# Remember pg_hba.conf must allow the hub server to reach this database.
set -euo pipefail

DB="${1:?usage: create_db.sh <database>}"
: "${HUB_ADMIN_PASSWORD:?set HUB_ADMIN_PASSWORD}"
: "${HUB_APP_PASSWORD:?set HUB_APP_PASSWORD}"
ADMIN="${HUB_ADMIN_USER:-hub_admin}"
APP="${HUB_APP_USER:-hub_app}"

psql -v ON_ERROR_STOP=1 -q -d postgres \
  -v admin="$ADMIN" -v app="$APP" \
  -v admin_pw="$HUB_ADMIN_PASSWORD" -v app_pw="$HUB_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'admin')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'admin') \gexec
SELECT format('CREATE ROLE %I LOGIN NOINHERIT', :'app')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app') \gexec
ALTER ROLE :"admin" LOGIN PASSWORD :'admin_pw';
ALTER ROLE :"app" LOGIN NOINHERIT PASSWORD :'app_pw';
SQL

if ! psql -tAq -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$DB'" | grep -q 1; then
  createdb "$DB"
fi

psql -v ON_ERROR_STOP=1 -q -d "$DB" -v admin="$ADMIN" -v app="$APP" -v db="$DB" <<'SQL'
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"admin", :"app";
GRANT USAGE, CREATE ON SCHEMA public TO :"admin";
GRANT USAGE ON SCHEMA public TO :"app";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"app";
SQL

echo "database $DB ready: owner login $ADMIN, site login $APP"
