# Contributing to Tartarus

This folder is for a developer who wants to fix a bug or add a feature. The [specs](../specs/) say
*what* the system does; these pages say *how* to change it.

Read these first:

- [Architecture](architecture.md): the containers and the path of one analysis, on one page.
- [Running the tests](running-the-tests.md): every test layer, its command and what it needs.
- [The rules](the-rules.md): the coding rules the repo follows.

Then the page for your task:

- [Adding a guest profile](adding-a-guest-profile.md): support for another operating system.
- [Adding an event source](adding-an-event-source.md): a normaliser for a new source of events, and the fields it fills.
- [Adding a message key](adding-a-message-key.md): a new string in the GUI.

The threat model and the accepted risks are in [security](../security.md). Read it before you add a
route, a mount or a secret.

## Repository layout

| Path | What is in it | Spec |
|---|---|---|
| `backend/` | FastAPI app in `app/`, Alembic migrations in `alembic/`, tests in `tests/`. Python 3.12, run with `uv` | [backend](../specs/backend.md) |
| `frontend/` | Vue 3 and Quasar app in `src/`, unit tests in `tests/unit/`, Playwright tests in `tests/` | [GUI](../specs/gui.md) |
| `cape/` | The image that runs CAPE, KVM and libvirt, and the guest control service (`bin/`, `guest_engine/`). Tests in `tests/` | [CAPE integration](../specs/cape-integration.md) |
| `guest/` | What a guest is made of: `profiles/<os>/`, the generic `steps/`, the libvirt `domain/` and the SMBIOS `personas/` | [guest profiles](../specs/guest-profiles.md) |
| `rules/` | Sigma rules in `rules/sigma/`, mounted into the backend and editable by the analyst | [backend, Sigma engine](../specs/backend.md#sigma-engine) |
| `scripts/` | The scripts behind the `make` targets (`smoke.sh`, `e2e.sh`, `verify-*.sh`, `build-guest.sh`), their helpers in `lib/` and their tests in `tests/` | [running the tests](running-the-tests.md) |
| `docs/` | The overview, the architecture, the specs, the design system and these pages | [overview](../overview.md) |

At the root: `docker-compose.yml` and `docker-compose.dev.yml`, the `Makefile`, `.env.example`, the CI
workflow in `.github/workflows/ci.yml`, and `.pre-commit-config.yaml`. `data/iso/` is where you put
installation media; it is git-ignored.

## Set up

- A Linux host with Docker (Compose v2), `make`, and KVM (`/dev/kvm`) for the real stack.
  `make preflight` checks the host.
- Python 3.12 and [uv](https://docs.astral.sh/uv/). The backend and `cape/` tests run with `uv run`.
- Node 24. `frontend/package.json` allows `^24 || ^26`; CI uses 24.
- `make init-env` writes `.env` with random secrets. It never overwrites an existing `.env`.
- `make hooks` once per clone. It installs pre-commit, which runs ruff and eslint on the files you
  changed, and the unit suites, before each commit.

## Day to day

- `make dev` runs the stack with hot reload. The frontend is on `127.0.0.1:5173` and the backend on
  `127.0.0.1:8000`, whose OpenAPI page is `/docs`.
- `make up`, `make down` and `make logs` run the production build, stop it and follow it.
- After you change a backend route, run `make api-sync` with `make dev` running. It regenerates
  `frontend/src/api/`. Do not edit that folder by hand.
- `make test` and `make lint` before you commit. [Running the tests](running-the-tests.md) lists every target.
