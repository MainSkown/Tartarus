# Task 10.5b/F1a notes: real progress and live words for the `install` step

## Where I am (resume from here)

- done: read the code; design settled (below)
- running: writing the failing tests (scripts/tests/test_windows_steps.sh, cape/tests/test_windows_profile.py)
- next: show them failing, implement provision.ps1 order + PLAN, steps/lib/windows.sh helpers, steps/install; green; ruff

## Design as implemented

- provision.ps1: `PLAN <n>` = count of `^Step ` lines of the script itself (cannot go stale). The agent step moves
  right after Pillow. The firewall step moves in front of it too: the agent listens on 8000 and Windows' firewall
  blocks it until that step has run, so the agent could not answer otherwise.
- windows.sh: fetch the guest log, keep its complete lines, relay the new ones, parse PLAN / steps done / newest STEP.
- install: the poll reads the log once the agent answers; the percentage comes from steps done over PLAN; before
  the agent answers it says "(estimated)"; no agent after the allowance + grace fails with the readable message.

## Evidence: failing first
- `bash scripts/tests/test_windows_steps.sh` with the 13 new install tests and no product change: 8 failed
  (relay once and in order, percentage from steps, step line names the newest guest step, retry a read error,
  partial line, last lines before the marker, estimate wording, no agent after the grace); the other 5 new tests
  (nothing relayed twice, no protocol-line confusion, ...) pass trivially before the change and guard it afterwards.
- `pytest tests/test_windows_profile.py`: 3 failed (agent registered before the slow steps; PLAN counted from the
  script's own Step blocks; a step title naming "decision 11").

## Result
- implemented as designed (firewall step moved ahead of the agent step: see Design). `bash scripts/tests/test_windows_steps.sh`:
  73 ok, all passed. cape pytest: 2029 passed 19 skipped without shim; 2048 passed with shim; ruff check/format clean.
- Done marker still last (existing test). Two sequencer tests flaked under load (procfs race), pass alone; not ours.
- Untestable without a real guest: provision.ps1 running on Windows (agent answering minutes in, firewall before
  agent), what the agent returns for a log held open (assumed: a failed /retrieve), the setup allowance default.
