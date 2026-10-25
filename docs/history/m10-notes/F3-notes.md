# M10 F3 notes (Defender step: switches found by toggle behaviour)

## State: done (planner proves it on the real guest next)

- done: failing tests first, then fix, then green; spec item (3) updated; "not exercised for real" sentence untouched.
- running: nothing.
- next (planner): `docker cp` the fixed `security-ui.ps1` into the container and run the Defender step on the w10 guest.

## Failing first (before touching security-ui.ps1)

`PATH=<scratchpad>/bin:$PATH pytest -q tests/test_windows_profile.py -k SecurityWindowLookup`
-> 7 failed, 9 passed. The two kinds of failure on the old script:
- text test `test_the_switches_are_found_by_toggle_behaviour_not_by_an_automation_id` (old script has `settingToggle`);
- the six pwsh selection tests: the old script could not be dot-sourced off Windows (`Add-Type -AssemblyName
  UIAutomationClient` fails on Linux pwsh: "Cannot find path ...") and has no `Select-TamperToggle`.

## Design

- `Select-TamperToggle` is pure (objects with a `Name`): by name in `$TamperToggleNames`, else the LAST switch, else `$null`.
- `Find-TamperToggle` only collects `IsTogglePatternAvailableProperty = $true` descendants, wraps them as `{Name; Element}`,
  calls the pure function and unwraps `.Element`. `TamperToggleFallbackIndex` and `settingToggle` are gone.
- `Add-Type` is guarded by `$PSVersionTable.PSEdition -eq 'Desktop' -or $IsWindows`: no new file, so no upload list changes.
- Tests feed the script text to pwsh with `-EncodedCommand` (no file paths, works with a real pwsh and the docker shim).
- Found on the way: the existing `test_every_script_parses` never worked on a real pwsh (`-Command` glues trailing args onto the
  command text, so `$args` was empty and it errored on the first path). It was always skipped. Fixed by calling the script as
  `& { ... }`; it now passes and was shown to fail on a file with a syntax error.

## Results

- no pwsh: `uv run --no-project --with pytest pytest -q` in cape -> 1958 passed, 8 skipped (7 new pwsh tests + the parse test).
- shim pwsh (docker): 1966 passed, 0 skipped.
- ruff check: All checks passed; ruff format --check: 88 files already formatted.
- `bash scripts/tests/test_windows_steps.sh`: all tests passed.
