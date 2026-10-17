# F18 notes (done / running / next)

## Facts found while reading
- PACKAGE in the Submit dialog is a free-text q-input today, not a select, and there is no static package list in
  the code (the gui spec names exe, dll, doc, xls, ps1, js). The fallback list is introduced in use-guest-choice.ts.
- Specs that open the dialog or Settings now also request /api/guests*, so the screenshot fixture's "unmocked /api
  request" check would fail them: the existing settings and submit-dialog specs call the new mock helper.

## Done
- use-guest-choice.ts, use-default-guest-field.ts, GuestChip.vue, GuestOptionRow.vue with unit tests.
- SubmitDialog (GUEST select, package list from the guest's profile, blocked state with link to /guest, list-failed
  state), SettingsPage (DEFAULT GUEST + stale-name note), AnalysisHeader (GUEST chip), AnalysesTable (chip).
- Visual review: every F18 screenshot looked at (1280 and the narrow 600/700 variants). Fixed:
  - the Submit dialog's guest menu overhung the select by 8px at 600px: its max-width now follows the dialog's real
    width (560px, 94vw or the viewport less Quasar's 24px gutters);
  - Settings' DEFAULT ROUTE group was cut off at 700px (it predates F18): it now wraps like the Submit dialog's.
- Unit 184 files / 2801 tests, typecheck and lint clean, guest-choice + submit-dialog + settings screenshot specs 48/48.

## Decision: Dashboard chip
The chip is a second line of the FILE cell, capped at 28ch (14ch under 700px, badges stacked below the name), so the
table has no new column and does not scroll sideways (asserted in guest-choice.spec.ts). Rows with a guest are about
20px taller; a row from before guests has no chip and keeps its height.

## Next
- The planner publishes the Artifact; wait for comments.
