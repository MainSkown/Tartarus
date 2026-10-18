# Plan: M7b, frontend i18n (English only)

M7b is the second milestone of the [finish line](finish-line.md) (its roadmap entry holds the scope and the reasons).
Every string a user can read in the frontend moves into a locale catalogue; `en-US` is the only locale that ships.
Nothing the analyst sees changes. This file is the task table and the record of what was found.

## Status

**Built and proven 2026-10-18.** Every user-readable string of the frontend is in the `en-US` catalogue (18 files under
`src/i18n/en-US/`, 887 messages); `npm run lint` fails on a raw string in a template; English is the only locale.

What each step proved, on `97111a3` as the baseline:

- **Baseline.** `npm run test:unit` 212 files, 3226 tests, exit 0. The screenshot harness (572 specs, 556 images) is not
  deterministic: spinners, pulse markers, hover transitions, drawer and toast slide-ins differ between two runs of the same
  commit, so [compare_shots.py](m7b-notes/compare_shots.py) compares several runs and ignores the pixels where runs of the
  same code disagree. `placeholders.spec.ts › guest-placeholder` fails before and after (it waits for text of a page that
  now exists); not M7b's.
- **S0** ([findings](m7b-notes/S0-findings.md)). `vue-i18n` 11, Composition API, installed from `boot/i18n.ts`. vue-i18n's
  own types accept any key, so the project exports its own `t`, `n`, `d`, `I18nT` typed on the catalogue's dotted leaf paths:
  `vue-tsc` fails on an unknown key, and `$t` and `useI18n` are banned by lint. Conventions are in
  [gui.md](../specs/gui.md#internationalisation).
- **I1.** The key-usage unit test (`tests/unit/i18n-keys.test.ts`: a key used must exist, a key defined must be used) and
  the lint rules. The first version of the rule missed text in attributes (`label`, `title`, `placeholder`, `aria-label`)
  and in string literals in their bound form (`:label="x ? '[HIDE]' : '[REVEAL]'"`), which is most Quasar text; both were
  added after a probe file showed the gap (backlog 249 errors in 58 files became 513 in 81).
- **Wave 3, by slice rather than by area** (a slice owns a screen's components, its services, composables and stores, and its
  own catalogue files, so no two tasks touched the same file): M1 guests 42 files, M2 analysis 22, M3 live 34, M4 events 44,
  M5 network, artifacts and detections 13, M6 timeline 18, M7 shell, dashboard, submit, settings and reports 39, M8 rules,
  notes, tags and widgets 21. All Haiku, all in one round, none needed a second attempt. Six existing test files were
  edited, only where an exported const became a function or a key (`EXTEND_LABEL`, `GENERIC_ERROR_MESSAGE`,
  `BLANK_IDENTITY_LABEL`, `REPORT_OPTIONS`, `AnalysisTab.label`); no English assertion changed. Six more gained
  characterisation tests for messages that were split or pluralised.
- **Lock-in.** The rules moved into `eslint.config.js` (rules in `eslint.i18n-rules.js`), so `npm run lint --max-warnings 0`
  fails on raw template text: a probe file with `label="Hello"` failed it and the real tree passes. The `common.*` allowlist in
  the key test is gone.
- **Proof, run by the planner on the combined tree.**
  - `npm run test:unit`: 214 files, 3259 tests, exit 0 (now and then a run prints a Quasar `window is not defined` timer error
    from `live-event-stream.test.ts` and exits 1; it also happened on the untouched baseline).
  - `npm run lint` exit 0; `npm run typecheck`: one error, in `tests/screenshots/header-health-dots.spec.ts`
    (it predates M7b), none from M7b; `npm run build` exit 0.
  - **Text conservation:** all 887 catalogue messages trace to text in the pre-migration source. 18 first looked missing and
    were sentences the old code assembled from parts (`` `Could not ${enabled ? 'enable' : 'disable'} ${title}` ``,
    `` `${key} arrives later` ``, the `live-state` messages), which now are one message each with the same English.
  - **Screenshots:** four runs of `97111a3` against three of the migrated tree, 556 images each: 366 byte-identical to the
    first baseline, 188 differ only in pixels that also vary between runs of the same code, and 2 were flagged by the
    strict pass and looked at by eye (neither is a change): the 28 px spinner of the busy `[RUN CHECKS]` button
    (identical in all seven runs by eye) and an 8-pixel sliver of the `+60S` countdown bar, whose fill depends on when the
    capture happens (empty in three baseline runs, part full in others).
  - Module-level text: an AST scan found no `t(...)` call outside a function in any `.ts` file. A scan of `.ts` files and
    `<script>` blocks for text-like literals found only format names (STIX, MISP, CSV, HTML, PDF), query grammar, CSS classes,
    route names and message keys.
- **Not run:** `make e2e` (needs the real stack), and the production bundle was built but not opened in a browser. The unit
  suite, the 572 screenshot specs through the dev server and the build cover the same code paths.

**Commits:** conventions 9879c49, guard rails a8d4558, catalogue skeleton f7ef099, then one commit per slice (M1 to M8) and the
lock-in. The first slice commit also carries the deletion of the superseded `eslint.i18n.config.js`.

**Findings that stay open:**
- The live event counter reads "1 events" (M3 kept it: M7b may not change what the analyst sees). A deliberate English fix
  is now one catalogue line (`live.*` plural form).
- English the code could not carry over as one message: CopyButton and the DesktopPanel `subject` prop build a sentence
  around a noun passed in (`{what}`), which a translation into a language with grammatical cases would need to reword.
- Technical terms (DNS, HTTP, TLS, JA3, SHA256, `inetsim`) are catalogue messages in M5's tabs; a translator may leave them.
- Strings in `.ts` files and `<script>` blocks are guarded by review and the scans above, not by lint.
- A handful of unit symbols (`B`, `KB`, `MB`, `h`, `m`, `s`) in `format-duration.ts` and `file-size.ts` are not catalogued.
- `tests/screenshots/header-health-dots.spec.ts` fails `npm run typecheck` (it passes `{}` where `getBody` is required) and
  `placeholders.spec.ts` fails at runtime, both from before M7b.

## Waves

Rule 5 applies, and the user asked for as much work as possible on Haiku. Sonnet is kept for the conventions spike (real
judgment, and it fixes what every later task copies). Every task is test-first where logic changes (rule 2), ends green on
`npm run test:unit`, `npm run lint` and `npm run typecheck` for the files it touched, and is committed by explicit path
(another session may edit the repo; no `git stash`). The planner reads every diff; a Haiku task that fails twice goes to
Sonnet.

### Wave 0: baseline (planner)

| ID | Task | Check |
|---|---|---|
| **B0** (done) | `npm run screenshots` on the pre-change commit, twice, into the scratchpad | The two runs are byte-identical, or the differing files are listed and explained (clock, animation) so the final comparison can ignore exactly those: see Status |

### Wave 1: conventions spike (one task)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **S0** | Decide and prove the conventions on three files: a component with template text, `services/guest-build.ts` (pluralised, concatenated messages), `composables/use-end-run.ts` (toasts) | Sonnet, **care** | The library installed and wired; `src/i18n/` with the shared `t` and the typed `en-US` schema; the three files migrated with their tests still green; the vitest `setupFiles` entry proven on `guest-card.test.ts`; a new "Internationalisation" section in [gui.md](../specs/gui.md) saying the library, the key scheme, the single source of the key list, how code outside a component translates, plurals, number and date formatting (UTC stays UTC), and how tests get the catalogue; `docs/plans/m7b-notes/S0-findings.md` with what was tried and rejected |

### Wave 2: infrastructure (after S0)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **I1** | The catalogue skeleton per area under `src/i18n/en-US/`, the lint rule (`@intlify/vue-i18n/no-raw-text`, `no-unused-keys`) as a warning with the list of files not yet migrated, and the unit test that a key used in code exists in the catalogue and a catalogue key is used | Haiku | Test first: the key-usage test fails on a deliberately missing key; lint warns on a raw string in a fixture template |

### Wave 3: migration by slice (Haiku, parallel, disjoint files)

Changed from the roadmap's "services first, then components": a slice owns a screen's components **and** the services,
composables and stores that feed it, **and** its own catalogue files, so no two tasks touch the same file and the agent
that writes a message also sees where it is shown. The skeleton (empty catalogue files registered in `en-US/index.ts`) was
committed first so no task edits `index.ts`. `common.ts` may be extended by any task with a word that is generic across
areas. Strings the API sends are shown as received. Existing English assertions stay unchanged unless a message was
split or pluralised. A function's signature stays (it keeps returning the translated string) unless its callers are in
the same slice. The ownership map is the file lists in each task brief (every `.vue` and `.ts` file under `src/` outside
`api/` and `i18n/` belongs to exactly one slice; `components/tabs/index.ts` has no text).

| ID | Slice | Files | Catalogue files |
|---|---|---|---|
| **M1** | Guests, wizard, clone, build page | 42 | `guests` |
| **M2** | Analysis page shell, Overview, Processes | 22 | `analysis` |
| **M3** | LIVE tab, desktop, end run, `+60s` | 34 | `live` |
| **M4** | Events, query bar, facets, detail drawer | 44 | `events` |
| **M5** | Network, Artifacts, Detections | 13 | `network`, `artifacts`, `detections` |
| **M6** | Timeline (canvas text and tooltips) | 18 | `timeline` |
| **M7** | App shell, Dashboard, Submit dialog, Settings, reports and exports, router | 39 | `shell`, `dashboard`, `submit`, `settings`, `reports` |
| **M8** | Rules, Notes, tags, shared widgets (copy button, badges, empty and view states) | 21 | `rules`, `notes`, `tags`, `widgets` |

Strings in `.ts` files are not found by tooling (the lint rules read templates only), so wave 5 adds an audit: a scan of
string literals in `src/**/*.ts` that look like user text, reviewed by the planner.

### Wave 4: lock it in

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **L1** | The lint rules go from warning to error across the tree; the key-usage test is part of `test:unit` | Haiku | `npm run lint` clean at `--max-warnings 0` with the rule on; a raw string added to any template fails it |

### Wave 5: proof (planner)

| ID | Task | Check |
|---|---|---|
| **P1** | Screenshots after the change against B0, with `m7b-notes/compare_shots.py` | No FAILED row; every NOISY row looked at (those with text in the noise box, such as toasts, by eye) |
| **P2** | The suites | `npm run test:unit` exit 0, `npm run lint`, `npm run typecheck`, `make e2e` browser flows |
| **D1** | Docs | Status filled in here and in the roadmap; the conventions section in [gui.md](../specs/gui.md) matches what was built |

## Not in M7b

Translations, a language switcher or locale Setting, right-to-left layout, the backend's texts, the report export, and
the docs outside the specs.
