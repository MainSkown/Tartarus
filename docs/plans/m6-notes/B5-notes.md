# B5 notes (choosing a guest for each detonation)

Baseline before any change: `uv run pytest -m "not integration" -q` = 3334 passed, 267 deselected, 1 xfailed
(the strict xfail of B1's gate).

## Plan (each step ends in a check that can fail)
1. `app/analyses/guest_choice.py`: pure `choose_guest` (defaults, gate) and `check_package`. Unit tests first.
2. `guest` option, `default_guest` setting (schema, repository, API).
3. `app/analyses/submission.py`: `AnalysisSubmitter.submit(..., gate=True, tags=())`, shared by the route and B3.
4. Route `POST /analyses` uses it; xfail test removed; 409 tests rewritten.
5. `CapeClient.create_file_task(options, task_fields)`; runner reads machine/options from guest + profile.
6. Finish through `GuestControl.finish_task`; `CapeControl`, `cape_control_url`, `guest_label` deleted.
7. `AnalysisRead.guest` / `guest_badges`; report header line.
8. Full gate: pytest, ruff check, ruff format --check, mypy.

## Done
- Step 1: `app/analyses/guest_choice.py` (+ `tests/analyses/test_guest_choice.py`, 21 tests).
- Step 2: `default_guest` setting (schema, tests in `tests/test_settings.py`), `guest` option (`app/schemas/guest_name.py`).
- Step 3: `app/analyses/submission.py` `AnalysisSubmitter.submit(..., gate, tags)` (+ `tests/analyses/test_submission.py`, 13).
- Step 4: route uses it, xfail test removed (its test kept under its name, now passing), 409/422/502 tests,
  read model `guest`/`guest_badges` (`app/analyses/guest_badges.py`), finish through `GuestControl.finish_task`.
  `tests/test_analyses_api.py` + submission + settings: green.

- Step 5: `CapeClient.create_file_task(options, task_fields)`; `Runner(..., guests, config)` reads machine from
  `analysis.options["guest"]`, interactive options from the guest's profile (`tests/analyses/test_runner_guest.py`).
- Step 6: `CapeControl`, `cape_control_url`, `guest_label` deleted; `main.py` passes the guest control to the runner.
- Step 7: `AnalysisRead.guest/guest_badges`; report header `guest` + "Analysed on <guest>" line (HTML and PDF).
- Step 8: `pytest -m "not integration"` 3531 passed (twice), `ruff check`, `ruff format --check`, `mypy app` clean.

## Running
- nothing

## Next
- Planner: regenerate the API client; update specs (backend: options.guest, settings.default_guest, read model).
- B3: call `AnalysisSubmitter.submit(..., gate=False, tags=["self-test"])`.
