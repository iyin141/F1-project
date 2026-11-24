#!/bin/sh
# One-off: copy the production database from Neon into the stack's postgres. READS Neon (pg_dump and
# SELECTs only, never writes). Run on the VM by the operator through `make migrate-from-neon`, which
# first stops the app services (nothing may hold or write the stack DB) and afterwards runs `migrate`.
#
# Order matters (learned from the first real run):
#   1. wipe the stack's `public` schema (a DB already migrated by the web entrypoint has rows in
#      django_content_type / auth_permission that conflict with the dump);
#   2. restore ONLY Neon's `public` schema (`pg_dump -n public` leaves out Neon's `neon_auth` schema);
#   3. compare row counts for the tables that exist in Neon (stack-only tables, e.g. the v2 apps and
#      Django auth tables, are ignored);
#   4. `migrate` (run by the make target) applies what Neon did not have: trackmap, chaos, assistant,
#      and creates the pgvector extension.
set -eu
: "${NEON_DATABASE_URL:?set NEON_DATABASE_URL}" "${PGHOST:=postgres}" "${PGUSER:=f1}" "${PGDATABASE:=f1}"
OUT=/backups/neon-$(date -u +%Y%m%d-%H%M%S).dump
LOCAL_URL="postgres://$PGUSER:$PGPASSWORD@$PGHOST:5432/$PGDATABASE"

echo "== versions"
neon_v=$(psql "$NEON_DATABASE_URL" -Atc 'show server_version_num')
echo "neon server_version_num=$neon_v ; local client: $(pg_dump --version)"
[ "$neon_v" -lt 180000 ] || { echo "Neon is newer than this image's pg_dump; bump the postgres image first" >&2; exit 1; }

echo "== dump Neon schema public (read only) -> $OUT"
pg_dump "$NEON_DATABASE_URL" -n public -Fc --no-owner --no-acl -f "$OUT"

echo "== wipe the stack's public schema, then restore"
psql "$LOCAL_URL" -v ON_ERROR_STOP=1 -c 'DROP SCHEMA IF EXISTS public CASCADE;'   # the dump itself re-creates schema public
# --no-owner/--no-acl: no Neon roles exist here. Errors about extensions Neon has but this image lacks would show here.
pg_restore --no-owner --no-acl -d "$LOCAL_URL" --exit-on-error "$OUT"

echo "== row counts for every table that exists in Neon (stack-only tables ignored)"
tables=$(psql "$NEON_DATABASE_URL" -Atc "select tablename from pg_tables where schemaname='public' order by 1")
: > /tmp/neon_counts.txt; : > /tmp/local_counts.txt
for t in $tables; do
  echo "$t $(psql "$NEON_DATABASE_URL" -Atc "select count(*) from public.\"$t\"")" >> /tmp/neon_counts.txt
  echo "$t $(psql "$LOCAL_URL" -Atc "select count(*) from public.\"$t\"" 2>/dev/null || echo MISSING)" >> /tmp/local_counts.txt
done
if diff /tmp/neon_counts.txt /tmp/local_counts.txt; then
  echo "row counts identical for $(wc -l < /tmp/neon_counts.txt) Neon tables"
else
  echo "ROW COUNT DIFFERENCES above (< neon, > stack). If production wrote during the dump, stop the writers and re-run." >&2
  exit 2
fi
echo "== done; the make target now runs: manage.py migrate, then migrate --check"
