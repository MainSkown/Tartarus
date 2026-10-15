# C2b-1 notes (done / running / next)

Baseline before any change: `pytest -q` in cape/ -> 817 passed, 1 skipped.

## Done (each test-first: the test file was written and seen failing, then the code)
- Item 5: `Registry.allocate_ip` reads the `ip` out of the raw text of a corrupt `guest.json`
  (2 regression tests failed first).
- `steps.py` (step contract: protocol lines, exit codes, environment, redaction, process-group run).
- `builds.py` (build.json, log, context.json, one directory per build under the guest's).
- `sequencer.py` (thread per build, pause/continue/resume/restart, one active build, recovery of
  builds a killed service left running, crash -> failed build).
- `config.py`, `host.py` (virsh/supervisorctl through the injected runner), `health.py` (the four
  checks, the machines/list probe, the default agent check), `registrar.py` (write guests.conf,
  restart cape, verify through machines/list), `inspectors.py`, `engine.py` (the GuestEngine).
- Adoption of a registered guest with no record, at engine creation; `adoption` block added to
  `guest/profiles/windows/profile.json` (+ one allow-list line in test_windows_profile.py's
  giveaway scan, because that block records the M0b names).
- Fixtures: `tests/fixtures/fake_profile/{profiles/fake,steps}`, `fake_host.py` (a fake libvirt and
  CAPE behind the command runner), `engine_lab.py`.
- `guest/steps/.gitkeep`. `cape/Dockerfile` is NOT changed (see "Left for the planner").
- Mutation checks: 50 deliberate breaks of the engine code run against the new test files; the 5
  that survived at first (one was an equivalent restart-reset that is now removed) got tests (restart log, adopted-guest cleanup, busy-before-validation,
  begin-failure rollback, deleted source on resume) and then died.

## Running
- nothing

## Next / left for the planner
- BLOCKER for item 7: the cape build context is `./cape`, so `guest/profiles` and `guest/steps` cannot
  be COPYed. `additional_contexts` was tried with `docker compose build` on this host and fails
  ("the classic builder doesn't support additional contexts": no buildx plugin). Options: (A) compose
  `context: .` + `dockerfile: cape/Dockerfile`, a root `.dockerignore` (data/ is 7.8 GB), and `cape/`
  prefixes on the Dockerfile COPY lines; (B) a make target that stages `guest/` into a gitignored
  folder inside `cape/` before the build. Until then the engine finds no profiles in the image and
  every build answers 422 "profile ... is not an installed profile".
- `registry._timestamp` and `builds.timestamp` are the same one-liner (registry.py was closed to me
  beyond item 5).
- mypy reports one error in C2a's validation.py:148 (not touched).

## Decisions taken (also in the final report)
- The injected runner is media's `Runner` (returns `CommandResult(returncode, stdout, stderr)`), so the media scan and the engine share one concept and one fake.
- CAPE `machines/list` default probe uses urllib with CAPE_API_TOKEN (no secret on argv).
- The engine registers a guest itself when the last step succeeds (state `testing`, guests.conf, cape restart, machines/list check); the pipeline's `register` step has nothing left to do.
- Service start never restarts `cape`: adoption rewrites the registration files only.
