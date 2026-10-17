# Plan: the finish line of v1

M0 to M6 are built and approved. This is what is left before Tartarus v1 is finished, decided with the user
on 2026-10-17 by going through every open question and every unfinished feature one by one. Milestones M7 to
M11 follow the order the user chose: **foundations, features, guest proofs, hardening, release**. Each
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

### Stays after v1

Linux profile and its normaliser, ISO drop zone, URL and archive submission, compare two analyses, custom
rules and sequence detections, linked clones, profile `extends`, Windows hosts.

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
- **Fix the resume race** (test-first, then the stop-and-resume drill again on a real clone).
- **Failed guests do not count towards the cap** (control service validation, the backend's error text, the
  wizard's messages, tests).
- **Remove `finish-run`:** the program, its supervisor entry, `GUEST_IP`'s last use, `test_finish_run.sh`, and the
  verify-cape and e2e references.
- **Anti-VM tells spike, then the fix:** remove the empty drives in the snapshot step; try a display adapter
  that a sample reads as a real GPU without breaking capemon, the Guacamole desktop or the snapshot; keep the
  facts script's check of both.
- **The wizard's browser e2e** in `make e2e`.
- **The `+60s` button** (interactive runs): a spike first on a real interactive run (does a task submitted with
  `timeout=1200` that the backend finishes at its own deadline give the same complete results as CAPE's own timeout;
  what the finish call's 409 window in the first seconds means for a short deadline), then test-first: the
  deadline kept in the analysis record, a backend timer that survives a restart (reattached like the guest builds),
  the `+60s` endpoint with its cap, the button and the running-out countdown in the analysis header and the LIVE
  status bar, screenshots for the Artifact review.
- **Close the questions in the docs:** update `tartarus-v1.md` open questions and note final-phase Sysmon in the
  specs.
- Exit: `make e2e`, `make verify-guest` and `make verify-wizard` pass on the real stack.

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
   guest profile or an event source); the specs stay as the reference.
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
| Agents report results optimistically (found again in M6) | Every milestone is proven on the real stack through the public API before it is called done, as M6 was |
