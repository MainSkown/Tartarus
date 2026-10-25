# M10 review screenshots: notes

Specs: `frontend/tests/screenshots/guest-retest.spec.ts` (+ `guest-retest-data.ts`) and
`frontend/tests/screenshots/analysis-warnings.spec.ts` (+ `analysis-warnings-data.ts`).
PNGs land in `frontend/screenshots/`. Both files: 18 tests, passing twice in a row.

## Layout problems seen on review

- Events tab, 600 px wide, long warning (`analysis-warnings-events-two-warnings-narrow-600px-route-analysis-events.png`):
  the warning list takes most of the window height, so the table is left a sliver (header and one row).
  Not off screen, but effectively unusable. Product code: `src/components/AnalysisWarnings.vue` inside
  `src/components/tabs/EventsTab.vue` `.events-tab__main`. Options: cap the warnings' height with its own
  scroll, or collapse them behind a toggle when there are several.
- Summary tab, long warning at 600 px: nothing broken; the nested path wraps with `overflow-wrap: anywhere` as intended.

## Looked fine

- Guest card: failed with button, hover, focus, testing after click, 409 refusal on card, ready (no button),
  failed never built (no button), long name plus long refusal, 900 px with two cards.
- Summary: one warning, two warnings, no warnings, long warning, 600 px.
- Events: two warnings at 1280x720 (table fills to the bottom, footer visible, scroll inside), no warnings (unchanged).

## Not product bugs

- Full-page captures show the left rail ending at the viewport height. It is a Quasar `q-drawer` (fixed),
  so this is a capture artifact. The existing guest-page specs have the same look.
- Busy button (`guest-retest-failed-busy-route-guest.png`): Quasar hides the label while `loading`, so only
  the spinner shows. Standard behaviour; mention it if the design wants the label kept.

## Fixture and harness choices

- The re-run request flips the guest to `testing` in later list reads, so the TESTING state is reached through
  the real reload path, not forced.
- `expectNoCardOverflow` is re-declared in `guest-retest.spec.ts` because it is private to `guest-page.spec.ts`
  and importing a spec would register its tests. Moving it to a shared helper is a follow-up.

## Checks

- `npm run lint`: clean.
- `npm run typecheck`: 3 errors, all pre-existing (header-health-dots.spec.ts, ioc-analyses-link.spec.ts). No new errors.
