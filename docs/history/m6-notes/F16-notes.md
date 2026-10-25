# F16 notes (guest build wizard and clone form)

## State: DONE; every screenshot looked at and fixed; gates green (205 files / 3144 tests, typecheck 0 errors, lint clean)

## Findings that shaped the design
- The 422 `details.fields[].location` is `["body", "<dotted path>"]` with the dotted path as ONE string
  (`identity.machine`, `media.file`, `options.defender`, `resources.vcpus`), so `validationIssues().field` is the full path.
- Variant is sent as `String(variant.index)` (server `variant_id`); omitted when the medium lists no variants.
- Clone: server refuses a different account/password, a changed locked option and a changed disk.

## Done
- services: guest-form, guest-media-view, guest-wizard-view (+ tests)
- composables: use-guest-submission, use-guest-wizard, use-guest-clone (+ tests)
- components/guest: GuestTextInput, GuestNameField, GuestIdentityField, GuestResourcesFields, GuestNotice, GuestMediaList, ProfileOptionField (+ tests)
- pages/GuestWizardPage.vue, GuestClonePage.vue (+ page tests), routes guest/new and guest/clone/:name wired, routes.test.ts updated
- tests/screenshots/guest-wizard.spec.ts + guest-wizard-data.ts: 42 passed
- Full unit run at 03:06: 203 files, 3125 tests, all passing (a first run showed 1 failure in F17's in-progress build header test, gone on re-run)

## Running
- nothing

## Next
- planner publishes the Artifact (one for the wizard, one for the clone form)

## Fixed after looking
- disabled media rows were dimmed to 60% by Quasar's `[disabled]` rule so the error text was unreadable: rows now use aria-disabled
- h2 section titles had Quasar's tall line-height (50px gaps); option labels now uppercase like the other fields; review label column widened; [BACK]/[CANCEL] padding aligned; empty-state RELOAD centred; clone computer-name placeholder says 'chosen at clone time'

## Screenshots (frontend/screenshots/, 42, spec: tests/screenshots/guest-wizard.spec.ts)
- guest-clone-conflict-409-narrow-600.png
- guest-clone-form-filled.png
- guest-clone-form-invalid-name.png
- guest-clone-form-long-source-name-narrow-600.png
- guest-clone-form-narrow-600.png
- guest-clone-form-narrow-700.png
- guest-clone-form.png
- guest-clone-giveaway-422.png
- guest-clone-loading.png
- guest-clone-source-not-found.png
- guest-clone-source-not-ready-narrow-600.png
- guest-clone-source-not-ready.png
- guest-clone-submitting.png
- guest-wizard-giveaway-422-jumps-back.png
- guest-wizard-giveaway-422-narrow-600.png
- guest-wizard-media-empty-narrow-600.png
- guest-wizard-media-empty.png
- guest-wizard-media-failed.png
- guest-wizard-media-loading.png
- guest-wizard-media-long-file-name.png
- guest-wizard-media-narrow-600.png
- guest-wizard-media-narrow-700.png
- guest-wizard-media-selected.png
- guest-wizard-media.png
- guest-wizard-name-taken-422.png
- guest-wizard-review-chosen-identity.png
- guest-wizard-review-conflict-409-narrow-600.png
- guest-wizard-review-conflict-409.png
- guest-wizard-review-narrow-600.png
- guest-wizard-review-narrow-700.png
- guest-wizard-review.png
- guest-wizard-settings-edition-open.png
- guest-wizard-settings-filled.png
- guest-wizard-settings-invalid-name.png
- guest-wizard-settings-keyboard-open.png
- guest-wizard-settings-long-values-narrow-600.png
- guest-wizard-settings-manual-step-option-narrow-600.png
- guest-wizard-settings-narrow-600.png
- guest-wizard-settings-narrow-700.png
- guest-wizard-settings-single-edition.png
- guest-wizard-settings.png
- guest-wizard-submitting.png
