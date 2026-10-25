# M10 F6 notes (the manual Defender pause looped)

## State: done (planner re-runs the checks and proves it on the real w10-q5 guest)

- done: failing tests first, then the fix, then green; spec paragraph "The pause is only the fallback" updated.
- running: nothing.
- next (planner): copy the changed `security-ui.ps1`, `tamper-off.ps1`, `defender-on.ps1` to `w10-q5`, CONTINUE with the
  broken lookup still in place (expect `RESULT toggle=not-found`, `RESULT toggle_skipped=tamper-protection-already-off`,
  then the flag, real-time and file checks); then update "This path was not exercised for real".

## The change

- `security-ui.ps1`: `Get-TamperProtected` moved here (one copy; both scripts defined it inside); new pure
  `Resolve-TamperAction -ToggleFound -TamperProtected -Wanted` -> `switch` | `already-there` | `pause`;
  `Close-SecurityWindow` returns on a null window.
- `tamper-off.ps1` (Wanted `$false`) and `defender-on.ps1` (Wanted `$true`): a missing window counts as toggle not found
  (`RESULT window=not-found` / `toggle=not-found` kept), the state is read once, `exit 10` only on `pause`,
  otherwise `RESULT toggle_skipped=tamper-protection-already-off|on` and the verification, real-time check and file proof run.
- Tests: `run_security_ui(snippet)` extracted from `select_tamper_toggle` (same encoded-command mechanism, the latter now calls it);
  `resolve_tamper_action` on top of it. The old text test "at least two `exit 10`" described the old structure and was
  replaced by a test that each script calls `Resolve-TamperAction` with its Wanted value, has exactly one `exit 10`, and that
  it sits directly under `if ($action -eq 'pause') {`.

## Failing first (new tests, with the pwsh shim on PATH, before any product change)

`pytest -q tests/test_windows_profile.py` -> 11 failed, 149 passed:
- `test_a_found_switch_is_always_operated[4 combinations]`, `test_no_switch_but_the_state_is_already_the_wanted_one_carries_on[2]`,
  `test_no_switch_and_the_state_differs_pauses_for_the_manual_fallback[2]`: Resolve-TamperAction did not exist
- `test_both_scripts_decide_through_the_shared_function_and_pause_only_on_its_say[tamper-off.ps1-$false | defender-on.ps1-$true]`:
  `assert 'Resolve-TamperAction -ToggleFound $false ...' in text`
- `test_the_tamper_state_is_read_by_one_shared_function`: `assert "function Get-TamperProtected" in text`
- `test_closing_a_window_that_was_never_found_does_nothing` passed already (the old try/catch swallowed the null); kept as a guard.

## Green

- with shim: `pytest -q` -> 1996 passed (baseline 1986, +10). Without shim: 1978 passed, 18 skipped (baseline 1977 / 9 skipped).
- `ruff check guest_engine auxiliary tests` clean; `ruff format --check` 88 files already formatted;
  `bash scripts/tests/test_windows_steps.sh` all tests passed.
