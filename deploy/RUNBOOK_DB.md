# Database runbook (Postgres inside the stack)

Production Postgres is the `postgres` service in `docker-compose.yml`: `pgvector/pgvector:0.8.0-pg17`
(multi-arch amd64 + arm64), data in the named volume `pg_data`, reachable only on the compose
network (no host port). Every app service gets `DATABASE_URL` from `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB` in `.env` (use a URL-safe password: `openssl rand -hex 24`).
One database holds the app tables and the Stewards tables; the assistant migration creates
the `vector` extension, `pg_trgm` comes from migration 0024.

Memory: postgres limit 1.5 GB (`shared_buffers` 384 MB, `max_connections` 150), pgbackup 256 MB.

## Backups

The `pgbackup` service runs `pg_dump -Fc` (compressed custom format) at start and every
`BACKUP_INTERVAL_HOURS` (default 24) into the `pg_backups` volume, and deletes dumps older than
`BACKUP_RETENTION_DAYS` (default 14).

    make backup          # dump now
    make backups         # list
    make restore f=f1-20261124-084355.dump    # DESTRUCTIVE: stops web/workers/beat/flower, restores, restarts

Rehearse a restore without touching live data (scratch database):

    docker compose exec -T -e TARGET_DB=scratch pgbackup sh /scripts/restore.sh <file>

Copy dumps off the VM too (the volume lives on the same disk):

    docker run --rm -v <project>_pg_backups:/b -v "$PWD":/out alpine cp /b/<file> /out/

## Migrate from Neon (operator, once, on the VM)

The script only READS Neon (`pg_dump`) and replaces the data in the stack's database.

1. `cp .env.example .env`, set `POSTGRES_PASSWORD` and the rest; `make up` (the stack runs on an empty DB; the web entrypoint applies migrations, including the pgvector one).
2. Stop whatever writes to Neon (the old `start_prod.sh` stack) so the copy is consistent.
3. `make migrate-from-neon NEON_DATABASE_URL='postgres://...neon...?sslmode=require'`
   - checks the Neon major version is not newer than the image's `pg_dump` (17),
   - dumps to `/backups/neon-<stamp>.dump` and restores into the stack DB,
   - compares row counts per table between Neon and the stack, and exits 2 on any difference.
4. `make migrate-check` (`manage.py migrate --check` must pass; if the Neon DB was behind, run `make migrate`).
5. Smoke test, switch traffic, keep the Neon project for a few days as a fallback, then delete it.

Rollback: point `DATABASE_URL` back at Neon (set it in `.env` and remove the interpolated value in
`docker-compose.yml`) and restart; the stack DB is untouched by the script's reads.

Tested locally only with a fake "Neon" (a second database on the stack's own postgres). Never run against the real Neon by the agents.
