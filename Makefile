.DEFAULT_GOAL := help
.PHONY: help dev up down logs test test-integration lint check api-sync screenshots preflight smoke verify-cape build-guest verify-guest e2e hooks

COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml

help: ## List the available targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-17s %s\n", $$1, $$2}'

dev: ## Run the stack with hot reload (compose watch)
	$(COMPOSE_DEV) up --build --watch

up: ## Run the stack detached, serving the production build
	docker compose up -d --build

down: ## Stop the stack
	docker compose down

logs: ## Follow the stack logs
	docker compose logs -f

test: ## Run backend and frontend unit tests
	cd backend && uv run pytest -m "not integration"
	cd frontend && npm run test:unit

test-integration: ## Run backend tests that need Docker
	cd backend && uv run pytest -m integration

lint: ## Run ruff, mypy, eslint and the TypeScript check
	cd backend && uv run ruff check
	cd backend && uv run ruff format --check
	cd backend && uv run mypy app
	cd frontend && npm run lint
	cd frontend && npm run typecheck

check: lint test test-integration screenshots ## Run everything: lint, unit and integration tests, and the screenshot harness

api-sync: ## Regenerate the frontend API client from the running backend (make dev first)
	cd frontend && npm run api:sync

screenshots: ## Capture the visual review screenshots
	cd frontend && npm run screenshots

preflight: ## Check host prerequisites
	scripts/preflight.sh

smoke: ## Smoke-test the stack: MODE=static (default, no daemon needed), prod or dev
	scripts/smoke.sh $(or $(MODE),static)

verify-cape: ## Prove the cape container's M0 checks with a throwaway guest (slow; restarts cape, leaves it stopped)
	scripts/verify-cape.sh

build-guest: ## Build the Windows analysis guest unattended and register it with CAPE (very slow)
	scripts/build-guest.sh

verify-guest: ## Prove acceptance checks 8-12 against the built guest (slow; needs make build-guest first)
	scripts/verify-guest.sh

e2e: ## End-to-end check against the running stack, up to date (make up) and with the built guest, slow: submit, live feed, views, Sigma rules (shipped set, the self-test alert live and final, disable and re-ingest), the query API, and the Events and Timeline tabs in a browser; DRILLS=1 adds the failure drills, DESKTOP=1 the interactive desktop (long)
	E2E_DRILLS=$(or $(DRILLS),0) E2E_DESKTOP=$(or $(DESKTOP),0) scripts/e2e.sh

hooks: ## Install the pre-commit tool and register the git hooks (once per clone)
	uv tool install pre-commit
	pre-commit install
