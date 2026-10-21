# quiet-desktop notes (done / running / next)

## Done
- Tests first, red: cape `pytest` could not even collect (3 collection errors, then 62 errors/failures in
  test_windows_profile.py: the list form and the new files did not exist); `test_generic_steps.sh` with the old
  `guest/steps/snapshot`: 12 tests failed (the 3 new pre-snapshot tests and the snapshot tests, the old step ran
  the list "[]" as a step name); backend `test_selftest_verdict.py`: 2 failed (open app named in the message).
- Green: cape 2117 passed with pwsh shim, 2076 passed + 41 skipped without; ruff check + format clean;
  `test_windows_steps.sh` 79 ok, `test_selftest_steps.sh` 31 ok, `test_generic_steps.sh` 72 ok, none failed;
  backend 4251 passed (not integration), ruff and mypy clean.
- `agent.pre_snapshot` is a list (profile.py), `guest/steps/snapshot` loops over it, Windows profile lists
  `remove-ghost-drives`, `quiet-desktop`; new `quiet-desktop` step, `quiet-desktop.ps1`, shared
  `desktop-apps.ps1` (the exclusion list `$KeptProcessNames`), fact `desktop.app_windows` in guest-facts.ps1,
  verdict in backend/app/guest/selftest_verdict.py, `guest_agent.py --with` reads helpers from the profile
  folder (a helper in the root reaches a script in selftest/), selftest-checks and verify-guest.sh upload the helper.

## Cannot be tested without a real guest
- that CloseMainWindow closes Edge, that Escape reaches the Networks flyout, that SendKeys works from the agent's
  session, that the registry key helps after the next boot, and that Get-Process sees the windows from the agent's
  session.

## Next
- the planner proves it on a real clone. Note: frontend/tests/screenshots/guest-build-data.ts still has the old
  snapshot description text (screenshot fixture, not touched).
