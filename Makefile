COMPOSE      ?= docker compose
DEV          = $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
s            ?= web


.PHONY: lint build build-ml up up-ml down logs ps migrate shell test dev dev-down

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

test:             ## Run the suite locally (no .env needed; same command as CI). Install first: pip install -r backend/requirements-dev.txt -r backend/requirements-rag.txt && pip install --no-deps fastembed==0.9.1
	cd backend && python -m pytest -q

lint:             ## Pyflakes-level ruff check (config: backend/ruff.toml)
	cd backend && ruff check .

dev:
	$(DEV) up -d

dev-down:
	$(DEV) down
