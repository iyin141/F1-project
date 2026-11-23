COMPOSE      ?= docker compose
DEV          = $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml
s            ?= web

.PHONY: build build-ml up up-ml down logs ps migrate shell test dev dev-down

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

test:             ## Run the suite locally (no .env needed; same command as CI). Needs pytest, pytest-django, pytest-asyncio.
	cd backend && python -m pytest -q

dev:
	$(DEV) up -d

dev-down:
	$(DEV) down
