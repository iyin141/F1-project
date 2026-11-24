#!/bin/sh
# One-off: copy the production database from Neon into the stack's postgres. READS Neon (pg_dump only,
# never writes to it). Run on the VM by the operator:   make migrate-from-neon NEON_DATABASE_URL='postgres://...'
# Order: 1) stop the apps (make down is NOT needed, only the writers)  2) run this  3) check output  4) switch traffic.
set -eu
: "${NEON_DATABASE_URL:?set NEON_DATABASE_URL}" "${PGHOST:=postgres}" "${PGUSER:=f1}" "${PGDATABASE:=f1}"
OUT=/backups/neon-$(date -u +%Y%m%d-%H%M%S).dump

echo "== versions"
neon_v=$(psql "$NEON_DATABASE_URL" -Atc 'show server_version_num')
local_client=$(pg_dump --version)
echo "neon server_version_num=$neon_v ; local client: $local_client"
[ "$neon_v" -lt 180000 ] || { echo "Neon is newer than this image's pg_dump; bump the postgres image first" >&2; exit 1; }

echo "== dump from Neon (read only) -> $OUT"
pg_dump "$NEON_DATABASE_URL" -Fc --no-owner --no-acl -f "$OUT"

echo "== restore into $PGHOST/$PGDATABASE (replaces anything there)"
pg_restore --clean --if-exists --no-owner --no-acl -d "$PGDATABASE" "$OUT" || echo "(pg_restore reported errors above: objects that did not exist yet are expected on a fresh DB)"

echo "== row counts per table (neon vs stack)"
q="select format('select %L as t, count(*) as n from %I.%I', schemaname||'.'||relname, schemaname, relname) from pg_stat_user_tables order by 1"
# format() output is SQL text; run each statement and collect "table count"
run_counts() { psql "$1" -Atc "$q" | while read -r stmt; do psql "$1" -At -F ' ' -c "$stmt"; done | sort; }
run_counts "$NEON_DATABASE_URL" > /tmp/neon_counts.txt
run_counts "postgres://$PGUSER:$PGPASSWORD@$PGHOST:5432/$PGDATABASE" > /tmp/local_counts.txt
if diff /tmp/neon_counts.txt /tmp/local_counts.txt; then
  echo "row counts identical ($(wc -l < /tmp/local_counts.txt) tables)"
else
  echo "ROW COUNT DIFFERENCES above (< neon, > stack). Production may have written during the dump; re-run with the writers stopped." >&2
  exit 2
fi
echo "== next: make migrate-check   (runs 'manage.py migrate --check' against the stack)"
