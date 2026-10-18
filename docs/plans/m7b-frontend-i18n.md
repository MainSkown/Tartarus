# Plan: M7b, frontend i18n (English only)

M7b is the second milestone of the [finish line](finish-line.md) (its roadmap entry holds the scope and the reasons).
Every string a user can read in the frontend moves into a locale catalogue; `en-US` is the only locale that ships.
Nothing the analyst sees changes. This file is the task table and the record of what was found.

## Status

Started 2026-10-18. Baseline taken on `97111a3`: `npm run test:unit` 212 files, 3226 tests, exit 0 (one run printed 2
transient errors and still passed; not reproduced on the next run). The 388 baseline screenshots are captured to the
session scratchpad (twice, to learn whether the harness is deterministic) before any change.

## Waves

Rule 5 applies, and the user asked for as much work as possible on Haiku. Sonnet is kept for the conventions spike (real
judgment, and it fixes what every later task copies). Every task is test-first where logic changes (rule 2), ends green on
`npm run test:unit`, `npm run lint` and `npm run typecheck` for the files it touched, and is committed by explicit path
(another session may edit the repo; no `git stash`). The planner reads every diff; a Haiku task that fails twice goes to
Sonnet.

### Wave 0: baseline (planner)

| ID | Task | Check |
|---|---|---|
| **B0** | `npm run screenshots` on the pre-change commit, twice, into the scratchpad | The two runs are byte-identical, or the differing files are listed and explained (clock, animation) so the final comparison can ignore exactly those |

### Wave 1: conventions spike (one task)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **S0** | Decide and prove the conventions on three files: a component with template text, `services/guest-build.ts` (pluralised, concatenated messages), `composables/use-end-run.ts` (toasts) | Sonnet, **care** | The library installed and wired; `src/i18n/` with the shared `t` and the typed `en-US` schema; the three files migrated with their tests still green; the vitest `setupFiles` entry proven on `guest-card.test.ts`; a new "Internationalisation" section in [gui.md](../specs/gui.md) saying the library, the key scheme, the single source of the key list, how code outside a component translates, plurals, number and date formatting (UTC stays UTC), and how tests get the catalogue; `docs/plans/m7b-notes/S0-findings.md` with what was tried and rejected |

### Wave 2: infrastructure (after S0)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **I1** | The catalogue skeleton per area under `src/i18n/en-US/`, the lint rule (`@intlify/vue-i18n/no-raw-text`, `no-unused-keys`) as a warning with the list of files not yet migrated, and the unit test that a key used in code exists in the catalogue and a catalogue key is used | Haiku | Test first: the key-usage test fails on a deliberately missing key; lint warns on a raw string in a fixture template |

### Wave 3: migration by area (Haiku, parallel, disjoint files)

Each task migrates only its own files and adds keys only to its own catalogue file. Strings the API sends are shown as
received. Existing English assertions stay unchanged unless a message was split or pluralised.

| ID | Area |
|---|---|
| **M1** | Services and composables with strings (about 32 TypeScript files outside the generated client) |
| **M2** | Guests page, build wizard, clone form, build page |
| **M3** | Analysis page shell and its tabs (header, Overview, Processes) |
| **M4** | LIVE tab |
| **M5** | Events, Network, Artifacts, Detections, detail drawer |
| **M6** | Timeline (canvas text and tooltips) |
| **M7** | Settings, Dashboard, Submit dialog, Rules, Notes, Export, layouts and the app shell |

M1 goes first (the components call the services); M2 to M7 run together after it.

### Wave 4: lock it in

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **L1** | The lint rules go from warning to error across the tree; the key-usage test is part of `test:unit` | Haiku | `npm run lint` clean at `--max-warnings 0` with the rule on; a raw string added to any template fails it |

### Wave 5: proof (planner)

| ID | Task | Check |
|---|---|---|
| **P1** | Screenshots after the change against B0 | Every pixel that differs is fixed or explained |
| **P2** | The suites | `npm run test:unit` exit 0, `npm run lint`, `npm run typecheck`, `make e2e` browser flows |
| **D1** | Docs | Status filled in here and in the roadmap; the conventions section in [gui.md](../specs/gui.md) matches what was built |

## Not in M7b

Translations, a language switcher or locale Setting, right-to-left layout, the backend's texts, the report export, and
the docs outside the specs.
