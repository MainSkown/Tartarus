# B2 notes (guest build and clone job and its API)

Baseline before any change (B4's unfinished test file ignored): 3309 passed, 267 deselected, 1 xfailed.

## Done
- `paused` job status: model, migration 0006 (check constraint replaced; downgrade ends paused jobs as
  interrupted), `mark_paused`, `record_log`, `mark_running` clears the pause result, runner relay carries
  progress, log text, pause and resume in order; `JobContext.append_log/pause/resume`.
- `app/guest/selftest.py` (protocol, verdict, `NoSelfTest`), `log_tail.py` (dedup), `build_job.py` (handler,
  `BuildTracking`, `reattach_guest_builds`).
- API: POST /guests/build, POST /guests/{name}/clone, GET /guests/builds/active, GET /guests/builds/{id},
  POST /guests/builds/{id}/resume|restart|continue. main.py: handler registered, tracking on app.state,
  reattach after the runner started.
- Tests: repository, runner, ws, alembic (offline SQL), integration migration (Postgres testcontainer),
  handler, reattach, API, lifespan, routes.
- Full run: 3531 passed, 269 deselected; ruff check, ruff format --check, mypy app clean.

## Running
- nothing

## Next
- B3: implement `SelfTestRunner` and pass it to `guest_build_handler` in main.py instead of `NoSelfTest()`.
- Planner: regenerate the API client.

## Decisions
- A `paused` job left by a dead process is interrupted at start like `running` (its handler is gone; reattach
  submits a fresh tracking job). The brief said both "treat paused like running" and "paused is not
  interrupted at start"; the first is the one that works with decision 14.
- `reattach_guest_builds(control, tracking)`, not `(control, runner)`: the tracking object holds the runner.
- resume, restart and continue are also refused with 409 while an analysis needs a guest (they re-register).
- Moved `Harness` and its fixture out of tests/guest/test_api.py into tests/guest/harness.py (conftest
  exposes the fixture); `captured` moved to tests/guest/captured.py and is re-exported by conftest.
