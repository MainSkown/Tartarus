# F17 notes (build progress page)

## State: built, tested, screenshots reviewed by the implementer; waiting for the planner to publish the Artifact

## Done
- Desktop reuse: services/desktop-url.ts, use-desktop-session takes `path`, components/DesktopPanel.vue (LiveDesktopSlot now wraps it), phaseMessage subject 'build', DesktopMessage `subject`; tests/screenshots/desktop-mock.ts gained `mockDesktopSocketAt` (mockDesktopSocket delegates to it)
- services/guest-build.ts, composables/use-guest-build.ts, components/guest/{BuildHeader,BuildStepList,BuildLogPanel,BuildNotice,SelfTestVerdict}.vue, CopyButton `label`, StatusBadge `buildPhase`, pages/GuestBuildPage.vue, route guest/builds/:buildId (and routes.test.ts line)
- GuestCard [VIEW BUILD] already links /guest/builds/<build_id> (guest-card.test.ts line 161)
- Screenshots: tests/screenshots/guest-build.spec.ts + guest-build-data.ts, 17 states x (1280, 700, 600) = 51, all in frontend/screenshots/guest-build-<state>[-narrow-700|-narrow-600].png

## Checks (last run)
- `npm run test:unit -- --run`: 205 files, 3143 tests passed
- `npm run typecheck`: no errors
- `npm run lint`: clean
- guest-build screenshot spec: 51 passed; live-desktop screenshot spec: 19 passed (after the desktop-mock change)
- Coverage not measured (@vitest/coverage-v8 not installed)

## Never exercised
The guacamole stream and the real websocket against a real build: only mocks (desktop-mock frames, fake guacamole in vitest).

## Fixed after looking at screenshots
Log bar underline, verdict heading line-height, narrow signal rows, header percent wrapping, log not starting at its end, unreachable page spacing, busy button keeps its label.
