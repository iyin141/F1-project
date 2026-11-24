#!/bin/sh
# Rehearsal of migrate_from_neon.sh without Neon: builds a fake "Neon" database (a second DB on the
# stack's postgres) with a public table, a neon_auth schema and rows, runs the script against it and
# checks the result. Needs only the postgres + pgbackup services.
#   MSYS_NO_PATHCONV=1 docker compose exec -T pgbackup sh /scripts/test_migrate_from_neon.sh
set -eu
: "${PGHOST:=postgres}" "${PGUSER:=f1}" "${PGDATABASE:=f1}"
FAKE=fakeneon
dropdb --if-exists "$FAKE"; createdb "$FAKE"
psql -d "$FAKE" -v ON_ERROR_STOP=1 -q <<'SQL'
create table public.race (id serial primary key, name text);
insert into public.race(name) select 'r' || g from generate_series(1, 50) g;
create table public.django_migrations (id serial primary key, app text, name text);
insert into public.django_migrations(app, name) values ('api', '0024_trigram_extension');
create schema neon_auth; create table neon_auth.users_sync (id int);
SQL
# stack side: pretend the web entrypoint already migrated (stack-only table + conflicting rows)
psql -d "$PGDATABASE" -q -c 'create table if not exists public.stack_only (id int); insert into public.stack_only values (1);'
NEON_DATABASE_URL="postgres://$PGUSER:$PGPASSWORD@$PGHOST:5432/$FAKE" sh /scripts/migrate_from_neon.sh
n=$(psql -d "$PGDATABASE" -Atc 'select count(*) from public.race')
[ "$n" = 50 ] || { echo "FAIL: expected 50 race rows, got $n" >&2; exit 1; }
s=$(psql -d "$PGDATABASE" -Atc "select count(*) from information_schema.schemata where schema_name='neon_auth'")
[ "$s" = 0 ] || { echo "FAIL: neon_auth was restored" >&2; exit 1; }
o=$(psql -d "$PGDATABASE" -Atc "select to_regclass('public.stack_only') is null")
[ "$o" = t ] || { echo "FAIL: stack public schema was not wiped" >&2; exit 1; }
dropdb "$FAKE"
echo "PASS: migrate_from_neon.sh (public only, wiped target, neon_auth excluded, counts compared)"
