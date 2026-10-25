# Running the tests

Run every command from the repo root. `make help` lists the targets. The layers run from fastest to
slowest. Only the first two need no Docker and no KVM.

## Unit layers (no Docker, no KVM)

| Command | What it runs | Needs |
|---|---|---|
| `make test` | `test-cape`, `test-scripts`, then the backend `pytest -m "not integration"` and the frontend `npm run test:unit` | uv, Node 24 |
| `make test-cape` | pytest over `cape/tests/` (`uv run --no-project --with pytest`): the code that runs inside the `cape` container | uv |
| `make test-scripts` | The bash tests `scripts/tests/test_*.sh`, run against fakes. The `*_real.sh` ones need a real ISO and are skipped | bash. CI installs `poppler-utils` first |
| `make lint` | Backend: `ruff check`, `ruff format --check`, `mypy app`. `cape/`: ruff check and format. Frontend: `eslint --max-warnings 0` and `vue-tsc` | uv, Node 24 |

One file or one suite:

- Backend: `cd backend && uv run pytest tests/ingest -q`
- Frontend: `cd frontend && npm run test:unit -- tests/unit/i18n-keys.test.ts`
- Frontend lint and types: `cd frontend && npm run lint` and `npm run typecheck`

`make check` runs `lint`, `test`, `test-integration` and `screenshots`. It needs everything below.

## Integration layer (Docker)

| Command | What it runs | Needs |
|---|---|---|
| `make test-integration` | Backend tests marked `integration`. They start OpenSearch and Postgres with testcontainers | Docker. Without it the tests fail; they do not skip |

## Browser layer (local only)

| Command | What it runs | Needs |
|---|---|---|
| `make screenshots` | `npm run screenshots`: the Playwright specs in `frontend/tests/screenshots/`. Playwright starts the Vite dev server on port 5190 itself | Playwright's Chromium (`npx playwright install chromium`) |

It is slow, and CI does not run it. It produces the captures for the visual review in [the rules](the-rules.md).

## Stack checks

| Command | What it proves | Needs |
|---|---|---|
| `make smoke` | The compose files and the networks. `MODE=static` is the default and needs no daemon; `MODE=prod` and `MODE=dev` check the running stack (see `scripts/smoke.sh`) | Docker. CI runs the default mode |
| `make verify-cape-hardening` | The `cape` user cannot open the host's disks or run anything as root, each program holds only its own secrets, CAPE's web process serves the API only, and root-run code is not writable by `cape`. It starts no guest | `make up`, and the stack running |
| `make verify-cape` | The M0 checks of the `cape` container, with a throwaway Cirros guest. It starts postgres, restarts `cape` and leaves it stopped. Slow | KVM |

## Real-guest checks (manual)

These build or run a real guest. They are slow, and they stay out of CI.

| Command | What it proves | Needs |
|---|---|---|
| `make build-guest` | Builds the Windows guest unattended and registers it with CAPE. Settings are the `GUEST_*` variables in `.env` (see the header of `scripts/build-guest.sh`) | KVM, the stack up, and an installer ISO in `data/iso/` (`GUEST_ISO`). Very slow |
| `make verify-guest` | The guest's acceptance checks 8 to 12. It submits a benign sample built with mingw-w64 and leaves the guest powered off | `make build-guest` first |
| `make verify-isolation GUESTS="a b"` | A guest reaches only what its route allows, on every route. It starts the guests by reverting their snapshot if they are off | The stack up and two ready guests |
| `make verify-wizard SAMPLE=path` | The guest wizard's path through the public API: clone a ready guest, check the gates, run an analysis on it and delete it. About six minutes. `SAMPLE` is a harmless Windows `.exe` | The stack up and one ready guest |
| `make e2e` | The whole flow on the real stack: submit, live feed, views, Sigma rules, the query API, tags and notes, exports, reports, and the browser flows | `make up` on current code, and a built guest |

Options for `make e2e`:

- `DRILLS=1` adds the failure drills: it stops `cape` or OpenSearch and restarts the backend mid-run.
- `DESKTOP=1` adds the interactive desktop. It holds the guest for about ten minutes.
- `E2E_GUEST=<name>` pins every run to one guest. The Makefile does not set it, so it is read from the environment.
- `E2E_WIZARD=0` skips the wizard browser test, which builds, cancels and deletes a guest named `e2e-wizard`.
- `E2E_SKIP_UI=1` skips the browser tests.

## What CI runs

`.github/workflows/ci.yml` runs on every push and on manual dispatch.

- **backend:** `uv sync --frozen`, then `ruff check`, `ruff format --check`, `mypy app` and `pytest -m "not integration"`.
- **backend-integration:** `make test-integration`.
- **cape-and-scripts:** `ruff check` and `ruff format --check` on the `cape/` code, `make test-cape`, then `make test-scripts`.
- **frontend:** `npm ci` in `frontend/` and `frontend/src-pwa`, then `npm run lint`, `npm run typecheck` and `npm run test:unit`. Node 24.
- **compose-smoke:** `scripts/gen-env.sh` writes a throwaway `.env`, then `make smoke`.

Pre-commit runs ruff and eslint on the backend and frontend files you changed, and the backend and
frontend unit suites in full, before each commit (`.pre-commit-config.yaml`).
CI does not run `make check`.

## What stays manual

The real-guest checks above stay manual. The CI file says why: hosted runners have no nested KVM, so
no job can build or run a guest. The screenshot target and the `*_real.sh` scripts are also outside
CI; the `*_real.sh` scripts need a real ISO. Run the manual checks that a change touches on a machine
with KVM, and name them in the pull request.
