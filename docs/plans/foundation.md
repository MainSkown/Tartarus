# Plan: foundation

Build the skeleton every later milestone plugs into: the compose stack, the backend skeleton and
the frontend skeleton. The CAPE container (M0 spike) is **not** part of this phase.

Work is split into subtasks along module boundaries and delegated by difficulty, per rule 5 in
[.claude/CLAUDE.md](../../.claude/CLAUDE.md). Rules 1–4 (self-documenting, test-first, no
duplication, frontend screenshot review) apply to every subtask regardless of model tier.

## Outcome

`make dev` starts Postgres, OpenSearch, the backend and the frontend. The browser shows the
Tartarus app shell in the ice-blue theme, with header health dots driven live by the real backend:
Postgres and OpenSearch green, CAPE and Guest red ("not set up yet"). The Settings page reads and
writes real data. Tests, lint and type checks pass, the API client is generated, and the shell
and Settings screens have passed screenshot review.

This phase also **establishes the templates** later Haiku-tier tasks copy: one CRUD vertical
slice (settings: migration → model → router → generated client → store → page), one live
WebSocket feed (`/ws/system`), one placeholder page pattern, and one visual-capture harness.

## Adjustments to the imported Momos compose files

| Momos | Tartarus |
|---|---|
| `momos-backend`, `momos-dashboard`, `momos-db`, `momos-ollama` | `backend`, `frontend`, `postgres`, `opensearch` (container names `tartarus-*`) |
| `pgvector/pgvector:pg16` | `postgres:16`, with an init script creating databases `tartarus` and `cape` (init scripts only run on an empty volume, so `cape` is created now even though M0 uses it later) |
| `ollama` service + NVIDIA GPU reservation | Removed |
| — | `opensearch` added (single node, security plugin off, heap from `.env`, `memlock` ulimits, healthcheck) |
| `/var/run/docker.sock` mounted in the backend | **Removed.** Never mounted anywhere (see architecture) |
| `ports: "8080:80"` on all interfaces | `127.0.0.1:8080:80`, and the frontend is the only published service in prod |
| `./backend:/app` mounted in prod | No source mounts in prod; images are self-contained |
| Dev: bind mounts **and** `develop.watch` sync, anonymous `/app/node_modules` volume | Dev: `develop.watch` only (sync source, rebuild on `pyproject.toml`/`uv.lock`/`package.json`), no bind mounts, so `.venv` and `node_modules` stay inside the image |
| Dev ports on all interfaces (`5173`, `8000`, `5432`) | Same ports plus OpenSearch `9200`, all bound to `127.0.0.1` |
| `depends_on` without conditions, hardcoded credentials | Healthchecks + `depends_on: condition: service_healthy`; credentials from `.env` |
| Build targets `prod`/`dev`, `production-stage`/`dev-stage` | Kept, same names |

## Prerequisites (documented in README, checked by `make preflight`)

- Docker with Compose ≥ 2.24.4 (`develop.watch`, and `ports: !override` in the dev override).
- `vm.max_map_count ≥ 262144` (OpenSearch).
- For running tests and codegen on the host: `uv` (Python 3.12) and Node ≥ 24 (images use Node 24 LTS) with npm.
  Tests run on the host, not in containers, so testcontainers uses the host Docker without
  mounting its socket anywhere.

## Shared contracts

Subtasks in the same wave run in parallel and must agree on these. They are the single source of
truth: if a subtask needs to change one, it says so in its report instead of silently diverging.

### Containers
| | backend | frontend |
|---|---|---|
| Dockerfile | `backend/Dockerfile` | `frontend/Dockerfile` |
| Build targets | `dev` (uvicorn `--reload`, dev deps), `prod` | `dev-stage` (Quasar/Vite dev server), `production-stage` (nginx) |
| Image tags | `tartarus-backend:latest` (prod), `tartarus-backend:dev` | `tartarus-frontend:latest` (prod), `tartarus-frontend:dev` |
| Base image | `python:3.12-slim` + uv | `node:24-alpine` (build/dev), `nginx:alpine` (prod) |
| `WORKDIR` | `/app` | `/app` |
| Listens on | `0.0.0.0:8000`, ASGI `app.main:app` | dev `0.0.0.0:5173`, prod `80` |
| Dependencies location | venv at `/opt/venv` (`UV_PROJECT_ENVIRONMENT`), so syncing source into `/app` never clobbers it | `/app/node_modules` inside the image |
| Proxy | — | `/api/` and `/ws/` → backend with WebSocket upgrade on `/ws/`; SPA fallback to `index.html`. Dev server: `API_PROXY_TARGET` (default `http://backend:8000`). Prod nginx: fixed `http://backend:8000` (nginx has no env substitution), `client_max_body_size 512m` on `/api/` |
| `develop.watch` | sync `./backend/app` → `/app/app`, `./backend/alembic` → `/app/alembic`; rebuild on `pyproject.toml`, `uv.lock` | sync `./frontend/src` → `/app/src`, `./frontend/public` → `/app/public`; rebuild on `package.json`, `package-lock.json`, `quasar.config.ts`, `src-pwa/package.json`, `src-pwa/package-lock.json` |

The explicit `image:` tags matter: without them, both compose files build into the same
auto-named image (`<project>-<service>`), so whichever target was built most recently silently
wins for *either* file — confirmed live: after `docker compose watch` built the `dev` target,
a plain `docker compose up -d` (no `-f`, no `--build`) started the frontend from the dev image
on the prod ports. `scripts/smoke.sh static`'s `distinct-build-image-tags` check catches this
class of bug without Docker.

### Environment (`.env`, from `.env.example`)
| Variable | Default | Used by |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `tartarus` | compose |
| `TARTARUS_PORT` | `8080` | compose (frontend published port) |
| `TZ` | `UTC` | all |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `tartarus` / `change-me` / `tartarus` | postgres, backend |
| `CAPE_DB_USER` / `CAPE_DB_PASSWORD` / `CAPE_DB_NAME` | `cape` / `change-me-too` / `cape` | postgres init script (CAPE uses it from M0) |
| `OPENSEARCH_HEAP` | `1536m` | opensearch |
| `LOG_LEVEL` | `info` | backend |
| `GUEST_VCPUS`, `GUEST_RAM_MB`, `GUEST_SUBNET`, `CAPE_REF`, `DEFAULT_ROUTE`, `DEFAULT_TIMEOUT`, `DISK_WARN_GB`, `DISK_BLOCK_GB` | per backend spec "Configuration" | later milestones (listed now, commented as such) |

Compose passes the backend `DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}`,
`OPENSEARCH_URL=http://opensearch:9200`, `ENVIRONMENT=production` (`development` in the dev
override), `LOG_LEVEL` and `TZ`.

### Health endpoint
`GET /api/system/health` always answers `200` while the backend is alive (compose uses it as the
liveness check). Body:
```json
{
  "postgres":   {"status": "ok",   "message": null},
  "opensearch": {"status": "ok",   "message": null},
  "cape":       {"status": "down", "message": "not set up yet"},
  "guest":      {"status": "down", "message": "not set up yet"}
}
```
`status` ∈ `ok`, `degraded`, `down`.

### Commands
| Make target | Runs |
|---|---|
| `dev` | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build --watch` |
| `up` / `down` / `logs` | `docker compose up -d --build` / `docker compose down` / `docker compose logs -f` |
| `test` | `cd backend && uv run pytest -m "not integration"`; `cd frontend && npm run test:unit` |
| `test-integration` | `cd backend && uv run pytest -m integration` (needs Docker; fails, never skips, if Docker is unavailable) |
| `lint` | `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app` (in `backend/`); `npm run lint`, `npm run typecheck` (in `frontend/`) |
| `check` | `lint`, `test`, `test-integration` (F10 adds `screenshots`) |
| `api-sync` | `cd frontend && npm run api:sync` (script added by F7; needs `make dev` running) |
| `screenshots` | `cd frontend && npm run screenshots` (script added by F10) |
| `preflight` / `smoke` | `scripts/preflight.sh` / `scripts/smoke.sh` |

Frontend npm scripts: `dev`, `build` (PWA mode), `lint`, `typecheck`, `test:unit`; later `api:sync`
(F7) and `screenshots` (F10).

### Tests
- Backend unit tests use fakes and need nothing running. Tests that need real Postgres or
  OpenSearch use testcontainers and carry `@pytest.mark.integration`.
- Shell scripts are tested with plain bash test scripts under `scripts/tests/`, stubbing external
  commands through `PATH`.

### Theme
`frontend/src/css/app.css` becomes the single source of the theme. `docs/design/tartarus-theme.css`
is moved there (not copied), and the docs link to the new path.

## Subtasks

Each subagent gets **only** the spec sections listed in its row. Every subtask is test-first: the
listed tests are written and seen failing before the implementation.

### Wave 1 (parallel)

| ID | Task | Model | Context to give | Deliverables | Tests first |
|---|---|---|---|---|---|
| **F1** | Repo scaffolding | Haiku | This plan; architecture "Repository layout" | `.gitignore`, `.env.example` (all vars from backend spec "Configuration"), `Makefile` (`dev`, `up`, `down`, `test`, `lint`, `check`, `api-sync`, `screenshots`, `preflight`), `scripts/preflight.sh`, `.pre-commit-config.yaml` (ruff, ruff-format, eslint, fast unit tests on changed files), empty `rules/sigma/custom/`, `data/iso/.gitkeep` | `preflight.sh` exits non-zero with a clear message when `vm.max_map_count` is low or Compose is too old (bats or a shell test with stubbed commands) |
| **F2** | Compose stack | Sonnet | This plan's adjustments table; architecture "Compose services" | `docker-compose.yml`, `docker-compose.dev.yml`, `docker/postgres/init/01-databases.sh`, OpenSearch settings | A smoke script (`scripts/smoke.sh`) asserting: only `127.0.0.1` ports published; prod publishes only `8080`; Postgres has both databases; OpenSearch cluster health is green or yellow |
| **F3** | Backend core | Sonnet | backend spec: module layout, REST conventions (error shape, operation ids), "Configuration", "API client", "Testing"; data-model "PostgreSQL" intro | `backend/` uv project (FastAPI, pydantic-settings, SQLAlchemy 2 async + asyncpg, Alembic async env, opensearch-py async, ruff, mypy, pytest, pytest-asyncio, httpx, testcontainers); `Dockerfile` with `dev` and `prod` targets; app factory + lifespan; config; error envelope + handlers; `operation_id` generator; DB session; OpenSearch client; `GET /api/system/health`; `conftest.py` with Postgres and OpenSearch testcontainer fixtures | Health returns `ok` per store when up and `down` with a message when a store is unreachable (one test per store); CAPE and guest report `down` "not set up yet"; error envelope shape for 404, 422 and unhandled errors; every route has an explicit `operation_id` (introspection test over `app.routes`); the app serves a valid schema at `/openapi.json` |
| **F4** | Frontend core | Sonnet | gui spec: intro, "Frontend structure"; design system: "Quasar setup", tokens; `frontend/src/css/app.css` (moved from `docs/design/tartarus-theme.css`) | Quasar CLI project (Vite, TypeScript, Pinia, Vue Router, PWA mode, npm); `Dockerfile` with `dev-stage` (Vite, proxy `/api` and `/ws` to `backend:8000`) and `production-stage` (nginx: PWA build, SPA fallback, `/api` + `/ws` proxy with WebSocket upgrade headers); `src/css/app.css` from the theme, `quasar.variables.scss`; dark mode; `boot/notify.ts` (four `tt-*` types); eslint, vue-tsc, vitest; PWA manifest | `notify` boot registers exactly the four types with the specified classes and timeouts; nginx config test (`nginx -t` in the image build) |

### Wave 2 (after F3)

| ID | Task | Model | Depends on | Context to give | Deliverables | Tests first |
|---|---|---|---|---|---|---|
| **F5** | Settings vertical slice, backend | Haiku | F3 | data-model `setting` table; backend spec `GET/PUT /settings` | Alembic migration `0001_settings`; model; Pydantic schemas with validation (route ∈ known routes, timeout 60–1200, thresholds positive, warn > block); router | GET returns defaults on an empty DB; PUT persists and validates (422 with error envelope for each invalid field); round trip survives a new session |
| **F6** | `/ws/system` health feed | Sonnet | F3 | backend spec "WebSockets" (`/ws/system`, message envelope) | WS endpoint pushing `health` on connect and every 5 s (and immediately on change); Pydantic message models exported into the OpenAPI schema so the client generator emits their types | Client receives `health` on connect; a store going down is pushed within one interval; message envelope `{type, ts, data}` validated against the model |

### Wave 3 (after F4 and F6)

| ID | Task | Model | Depends on | Context to give | Deliverables | Tests first |
|---|---|---|---|---|---|---|
| **F7** | API client + WS client | Sonnet | F4, F6 | backend spec "API client"; gui "Frontend structure" (`api/` generated, `services/`, `boot/api.ts`) | `@hey-api/openapi-ts` (same setup as Momos) with the script `"api:sync": "openapi-ts -i http://localhost:8000/openapi.json -o ./src/api"` (an `openapi-ts.config.ts` only for options the CLI flags can't express), generated client committed in `src/api/`; `boot/api.ts` (base URL, error interceptor raising `tt-error` toasts from the error envelope); `services/ws.ts` typed client with exponential reconnect | Interceptor maps the error envelope to a toast; `ws.ts` reconnects with backoff and exposes connection state; `npm run api:sync` twice produces no diff |

### Wave 4 (after F7, then F5 + F8, then F9)

| ID | Task | Model | Depends on | Context to give | Deliverables | Tests first |
|---|---|---|---|---|---|---|
| **F8** | App shell | Sonnet | F6, F7 | gui "App shell", "Routes", "States and feedback"; design system components | `MainLayout` (header: wordmark, CAPE/Guest/Store health dots with tooltips, `+ SUBMIT` disabled with reason while the guest isn't ready; mini drawer: Dashboard, Rules, Guest VM, Settings); router with all top-level routes; `system` store fed by `/ws/system` with REST fallback; "Reconnecting…" bar; `HealthDot` and `TerminalEmpty` components; placeholder pages using `TerminalEmpty` (`> not implemented yet`) | Store maps health payloads to dot states; reconnect bar shows when the WS drops; Submit is disabled with the guest-not-ready reason; routes render their pages |
| **F9** | Settings page | Haiku | F5, F8 | gui "Settings"; design system form components | Settings page (defaults: route, timeout, interactive; disk thresholds) using the generated client, floating-label inputs, segmented route radio, `tt-success` toast on save, inline validation errors from the API | Loads and shows values; save calls PUT and toasts; a 422 shows the field error inline |
| **F10** | Visual capture harness | Sonnet | F8, F9 | CLAUDE.md rule 4; gui "States and feedback" | Playwright (devDependency) script `npm run screenshots` that starts the dev frontend, mocks `/api` and `/ws` per scenario, and writes labelled PNGs: shell healthy, shell with OpenSearch down, shell reconnecting, shell at 1024 px width, each placeholder page, settings loaded / loading / validation error / saved toast | The harness itself is checked by producing the full set without errors in CI-less `make check` |

### Wave 5 (integration and review, done by the planner)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F11** | Integration | Sonnet | `make dev` and `make up` both come up healthy; `scripts/smoke.sh` passes against both; `make check` green; README quick start updated for dev |
| **F12** | Screenshot review | Planner | Run `make screenshots`, self-check for overflow, clipping and alignment (rule 4 step 3), publish one Artifact for the shell and one for Settings, address comments until approved |

No Opus-tier subtask in this phase: nothing here is ambiguous or cross-cutting enough. The first
Opus task is the M0 CAPE spike.

## Dependency graph

```
F1 ────────────────────────────────────────────┐
F2 ────────────────────────────────────────────┤
F3 ──┬─► F5 ─────────────────────┐             ├─► F11 ─► F12
     └─► F6 ──┐                  ├─► F9 ─► F10 ┘
F4 ───────────┴─► F7 ─► F8 ──────┘
```

Critical path: F3 → F6 → F7 → F8 → F9 → F10 → F11 → F12. F1, F2, F4 and F5 run alongside it.

## Acceptance criteria

- `make dev` brings up all four services healthy, publishing only on `127.0.0.1`; frontend HMR
  and backend reload work on file save.
- `make up` serves the PWA at `http://127.0.0.1:8080`; `/api/system/health` and `/ws/system`
  work through nginx; nothing else is published.
- Health: Postgres and OpenSearch `ok`, CAPE and Guest `down` with "not set up yet". Stopping the
  OpenSearch container turns its dot red within ~5 s, and starting it again turns it green.
- Settings changes persist across `make down && make up`.
- `make check` runs ruff, mypy, pytest, eslint, vue-tsc, vitest and the screenshot harness, all
  green.
- `make api-sync` is idempotent, and generated function names match the backend operation ids.
- The shell and Settings screenshots are approved on their review Artifacts.

## Out of scope for this phase

CAPE container and guest; analyses, events and every feature view; OpenSearch index templates
(they arrive with the first event-writing feature); job runner and queue runner; CI pipeline
(no git remote yet; `make check` is the gate until one exists).
