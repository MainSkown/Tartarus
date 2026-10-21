# Plan: the finish line of v1

M0 to M7b are built (M7 closed 2026-10-17 after its exit run passed, M7b 2026-10-18; see their plans). This is what is left before Tartarus v1 is finished, decided with the user
on 2026-10-17 by going through every open question and every unfinished feature one by one. Milestones M7 to
M11 follow the order the user chose: **foundations, features, guest proofs, hardening, release**; M7b (frontend i18n,
added later the same day) sits between foundations and features. Each
milestone gets its own plan file (`m7-*.md` and so on) with waves and a test-first task table when it starts,
as M5 and M6 did; this file is the roadmap and the decision record.

## Decisions

### The v1 open questions

| Question | Decision |
|---|---|
| Stop and extend a running task | **Keep the `+60s` button, for interactive runs only** (changed the same day: the first answer, dropping it, was a misunderstanding). CAPE cannot extend a running task, so Tartarus enforces the deadline itself: an interactive task is submitted with CAPE's maximum timeout (1200 s) as the safety net, the backend ends the run at the analyst's deadline through the existing finish call, and `+60s` moves that deadline later, up to 1200 s. Non-interactive runs keep CAPE's own timeout. END RUN already works. |
| Sysmon timing | **Final phase only.** capemon gives the live events; Sysmon arrives with the final report. |
| Default analysis timeout | **180 s stays.** |
| App icon | **The user supplies the logo later.** Wiring it in (favicon, PWA manifest, header) is a release task (M11). |
| PDF report styling | **Closed:** the print variant that shipped in M5 stays. |
| Maximum upload size | **512 MB stays.** |
| Remaining sandbox-detection tells | **Fix both:** remove the two empty optical drives after install and give the guest a realistic display adapter. A real-guest spike comes first (M7), because the adapter may disturb capemon or the Guacamole desktop. |
| The guest's default password | **Closed.** Wizard builds get a random password; only the adopted `win` guest keeps `Tartarus1!`, a throwaway account on an isolated machine. |

### Unfinished M6 work

| Item | Decision |
|---|---|
| Resuming a clone too soon races the guest | **Fix it:** the reconfigure step waits for an earlier apply and reboot to finish before it applies again. |
| Failed guests count towards the five-guest cap | **Failed guests do not count.** The cap applies to ready and building guests; a failed guest never blocks a new build. |
| Browser e2e for the wizard | **Add a short flow to `make e2e`:** the wizard's fields, validation errors and the hand-over to the build page against the real backend. The six-minute clone stays in `make verify-wizard`. |
| Old `finish-run` program | **Remove it** from the cape image, its supervisor entry and its tests. |
| `[REBUILD]` button, pafish summary, "verified on Windows 11 25H2" note | **Not wanted.** A clone or a new build covers rebuilding. |

### Features that move into v1

| Feature | Decision |
|---|---|
| Event sources | **Sysmon, ETW and Volatility3 memory findings**, all final-phase. Volatility3 brings the "full memory dump" option on the Submit dialog (about 4 GB per run). |
| Defender's verdict in an analysis | **Build it in v1:** an analysis on a Defender-on guest says what Defender did (its operational log, whether the sample or process was removed). |
| PCAP and memory-image import | **Both, PCAP first:** an "imported" analysis kind with no guest run, with the same views and exports. |
| Search and IOC pivot across analyses | **A Search page plus an IOC pivot** (an IOC to every analysis that saw it). |
| Parallel analyses | **Analyses on different ready guests run at the same time; builds, clones, deletes and registration still wait for every analysis to finish.** CAPE reads its machine list at start, so hot reload is out of scope. |
| Windows hosts (WSL2) | **Dropped from the finish line** until the user has a Windows host to test on. |
| Frontend i18n | **Added 2026-10-17: every user-facing string of the frontend moves into a locale catalogue, and only English ships.** It touches about 110 files, so it gets its own milestone, M7b, placed before M8 so that the screens M8 and M9 add are written with message keys from the start. No translation and no language switcher in v1. |

### Stays after v1

Linux profile and its normaliser, ISO drop zone, URL and archive submission, compare two analyses, custom
rules and sequence detections, linked clones, profile `extends`, Windows hosts, **translations into other languages
with a language switcher** (M7b only builds the catalogue and ships English), and localising what the backend writes
(API error texts, the HTML and PDF report).

### Guest proofs the user wants run for real

The manual Defender pause fallback, a failing install step with RESUME and RESTART, a Windows 10 ISO and an
English-language Windows ISO. **The user supplies both ISOs when M10 starts.**

### What "finished" means

A clean-host install test following only the README; a CI pipeline on **GitHub Actions** (lint, types, unit and
integration suites; the real-guest checks stay manual because hosted runners have no nested KVM); a full
security review; a release with a version tag, changelog and the **GPL-3.0** license; and a cleanup of the docs:
the per-milestone plans and spike notes move to `docs/history/` with an index, and new top-level docs for people
who use or contribute to the project replace them.

## Milestones

### M7: Foundations (small fixes, closing questions)
Done 2026-10-17. The plan with its decisions and what each wave proved is in [m7-foundations.md](m7-foundations.md).
- **Fix the resume race:** done. A resumed clone reconfigure waits for an earlier apply instead of racing it; two
  stop-and-resume drills passed on real clones.
- **Failed guests do not count towards the cap:** done. The cap counts building, testing and ready guests.
- **Remove `finish-run`:** done. The backend still ends runs through `guest-control`.
- **Anti-VM tells spike, then the fix:** done for the drives. Run-mode guests have no optical drives and a
  pre-snapshot step removes the ghost ones. The display adapter stays the Basic Display Adapter: no candidate
  changed its name (spike S2).
- **The wizard's browser e2e** in `make e2e`: done. It builds, cancels and deletes a guest; `E2E_WIZARD=0` skips it.
- **The `+60s` button** (interactive runs): done. The spike S1 measured the design and the proof P2 ran it on the real
  stack, with a backend restart in the middle.
- **Close the questions in the docs:** done for `tartarus-v1.md` questions 2, 3 and 10, and the specs.
- Exit: passed on 2026-10-17 on the real stack: `make verify-guest` 12 of 12, `make verify-wizard` 12 of 12 and
  `make e2e` 129 checks, none failed; see the Status of [m7-foundations.md](m7-foundations.md).

### M7b: Frontend i18n, English only
Done 2026-10-18. The plan, what each step proved and the open findings are in [m7b-frontend-i18n.md](m7b-frontend-i18n.md).
Every string a user can read in the frontend moves out of the templates, services and composables into a locale
catalogue, with one locale, `en-US`, shipping. **Why now:** it is a change across about 110 files (108 Vue files, about
81 of them with visible text, and about 32 of the 126 TypeScript files outside the generated client, led by
`services/guest-build.ts`, `timeline-tooltip.ts`, `analysis-status.ts`, `analysis-tabs.ts`, `report-request.ts` and
`composables/use-guest-wizard.ts`), so it is cheapest while M8's Memory view and M9's Search and Import pages do not exist
yet: written afterwards, they would need migrating too. **What does not change:** how the app looks and reads. The exit
proof is that every screenshot comes out pixel-identical and every English assertion in the 230 unit tests still holds.
- **Conventions spike first (Sonnet).** Migrate three representative files by hand: a component with template text, a
  service that builds sentences from parts (`guest-build.ts` has pluralised and concatenated messages), and a composable
  that raises toasts (`use-end-run.ts`). Decide and write down, in a new "Internationalisation" section of
  [gui.md](../specs/gui.md): the library (the proposal is `vue-i18n` v9 in Composition mode, installed from a Quasar boot
  file, with Quasar's own component strings set from the same locale, `quasar/lang/en-US`); the key scheme
  (`area.screen.thing`, one catalogue file per area under `src/i18n/en-US/`); one source of truth for the key list (the
  `en-US` catalogue is the message schema, so `vue-tsc` fails on an unknown key); how code outside a component translates
  (one shared `t` imported from `@/i18n`, not a copy per file); plurals (`1 process`, `3 processes`) through the library's
  plural rules, not string building; numbers and dates through its formatters, replacing the hard-coded
  `toLocaleString('en-US')` in `format-number.ts` and `NoteEditor.vue`, while timestamps shown in UTC stay in UTC; and how
  tests get the catalogue (the proposal is one vitest `setupFiles` entry that installs the plugin through
  `config.global.plugins`, which `@vue/test-utils` merges with each mount's own plugins, so the roughly 100 mounting tests
  need no edit; the spike confirms it on `guest-card.test.ts`).
- **Infrastructure (Sonnet).** The i18n instance and boot file, the `en-US` catalogue skeleton, the typed schema, the
  vitest setup entry, and the lint rule: `@intlify/vue-i18n/no-raw-text` for templates (and `no-unused-keys`), added
  first as a warning list of the files not yet migrated.
- **Migration by area (Haiku, parallel, disjoint files, test-first only where logic changes).** Services and composables
  with strings first (about 32 files), then the components and pages by area: Guests, wizard and build page; the analysis
  page shell and its tabs; LIVE; Events, Network, Artifacts, Detections and the detail drawer; Timeline (canvas text and
  tooltips); Settings, Dashboard, Submit dialog, Rules, Notes and Export. Each task migrates only its own files and adds
  its keys to its own catalogue file, so tasks do not collide. Strings the API sends (error texts, validation messages) are
  shown as received.
- **Lock it in.** The lint rule goes from a warning list to an error for the whole tree, so a new screen cannot add raw
  text; a unit test fails when a key used in code is missing from the catalogue or a catalogue key is unused.
- **Proof.** Capture all 32 screenshot specs on the commit before the change and on the commit after, and compare the
  images: any pixel that differs is either fixed or explained. `npm run test:unit` exits 0 with the existing assertions
  unchanged except where a message was split or pluralised, `eslint` and `vue-tsc` are clean, and `make e2e`'s browser flows
  pass. No screenshot review Artifact is needed while the images are identical (rule 4 is about visual changes).
- **Not in M7b:** translations, a language switcher or a locale Setting, right-to-left layout, the backend's texts, the
  report export, and the docs.

### M8: More event sources and Defender's verdict
- **Sysmon normaliser:** CAPE's collected Sysmon EVTX to process, network, file and registry events; Sigma rules
  already target these fields. Needs an EVTX reader (a spike first: which library, how big the logs are).
- **ETW normaliser:** enable CAPE's ETW auxiliary in the generated config, then DNS, WMI, AMSI and network events
  into the existing lanes.
- **Volatility3:** a "full memory dump" checkbox on the Submit dialog (with the 4 GB and minutes warning and a disk
  check), CAPE's memory dump and its Volatility results into a `memory` lane, a Memory view or filter, and
  `malfind` and hollowing findings as detections.
- **Defender's verdict:** collect the Defender operational event log from the guest after a run on a Defender-on
  guest, normalise it, and say on the analysis whether Defender detected or removed the sample.
- Each source is a `Normalizer` implementation behind the one shared interface; no source writes its own copy of
  the ECS helpers. Each gets fixture tests and an e2e check on a real run.

### M9: Beyond one run

**Status (2026-10-21): built; wave 3 (parallel analyses) pending its proof** (task 3.6). The header chip and the
Guest picker's busy marker (3.5b) are not built yet.
- **PCAP and memory import:** an `imported` analysis kind (no guest, no queue slot for a guest), upload and size
  limits, the existing network and memory normalisers run on the file, the Submit dialog gets an Import tab.
- **Search and IOC pivot:** a cross-analysis query over an OpenSearch alias, a Search page reusing the query bar
  and event table, and an IOC link to every analysis that contains the value.
- **Parallel analyses:** the queue runs one analysis per ready guest at the same time; the live collector, the
  LIVE tab, the desktop and the header's live chip become per-analysis; a build, clone or delete waits for every
  analysis; the gate and the "analysis refused while a guest is built" rules are reviewed for several running
  analyses. Largest item of the finish line: a spike on CAPE's behaviour with two tasks at once comes first
  (S0b ran only one at a time).

### M10: Guest proofs
With the user's ISOs: the manual Defender pause (force the toggle-not-found case on a throwaway clone and walk
the pause, the desktop and CONTINUE), a failing install step with RESUME and RESTART from the real build page,
a Windows 10 22H2 build and a clone with its self-test, and an English-language Windows build proving the
localized names of the Security window and the giveaway scan. What differs per ISO is recorded in the spec; each
proof becomes a `verify-*` check where it can be automated.

### M11: Hardening and release
1. **Security review** of the backend (it parses untrusted report data), the control service, the cape container
   and the compose network layout; findings fixed or recorded.
2. **CI on GitHub Actions:** lint, types, the unit suites of backend, cape and frontend, the integration suite,
   the screenshot harness; a status badge in the README.
3. **Docs cleanup:** `docs/plans/**` to `docs/history/` with an index; new top-level docs for users (install,
   first analysis, building a guest, reading a report, backup and disk use, troubleshooting) and contributors
   (architecture overview, running the tests, the rules in `.claude/CLAUDE.md` in plain language, how to add a
   guest profile, an event source or a translatable message key); the specs stay as the reference.
4. **License and release files:** `LICENSE` (GPL-3.0), `CONTRIBUTING.md`, `CHANGELOG.md`, a version in the app,
   the About page and the backend, the app icon from the user's logo, a licence note about CAPEv2 and the other
   bundled components.
5. **Clean-host install test:** a machine that has never run Tartarus, following only the README, from
   `docker compose up` to a first analysis and a built guest; every gap becomes a doc or preflight fix.
6. Tag `v1.0.0`.

## What the user provides, and when
- Before M10: a Windows 10 22H2 ISO and an English-language Windows ISO in `data/iso`.
- Before M11 step 4: the logo.
- During every milestone with a screen (M8's Memory view, M9's Search and Import): the screenshot Artifact
  review, as in M5 and M6.

## Risks

| Risk | Handling |
|---|---|
| Parallel analyses touch the queue, collector, desktop and gates at once | A CAPE spike with two tasks first; the milestone is split into waves that each keep `make e2e` green |
| Volatility3 and the memory dump are slow and large | A disk check before submit, the existing disk thresholds, the option off by default |
| An EVTX reader or the ETW module does not give usable events | Each source starts with a spike on a real run; a source that cannot meet the bar is dropped from v1 and recorded |
| The display adapter change breaks capemon or the desktop | The spike runs first on a throwaway clone with `verify-guest` and an interactive run as checks; the empty-drive removal ships alone if the adapter cannot |
| GPL-3.0 and bundled components | The README and `LICENSE` note which parts are separate programs in the cape container (CAPEv2 is GPL-3.0 too); checked in the release step |
| The i18n migration changes a string without anyone noticing, or a template keeps a raw string | The before-and-after screenshot comparison, the unchanged English unit assertions, and a lint rule that errors on raw text across the tree |
| Agents report results optimistically (found again in M6) | Every milestone is proven on the real stack through the public API before it is called done, as M6 was |
