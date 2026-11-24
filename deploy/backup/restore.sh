#!/bin/sh
# Restore a dump from /backups into the stack's database. DESTRUCTIVE: replaces current data.
# Run through `make restore f=f1-YYYYmmdd-HHMMSS.dump` (stops the app services first).
#   TARGET_DB  database to restore into (default $PGDATABASE; use a scratch name to rehearse)
set -eu
: "${PGHOST:=postgres}" "${PGUSER:=f1}" "${PGDATABASE:=f1}"
f="${1:?usage: restore.sh <dump file name in /backups>}"
DB="${TARGET_DB:-$PGDATABASE}"
[ -f "/backups/$f" ] || { echo "no such backup: /backups/$f" >&2; ls -1 /backups >&2; exit 1; }
if [ "$DB" != "$PGDATABASE" ]; then
  dropdb --if-exists "$DB"; createdb "$DB"
fi
# --clean --if-exists drops objects before recreating them; errors from objects that do not exist yet are harmless.
pg_restore --clean --if-exists --no-owner --no-acl -d "$DB" "/backups/$f"
echo "restored $f into $DB"
