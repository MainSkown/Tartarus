# F15 notes (Guests page)

## State: built, tested, screenshots reviewed by the implementer; waiting for the planner to publish the Artifact

## Done
- services/guest-state.ts (one state mapping, unknown state falls back to a neutral look), services/guest-view.ts (labels)
- composables/use-guest-list.ts (load, default marker, refresh on guest_build job messages, 5 s poll while building/testing, build progress, run checks, delete with 409)
- components/guest/{GuestBadges,GuestCard,GuestChecks,GuestField,GuestHealthMenu,GuestStateList}.vue
- pages/GuestPage.vue, routes `/guest`, `/guest/new`, `/guest/clone/:name`, `/guest/builds/:buildId` (the last three on PlaceholderPage), MainLayout guest-dot popover, StatusBadge guest state
- tests/screenshots/guest-page.spec.ts + guest-page-data.ts (18 states)
- Fix this round: guest-page.spec.ts had two typecheck errors (health fixture typed as the literal `degraded`); typed it as `SystemHealth`.

## Checks (last run)
- `npm run test:unit -- --run`: 184 files, 2801 tests, all passing
- `npm run typecheck`: 0 errors
- `npm run lint`: clean
- guest-page screenshot spec: 18 passed
- Coverage was not measured: `@vitest/coverage-v8` is not installed. Logic coverage was checked by reading the test titles.

## Left as is (seen in the screenshots, judged not bugs)
- A broken guest's card is stretched to the height of its row neighbour and shows empty space.
- Full-page captures draw the sidebar rail and the dialog backdrop only to the first viewport height (Playwright fullPage with fixed layout), not an app bug.
- The RUN CHECKS button shows only a spinner while busy (Quasar loading), with the progress line above it saying what runs.

## Screenshots (frontend/screenshots/)
See the final report of the F15 finishing run for the list with states and routes.
