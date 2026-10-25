# Task 10.9 (F1b + F7) notes: the build page says what runs, one shared panel header

## State: done, awaiting the planner's review (nothing committed)

## Design as implemented

- cape: `BuildRecord.last_activity` (set when a step starts, on every log line and progress change; a plain line saves
  build.json only when the second moved), `StepState.description` frozen from `PipelineStep.description`
  (profile.json `description`, optional non-empty string, validated in `profile.py`); sentences for every step of
  guest/profiles/windows/profile.json (no "CAPE" in them: the profile is scanned for giveaway words).
- backend: `BuildStatus.last_activity`, `BuildStep.description`, both `None` when absent. Client regenerated offline.
- frontend: `services/build-activity.ts` (STALE_AFTER_S = 120, ACTIVITY_TICK_MS), `composables/use-activity-age.ts`,
  `composables/use-now.ts` (the shared 1 s clock; BuildStepList uses it too; LiveChip and use-ticking-seconds still
  hold their own copy), `BuildHeader` shows description + phase + age, `PaneHeading` is the one panel header
  (title left, `actions` slot right, `--pane-heading-height`), `BuildLogPanel` and `DesktopPanel` use it, the
  desktop buttons moved from the toolbar under the screen into the header, the hint stays under the screen.
- PROGRESS lines in the log: rendered as a thin bar labelled with the step (`INSTALL 36%`), not hidden, so the log
  keeps its story; `LOG ` prefix dropped (which also makes the dimming of `guest:` lines work on real logs).
- DesktopPanel keeps its box on the live tab (prop `bare` removes it); the build page uses `bare`, so the DESKTOP
  header starts level with STEPS.

## Evidence: failing first

- cape (`pytest tests/test_builds.py tests/test_sequencer.py tests/test_profile.py tests/test_windows_profile.py`):
  11 failed, 486 passed before the change (4 builds, 3 sequencer, 1 profile, 3 windows profile).
- backend `tests/guest/test_build_api.py tests/guest/test_schemas.py`: 3 failed, 70 passed.
- frontend vitest on the 8 touched/new files: 14 failed + 2 files that could not load (build-activity,
  use-activity-age), 91 passed.

## Result

- cape pytest 2043 passed, 19 skipped; ruff check/format clean. backend 4247 passed (not integration), ruff, mypy clean.
- frontend vitest 238 files, 3575 tests passed; eslint and vue-tsc clean.
- screenshots: guest-build.spec.ts 88 passed (4 widths), live-desktop.spec.ts and guest-build-cancel.spec.ts pass.
  Full screenshot suite had 51 failures before the last tweaks, all in specs this task does not touch (unmocked
  /api/iocs/*/analyses requests, export menu, report dialog, placeholders, shell, submit-memory, timeline).
