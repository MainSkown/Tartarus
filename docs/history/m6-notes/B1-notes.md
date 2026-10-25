# B1 notes (guest control client, read endpoints, aggregate guest health)

Baseline before any change: `uv run pytest -m "not integration" -q` = 3197 passed, 267 deselected.

## Done
- Read the plan, control service, engine shapes and backend patterns; captured real control-service answers
  (guests, profiles, media, a build status and log) into `backend/tests/guest/fixtures/` (lab1/lab2 passwords
  replaced by a fixture string).
- Settings, schemas, errors, client, health, routes, error handler, repository function, lifespan wiring, tests.
- Full run: `uv run pytest -m "not integration" -q` = 3307 passed, 1 xfailed (strict, the submission gate);
  ruff check, ruff format --check, mypy app all clean.

## Running
- nothing

## Next
- B5: let `degraded` through the submission gate (`_require_ready_guest` in app/api/analyses.py), then remove
  the xfail marker in tests/test_analyses_api.py and change the degraded case of the 409 test.
- Planner: regenerate the API client; the running backend image predates this code.

## Decisions / findings
- `_require_ready_guest` in `app/api/analyses.py` refuses every status except `ok` (degraded included), and
  `test_a_submission_is_refused_with_409_while_the_guest_is_not_ready` pins degraded -> 409. That file is out of
  bounds for B1, so the gate is NOT changed; a strict xfail test records the wanted behaviour for B5.
