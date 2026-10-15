# C5 notes (done / running / next)

Baseline before any change: `pytest -q` in cape/ -> 1296 passed, 1 skipped.

## Done (each piece: test written, seen failing, then the code)
- Item 1: cape/Dockerfile gets a late apt layer for gcc-mingw-w64-x86-64 (candidate 13.2.0-6ubuntu1+26.1,
  universe, seen with `apt-cache policy` and `apt-get -s install` in ubuntu:24.04). No docker build run.
- Profile schema (`cape/guest_engine/profile.py`, tests in test_profile.py, fixtures windows/ubuntu/fake):
  `selftest.check_step` (string or null, optional, step-existence checked like a pipeline step),
  `selftest.sample` is now optional (a profile may define none), and the sample gets `output` (the file
  name the build produces and the service serves) plus placeholders `{source}` / `{output}` that the
  `build` argv must hold exactly once. Reason: the old `build` argv was only a prefix
  (`gcc -O2 -s`), which cannot say where the source and output go nor put `-lws2_32` after the source
  (benign.c uses winsock; the scripts' command is `gcc -O2 -s src -o out -lws2_32`).
- `cape/guest_engine/selftest.py` (new): `SampleBuilder` (cache `<libvirt_dir>/tartarus/cache/selftest/
  <profile id>/<output>` + `<output>.key`, a sha256 of the source bytes and the argv; fresh temp dir in
  that folder; failure -> `SampleBuildFailed`), `ChecksCollector` (FACT/GIVEAWAY/PROOF protocol),
  `PreparedChecks` + `run_check_step`, `ChecksFailed`. Tests: test_selftest_sample.py (18),
  test_selftest_checks.py (39).
- `steps.failure_message` extracted from the sequencer (one wording for a failed step, used by builds
  and checks). `Sequencer.occupy()` / `require_unoccupied()` hold the one slot for work that is not a
  build; `shutdown()` stops the step run under it. Tests in test_sequencer.py.
- Engine: `selftest_sample`, `selftest_checks`, `EngineConfig.selftest_check_timeout_s` (default 300),
  protocol + `NotReadyEngine`; start_build/start_clone/resume/check/delete_guest refuse while checks run.
  A failed check also `virsh destroy`s the guest (a step killed at its limit cannot run its trap).
  test_engine_selftest.py (28).
- control_http `Binary` answers; guest-control routes `GET /guests/{name}/selftest/sample` and
  `POST /guests/{name}/selftest/checks` (500 `SampleBuildFailed`, 502 `ChecksFailed`).
- `guest_agent.py run` accepts a path inside the profile folder (`selftest/guest-facts.ps1`), stored in the
  guest under its plain name, `..` and absolute paths refused.
- Windows: `defender-proof.ps1`, `steps/selftest-checks`, `scripts/tests/test_selftest_steps.sh`.

## Checks run at the end
- `pytest -q` in cape/: 1438 passed, 1 skipped (the skip is the pwsh parser test, run through docker instead:
  9 .ps1 files, 0 parse errors). ruff format/check clean except cape/patches/skip-packaged-apps.py (not mine).
- scripts/tests: generic_steps 69, windows_steps 43, clone_steps 62, build_guest 17, verify_guest 17,
  selftest_steps 30, verify_cape 57, finish_run 18, all ok. shellcheck -x on the step and its test: clean.
- Mutation checks: the step 33 mutants (4 survived at first, got tests, all killed); python 46 mutants (4
  survived at first, got tests, all killed).
- The profile's sample command (expanded) compiled benign.c to a PE in ubuntu:24.04 + gcc-mingw-w64-x86-64.

## Not verified
- Nothing ran against a real guest, real libvirt, or the rebuilt image (no docker build).

## Running
- nothing

## Next
- final report
