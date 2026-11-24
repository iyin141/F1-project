#!/bin/sh
# Scheduled pg_dump sidecar. Runs inside the pgbackup service (same image as postgres, so the
# client always matches the server). Custom format (-Fc) is compressed and restorable with pg_restore.
#   BACKUP_INTERVAL_HOURS  hours between dumps (default 24)
#   BACKUP_RETENTION_DAYS  dumps older than this are deleted (default 14)
set -eu
: "${PGHOST:=postgres}" "${PGUSER:=f1}" "${PGDATABASE:=f1}"
INTERVAL=$(( ${BACKUP_INTERVAL_HOURS:-24} * 3600 ))
KEEP=${BACKUP_RETENTION_DAYS:-14}
DIR=/backups

dump_once() {
  stamp=$(date -u +%Y%m%d-%H%M%S)
  tmp="$DIR/.f1-$stamp.partial"
  if pg_dump -Fc --no-owner --no-acl -f "$tmp"; then
    mv "$tmp" "$DIR/f1-$stamp.dump"
    echo "backup ok: f1-$stamp.dump ($(du -h "$DIR/f1-$stamp.dump" | cut -f1))"
  else
    rm -f "$tmp"; echo "backup FAILED" >&2
  fi
  find "$DIR" -name 'f1-*.dump' -mtime +"$KEEP" -print -delete | sed 's/^/pruned: /'
}

if [ "${1:-}" = "once" ]; then dump_once; exit 0; fi
until pg_isready -q; do sleep 2; done
while true; do dump_once; sleep "$INTERVAL"; done
