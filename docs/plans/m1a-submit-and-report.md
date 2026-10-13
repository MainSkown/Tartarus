# Plan: M1a, submit a sample and see its result

The first time the pieces meet. From the browser you submit a file, watch it queue, run in the
Windows guest and finish, and read its score and detections. It connects what M0 proved (CAPE and
the guest) to what the foundation built (backend, API client, app shell), and it replaces the
"not set up yet" placeholders with real health.

M1b (the views that explore a report: processes, network, artifacts, detections, and the events
index behind them) is sketched at the end and planned once M1a shows what a real report needs.

Delegation follows rule 5 of [.claude/CLAUDE.md](../../.claude/CLAUDE.md): Haiku and Sonnet only,
never Opus. Every subtask is test-first, and every agent keeps a notes file so an interrupted run
can resume. Waves are at most four agents, because usage limits have already interrupted a long run.

## Outcome

With `make up`:
- The header's CAPE and Guest dots are green, and `+ SUBMIT` is enabled.
- Submitting `benign.exe` (or any Windows file) shows it on the Dashboard as queued, starting,
  running, processing, then done, in about two minutes for the test sample.
- Its page shows the status, timings, the malware score, the highest severity and the list of
  signatures and ATT&CK techniques that CAPE reported.
- A second submission made while one is running waits in the queue and runs afterwards.
- A queued analysis can be cancelled; a finished one can be deleted, which removes its CAPE task,
  its sample and its rows.

## What exists and what is new

| Exists | New in M1a |
|---|---|
| CAPE container, the `win` guest at 192.168.150.10 with the `tartarus-clean` snapshot, `make verify-guest` | `cape` joins the default stack; its API is called by the backend |
| Backend: health, Settings, `/ws/system`, error envelope, migrations on start | `sample` and `analysis` tables, a CAPE client, submission, a queue and status tracker, the callback, real CAPE and guest health, analysis endpoints |
| Frontend: shell, Settings, generated client, screenshot harness | Dashboard, Submit dialog, analysis page with a summary tab |

## Decisions in this plan (change them before work starts, not during)

1. **`cape` is part of the default stack**, so `make up` and `make dev` give a working sandbox. The
   service loses its compose profile. A machine without `/dev/kvm` can still run the UI work with
   `docker compose up postgres opensearch backend frontend`; `make preflight` already warns.
2. **The callback is a hint, not a fact.** CAPE's `callback` module posts `{"task_id": N}` and
   cannot send a secret. The backend never trusts it: on a callback it asks CAPE's API for the
   task's state and reads the report only if CAPE says `reported`. A callback for an unknown task
   (`make verify-guest` produces some) is ignored with a 200. The endpoint is reachable only on
   the internal network because the backend publishes no port.
3. **The backend submits to CAPE only when the last analysis has finished**, as the spec says
   (one at a time, which also makes "cancel a queued analysis" possible). CAPE has its own
   queue, but cancelling there is awkward.
4. **Status comes from polling** `GET /api/analyses/{id}` every 2 seconds while not finished. The
   `/ws/analyses/{id}/live` feed is M2.
5. **Deferred options.** The Submit dialog's "interactive desktop" and "full memory dump +
   Volatility3" are left out: guacd's desktop proxy is M2, and Volatility3 and its symbol tables
   are not installed. Route, timeout and package are in.
   **Tags are out of M1a too**: they live in the annotation tables (`tag`, `tag_link`), which belong
   to M5, so there is nowhere to store them yet. The Dashboard has no tags column and
   `GET /analyses` has no `tag` filter.
6. **Samples are stored encrypted at rest** (an AES zip, password `infected`, via `pyzipper`) in a
   backend-only volume. Downloads in M1b reuse the same zip. The upload is streamed to a temp file,
   hashed, forwarded to CAPE, then zipped; it is never held in memory.
7. **A small `summary` is stored on the analysis** (JSON: signatures with severity, ATT&CK
   techniques, process count, network counts, duration), because the Dashboard and the summary tab
   need it before M1b's index exists. It is a spec change to the `analysis` table in
   [data-model](../specs/data-model.md), made by the planner when the migration lands.

## Shared contracts

Binding for every subtask, as in the foundation plan. A subtask that needs to change one says so
in its report instead of diverging.

### Environment and wiring
| Item | Value |
|---|---|
| Backend settings (new) | `CAPE_API_URL` default `http://cape:8000`, `CAPE_API_TOKEN` (from `.env`), `CAPE_STORAGE_PATH` default `/cape-storage`, `SAMPLE_STORE_PATH` default `/data/samples`, `GUEST_LABEL` default `win` |
| Volumes | `cape-storage` mounted **read-only** at `/cape-storage` in `backend`; new volume `sample-store` at `/data/samples`, backend only |
| Compose | `backend` `depends_on` `cape` (healthy); `cape` has no profile; the callback URL is `http://backend:8000/internal/cape/callback` |
| CAPE config | `callback` reporting enabled in `cape/conf/reporting.conf`. `verify-guest.sh` overrides it temporarily through `reporting.conf.d/callback.conf` and removes only that file |
| API token | The backend sends `Authorization: Token $CAPE_API_TOKEN` |

### CAPE API behaviour (captured from the real container, fixtures in `backend/tests/fixtures/cape/`)
- **Errors come back as HTTP 200** with `{"error": true, "error_value": "..."}`; only a missing or
  wrong token gives a real 401 (`{"detail": "Authentication credentials were not provided."}`).
  Success spells the field two ways: `{"error": false, "data": ...}` for task calls and
  `{"error": [], "data": ...}` for `cuckoo/status` and `machines/list`. The client treats any
  truthy `error` (true or a non-empty list) as a failure, and an unreadable body as one too.
- `tasks/status/{id}/` returns `{"error": false, "data": "reported"}`; an unknown task returns
  `{"error": true, "error_value": "Task does not exist"}`.
- **`tasks/delete/{id}/` is disabled by default** ("Task Deletion API is Disabled"). A3 enables
  it in `cape/conf/api.conf` (the `[taskdelete]` section; confirm the name in CAPE's source) and
  the client's delete relies on that.
- `machines/list/` shows an idle guest as `status: "poweroff"`, `locked: false`, `reserved: false`:
  the guest is **ready when it is listed under `GUEST_LABEL` and not locked**, not when it runs.
- `tasks/view/{id}/` carries `added_on`, `started_on`, `completed_on`, `reporting_finished_on`,
  `status`, `machine`, `route`, `package` and `timedout`; those feed the analysis timings.

- **Deleting needs the task's status unless it is `reported`.** CAPE's `validate_task` refuses
  anything else ("Task failed", "Task is still being analyzed"). To delete a failed task, call
  `tasks/delete/{id}/{status}/` with the task's own current status; the client's
  `delete_task(task_id, task_status=...)` does that. A running task cannot be deleted at all, so
  `DELETE /analyses/{id}` stays `409` while running. A success carries no `error` key
  (`{"data": "Task(s) ID(s) 6 has been deleted"}`); a refused delete says only `failed`, so it
  cannot be told from a missing task.
- **Task statuses** (all 11, from `ALL_DB_STATUSES` in `lib/cuckoo/core/data/task.py`, checked
  against the image): `pending`, `running`, `completed`, `reported`, `failed_analysis`,
  `failed_processing`, `failed_reporting`, `banned`, `recovered`, `distributed`,
  `distributed_completed`. `app/cape/status.py` maps all of them; `done` is deliberately not in the
  mapper because only the backend, after reading the report, can say it.
- **The client's public interface lives in `app/cape/`** (`CapeClient`, the `CapeError` hierarchy
  with `CapeUnreachable` for "retry later" and `CapeRejected` for "CAPE said no", `TaskView`,
  `Machine`, `CapeProgress`, `CapeCheck`, `GuestCheck`). Read the code, not this plan, for
  signatures. `create_file_task` returns the new CAPE task id and sends no `options` and no tags.

### The tables as built (`app/db/models/`, `app/db/analysis_repository.py`)
- Import `AnalysisStatus`, `AnalysisPhase`, `Severity` and `ACTIVE_STATUSES` from
  `app.db.models.analysis`, never copy the lists. Statuses are stored as text with a CHECK
  constraint (not native enums, which are painful to migrate); `phase` defaults to `live`.
- `create_analysis(session, *, sample_sha256, filename, options)` always creates `queued`;
  `update_analysis(session, id, **changes)` raises `TypeError` on an unknown field; each write
  commits. `get_active_analysis` and `get_oldest_queued_analysis` are for the tracker. Deleting an
  analysis never deletes its sample (`delete_sample_if_unreferenced` does, when nothing refers to it).
- **`add_sample_if_new` is get-then-insert**, so two identical uploads at the same moment can race
  and raise `IntegrityError`. The submission path catches it and reads the existing sample.
- `analysis.summary` is JSON with **no schema yet**: A5 defines it as a Pydantic model next to
  the report reader, stores `model_dump()`, and exposes it in the API schema.
- `AnalysisFilter.tag` exists and is a documented no-op (tags are M5); the API does not expose it.

### Analysis states
`queued` (not yet sent to CAPE), `starting` (CAPE pending), `running`, `processing` (CAPE
completed or reporting), `ingesting` (CAPE reported, reading the report), `done`, `failed`,
`report_failed`, `cancelled`. CAPE's own statuses map onto these in one place (the CAPE client's
status mapper), whose list is checked against CAPE's source (`TASK_*` in
`lib/cuckoo/core/database.py`), not guessed. Terminal states: `done`, `failed`, `report_failed`,
`cancelled`.

### Endpoints (shapes follow [backend](../specs/backend.md); only these exist in M1a)
| Method and path | Notes |
|---|---|
| `POST /api/analyses` | multipart: `file`, `options` JSON (`route`, `timeout` 60 to 1200, `package` default `auto`). `201` with the analysis. `409` if the guest is not ready |
| `GET /api/analyses` | Paged, newest first; `q` (name or hash substring), `status` |
| `GET /api/analyses/{id}` | Detail, including `summary` once known |
| `POST /api/analyses/{id}/cancel` | Only while `queued`; otherwise `409` |
| `DELETE /api/analyses/{id}` | `409` while running; otherwise removes the CAPE task, the sample if unreferenced, and the rows |
| `POST /internal/cape/callback` | `{task_id}`; see decision 2. Not in the OpenAPI client |
| `GET /api/system/health` | `cape` is `ok` when `apiv2/cuckoo/status/` answers with the token; `guest` is `ok` when `apiv2/machines/list/` lists `GUEST_LABEL` |

Operation ids follow `<tag>_<name>` (`analyses_create`, `analyses_list`, `analyses_read`,
`analyses_cancel`, `analyses_delete`). Errors use the existing envelope.

### Tables
`sample` and `analysis` exactly as in [data-model](../specs/data-model.md), plus
`analysis.summary jsonb` (decision 7). Severity maps from CAPE's signature severity: 1 low,
2 medium, 3 high, 4 or more critical (the design system's scale).

### Frontend
Routes `/` (Dashboard) and `/analyses/:id` with a `summary` tab. The Submit dialog opens from the
header button and from the Dashboard's empty state. Uploads use the generated client's multipart
support, not a hand-written `fetch`. Status badges, severity badges and the dialog follow the
[design system](../design/design-system.md).

## Subtasks

Models are the cheapest tier that can do the job. Each agent gets only the spec sections it needs.

### Wave 1 (parallel)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **A1** | `sample` and `analysis` tables | Haiku | Models, schemas, repository functions, Alembic migration `0002` (applies cleanly on a database that already has `0001`) | Create, read, list with filters and paging, delete cascades; migration upgrade and downgrade on a real Postgres (testcontainers) |
| **A2** | CAPE client | Sonnet | Owns the new backend settings and the `httpx` runtime dependency. `app/cape/`: async client for `tasks/create/file` (with `machine`, `route`, `timeout`, `package`), `tasks/status`, `tasks/delete`, `cuckoo/status`, `machines/list`; token auth; typed results; one status mapper onto the analysis states; errors that name the failing call without leaking the token | Against a fake HTTP transport serving the captured fixtures (401 without a token, `error: true` on HTTP 200, both spellings of `error`, status progression, a failed task); the mapper covers every `TASK_*` value from CAPE's source |
| **A3** | Compose and CAPE wiring | Sonnet | `cape` without a profile, `[taskdelete]` enabled in `cape/conf/api.conf`, `backend` env and mounts, `sample-store` volume, the callback in `cape/conf/reporting.conf`, `.env.example`, `verify-guest.sh` adjusted so its temporary callback leaves the permanent one alone, `make preflight` and README notes | `smoke.sh static` cases first (cape-storage mounted read-only into backend; only `cape` privileged; no new published ports; both compose files agree on image tags); then `make up` healthy and `make verify-guest` still 12 of 12 |

### Wave 2 (after Wave 1; four agents, disjoint files)

| ID | Task | Model | Depends | Deliverables | Tests first |
|---|---|---|---|---|---|
| **A4** | Status tracker and queue | Sonnet, extra care | A1, A2 | `app/analyses/runner.py`: submits the next `queued` analysis when none is active, polls CAPE every 2 seconds, moves states, persists them so a backend restart resumes tracking, ends an analysis as `failed` (with a message) when CAPE disappears or reports failure. Starts from the app lifespan | A test that every `CapeProgress` value except `unknown` is a valid `AnalysisStatus` (the two lists must not drift); pure state-machine tests over a fake CAPE client for every path (happy path; CAPE fails; CAPE unreachable for a while then back; backend restart mid-run; cancel while queued; two queued run in order); one integration test against Postgres |
| **A5** | Submission, callback and report summary | Sonnet | A1, A2 | `POST /analyses`, `GET /analyses`, `GET /analyses/{id}`, cancel and delete; the sample store (stream, hash, forward, encrypted zip); `POST /internal/cape/callback`; the summary reader that turns `report.json` into `analysis.summary` and `score` and `max_severity` | Validation (size, timeout range, route list), `409` when the guest is not ready, a callback for an unknown task is ignored, a callback never causes a read before CAPE confirms `reported`; the summary reader runs against a trimmed real `report.json` fixture (about 600 KB untrimmed, from task 6 on the volume: keep signatures, TTPs, counts and a few calls, drop the rest) |
| **A6** | Real CAPE and guest health | Haiku | A2 | Replace `NotConfiguredCheck` for `cape` and `guest` with checks through the client, reusing `collect_health`'s timeouts, so `/ws/system` and the REST route both report them | `ok`, `degraded` (CAPE up, guest not listed) and `down` cases with the fake client; the old "not set up yet" assertions updated |
| **A7** | Frontend API client and stores | Sonnet | A5 (contract only; regenerated by the planner once A5 lands) | `analyses` Pinia store (list, detail, submit, cancel, delete, 2-second polling while an analysis is not finished); the Submit button enabled from `system.guestReady` | Store tests against a mocked client for each action and for polling start and stop |

The planner wires the shared files (`app/api/__init__.py`, `app/main.py` lifespan, `routes.ts`,
`MainLayout.vue`) after Wave 2, runs the full gate and regenerates the client with `api:sync`.

### Wave 3 (frontend pages, parallel, after the client is regenerated)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **A8** | Dashboard | Sonnet | The analyses table (name, SHA256 prefix, submitted, status badge, score, severity badge), search and status filter, the empty states from the GUI spec (no analyses yet; guest not ready), row actions, delete with a confirmation dialog | Component tests for rows, filters, empty states and the delete confirmation |
| **A9** | Submit dialog | Sonnet | The dialog from the GUI spec without the deferred options: drop zone, route (segmented radio), timeout, package; shows the hash after selection; disabled with the reason when the guest is not ready; navigates to the new analysis | Component tests for validation, the disabled reason, and the submit call; 422 messages shown inline as on the Settings page |
| **A10** | Analysis page and summary tab | Sonnet | Header (id, name, hash, status, timing), the summary tab (score, severity, signatures, ATT&CK techniques, counts), a queued position, failure banners, cancel and delete | Component tests for each state: queued, running, processing, done with and without detections, failed, report failed |

### Wave 4 (planner, with one agent)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **A11** | End to end | Sonnet | `scripts/e2e.sh` (`make e2e`): on a fresh `make up`, submits `benign.exe` through the real API, waits for `done`, asserts the score and signatures, then submits two at once and checks the order; screenshot scenarios for every new state; failure drills (stop `cape` mid-run; restart the backend mid-run) |
| **A12** | Review | planner | The screenshots published as Artifacts, one per screen, comments addressed, as rule 4 requires |

## Acceptance criteria

- `make up` brings up a healthy stack including `cape`; the CAPE and Guest dots are green and
  `+ SUBMIT` is enabled. Stopping `cape` turns both dots red and disables the button with the reason.
- `make e2e` passes on a fresh stack: a submitted sample reaches `done` with a score and a
  signature list; two submitted at once run in order.
- Killing `cape` mid-run ends the analysis as `failed` with a message and the queue moves on after
  `cape` returns; restarting the backend mid-run resumes tracking and still ends `done`.
- A callback for an unknown task is ignored; a forged callback for a running task does not make the
  backend read a report CAPE has not finished.
- Cancelling a queued analysis and deleting a finished one leave no CAPE task, sample file or rows.
- `make check` is green, `make verify-cape` 28 of 28 and `make verify-guest` 12 of 12 still pass,
  and every new screen has passed screenshot review.

## M1b sketch (planned after M1a)

The events behind the exploring views. The core is the normaliser interface: one protocol, an
implementation for capemon's API calls from `report.json`, and the derived events (a process, file,
registry or network event derived from the raw call), writing ECS documents into one OpenSearch
index per analysis through a bulk indexer. That is the hard design task, so it gets the extra-care
treatment (small steps, each ending in a failing-first check). On top of it: process tree, network,
artifacts and detections endpoints, and the Processes (Cytoscape), Network, Artifacts and Detections
tabs. The query language and Events tab stay in M3, the live feed in M2.

## Risks

| Risk | Handling |
|---|---|
| The queue and status tracker is the subtle part (restarts, CAPE outages) | Pure state machine behind a fake CAPE, one test per path; extra care per rule 5 |
| CAPE's status vocabulary differs from what the M0 runs showed | A2 reads CAPE's source for the full list and tests the mapper against all of it |
| An upload of up to 512 MB through nginx and the backend | Stream to a temp file, never buffer in memory; the foundation already set the nginx limit |
| A callback arrives before the report is fully written | The backend waits for CAPE's `reported` status; the callback only triggers an early check |
| The real report is large (600 KB for one minute) | Fixture trimmed for tests; M1a reads it once and keeps only the summary |
| Agents report results optimistically | The planner re-runs the gate and `make e2e` itself before every commit |
