COMPOSE      ?= docker compose
DEV          = $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
s            ?= web
APPS         = web beat flower worker-t1 worker-t2 worker-t3 worker-t4 worker-t5 worker-t6 worker-rag worker-ml


.PHONY: test-neon-migration backup restore backups migrate-from-neon migrate-check lint build build-ml up up-ml down logs ps migrate shell test dev dev-down

build:            ## Build the API/worker image
	$(COMPOSE) build web

build-ml: build   ## Build the ML worker image (needs the API image first)
	$(COMPOSE) --profile ml build worker-ml

up:               ## Start the production stack
	$(COMPOSE) up -d

up-ml:            ## Start the stack including the ML worker
	$(COMPOSE) --profile ml up -d

down:
	$(COMPOSE) down

logs:             ## make logs s=worker-t4
	$(COMPOSE) logs -f --tail=200 $(s)

ps:
	$(COMPOSE) ps

migrate:
	$(COMPOSE) run --rm web python manage.py migrate

shell:
	$(COMPOSE) run --rm web python manage.py shell

test:             ## Run the suite locally (no .env needed; same command as CI). Install first: pip install -r backend/requirements-dev.txt && pip install -r backend/requirements-rag.txt && pip install --no-deps fastembed==0.9.1
	cd backend && python -m pytest -q

lint:             ## Pyflakes-level ruff check (config: backend/ruff.toml)
	cd backend && ruff check .

backup:           ## Dump the database now into the pg_backups volume (the pgbackup service also does it on a schedule)
	$(COMPOSE) exec -T pgbackup sh /scripts/backup.sh once

backups:          ## List dumps
	$(COMPOSE) exec -T pgbackup ls -lh /backups

restore:          ## make restore f=f1-YYYYmmdd-HHMMSS.dump  (DESTRUCTIVE; stops the app services while restoring)
	@test -n "$(f)" || { echo "usage: make restore f=<dump name> (see make backups)"; exit 1; }
	$(COMPOSE) stop $(APPS)
	$(COMPOSE) exec -T pgbackup sh /scripts/restore.sh $(f)
	$(COMPOSE) up -d

migrate-from-neon: ## make migrate-from-neon NEON_DATABASE_URL=postgres://...  (READS Neon; run on the VM, see deploy/RUNBOOK_DB.md)
	@test -n "$(NEON_DATABASE_URL)" || { echo "set NEON_DATABASE_URL=..."; exit 1; }
	$(COMPOSE) up -d postgres pgbackup
	$(COMPOSE) stop $(APPS)
	$(COMPOSE) exec -T -e NEON_DATABASE_URL="$(NEON_DATABASE_URL)" pgbackup sh /scripts/migrate_from_neon.sh
	$(COMPOSE) run --rm --no-deps -e RUN_MIGRATIONS=0 web python manage.py migrate --noinput
	$(COMPOSE) run --rm --no-deps -e RUN_MIGRATIONS=0 web python manage.py migrate --check
	$(COMPOSE) up -d

test-neon-migration: ## Rehearse migrate_from_neon.sh against a fake Neon database on the stack's own postgres
	$(COMPOSE) exec -T pgbackup sh /scripts/test_migrate_from_neon.sh

migrate-check:    ## Fail if any migration is unapplied
	$(COMPOSE) run --rm --no-deps -e RUN_MIGRATIONS=0 web python manage.py migrate --check

dev:
	$(DEV) up -d

dev-down:
	$(DEV) down
