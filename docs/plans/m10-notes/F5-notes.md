# F5 (task 10.12): `[RE-RUN SELF-TEST]` for a failed guest

Status: done in code, unit-green. Real-guest proof and screenshot review are the planner's.

## Design as built

- Control service: `POST /guests/{name}/selftest` -> `Engine.retry_selftest(name)` -> `202 {"id": <build id>}`.
  The engine refuses (409) unless it can take the one slot (`require_free_slot`: another build, clone, check or
  self-test check, or a stopping service), the guest is `failed`, and the guest's last build record is `succeeded`
  (what the record says: a guest that failed in a step has a `failed` build and no snapshot; a guest that failed its
  verdict has a `succeeded` one). Then `refuse_when_full` (the five-guest cap, now a public function of
  `validation.py` the build and clone also call), state `testing`, and `Registrar.sync()` (the build's own register
  path). A registration failure puts the guest back to `failed`, unregisters quietly and answers 409.
- `complete_build(build_id, ...)` needed no change: a `testing` guest with a `succeeded` build is exactly what it accepts,
  so the verdict makes it `ready` or `failed` and stores the new verdict.
- Backend: `POST /guests/{name}/selftest` (`guests_retry_selftest`), gate `require_no_analysis_needing_a_guest("tested")`,
  `control.retry_selftest(name)`, then the same `guest_build` job via `tracking.track(name, build_id, SELFTEST_KIND)`.
  Everything else (404, 409 texts) is the control service's, passed through like clone's.
- Job: `kind == "selftest"` skips `follow()` (the build already succeeded: nothing to poll, no old log replayed into the
  job) and calls `hand_to_self_test(build_id)`, the same method the build path calls. The extraction was changing its
  argument from the `BuildStatus` to the build id; nothing was copied. After a backend restart `reattach_guest_builds`
  already follows a `testing` guest with a succeeded build, which covers a retest cut off by a restart.
- Frontend: why no new handle: the card never follows a job id. It follows the guest's `state` (list reload on every
  `guest_build` job message plus the 5 s poll while a guest is `building`/`testing`) and `guest.build_id` for the
  progress bar. A retry makes the guest `testing` with the same `build_id`, so the existing display works unchanged.
  So: composable `retestSelfTest/isRetesting/retestErrorOf` in `use-guest-list.ts`, `guestActions().retestSelfTest`,
  card props `retesting`/`retestError`, event `retestSelfTest`, message `guests.card.action.retestSelfTest`.
- "Qualifies" in the GUI: `state === 'failed' && selftest != null`. The control service stores a verdict in the record
  only through `complete_build`, so a failed guest with a verdict finished its build. The service stays the authority:
  an edge (failed during a step on a later RESUME after an earlier failed verdict) still shows the button and is refused
  with "never finished building" on the card.
- The card's refusal paragraph became one `v-for` over `[deleteError, retestError]` (no second copy of the markup).

## Test-first evidence

Failing first (before any implementation):

- cape: `pytest tests/test_engine.py tests/test_guest_control.py`: 12 failed (9 engine retry tests: AttributeError
  `retry_selftest`; control: the route 404, the 409 mapping, the unknown-guest 404) and 1 error (the pre-existing flaky
  `/proc/self/task/*/children` teardown race, different test each run, not related).
- backend: `pytest tests/guest tests/test_app_routes.py`: 3 collection errors (`SELFTEST_KIND` not importable in
  `test_build_api.py`, `test_build_job.py`, `test_gate_api.py`), i.e. none of the new tests could run.
- frontend: `vitest run` of guest-view, guest-card, use-guest-list, guest-page: 23 failed of 110.

Passing after: see the totals in the final report.

One bad test of mine, fixed: `cape_restarts == 2` after the retry (it is 3: register, unregister on the failed
verdict, register again). A second test name collided with an existing `test_an_unknown_guest_is_not_found` in
`test_engine.py` and silently shadowed it until renamed.

## Hand-edited generated client

`make api-sync` needs the backend; not run. Edited in the generator's style: `frontend/src/api/sdk.gen.ts`
(`guestsRetrySelftest` after `guestsClone`, import list), `types.gen.ts` (`GuestsRetrySelftest{Data,Errors,Error,
Responses,Response}` after `GuestsClone*`), `index.ts` (the exports). The next real `make api-sync` should produce no
diff in those spots; if it reorders them, take the generator's output.

## For the real-guest proof

1. `w10`/another guest that failed its self-test with all steps passed: button shows, click, card goes `TESTING`,
   CAPE lists the machine (`machines/list`), the self-test analysis runs, the guest ends `ready` with the new verdict.
2. A ready guest: no button; `POST /api/guests/<ready>/selftest` answers 409 "is ready; only a failed guest...".
3. A guest that failed during a step: 409 "never finished building".
4. Click during an analysis: 409 naming it. `cape` restart is part of the retry (it kills a running analysis, hence the gate).
5. Failing it again (e.g. inject a failing signal) leaves it `failed` and unregistered, and the button is there again.
6. Screenshot states: failed card with the button, busy, refusal on the card, testing card after the click.
