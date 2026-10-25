# History: how v1 was built

These are the working records of how Tartarus v1 was built, kept as history: the plans each milestone was written
against, the decisions taken on the way, and the findings of the spikes and proof runs. They describe what was
planned and tried, so they can be out of date. The specs in [docs/specs](../specs/) are the reference for how the
system works now.

## Milestones

- [Foundation](foundation.md): the compose stack, the backend and the frontend skeletons, with the app shell and live health dots.
- [M0, CAPE container spike](m0-cape-spike.md): proved CAPE, libvirt, the rooter, INetSim and Guacamole run in one privileged container with a Windows guest.
- [M1a, submit and report](m1a-submit-and-report.md): submit a sample from the UI and read its score and detections.
- [M1b, explore a report](m1b-explore-a-report.md): the processes, network, artifacts and detections views over the event index.
- [M2, live](m2-live.md): watch an analysis as it runs, with the live event stream, process tree and interactive desktop.
- [M3, query and timeline](m3-query-and-timeline.md): the query language, the Events table with facets, the timeline and the event drawer.
- [M4, Sigma](m4-sigma.md): Sigma rules evaluated live and at final ingest, with a shipped ruleset and the Rules page.
- [M5, analyst workflow](m5-analyst-workflow.md): tags and notes, the STIX, MISP and CSV exports, and the HTML and PDF report.
- [M6, guest wizard](m6-guest-wizard.md): building, cloning, checking and deleting Windows guests from the GUI, with up to five guests.
- [M7, foundations](m7-foundations.md): the cancellable build, the `+60s` extension, the resume race fix and the removal of `finish-run`.
- [M7b, frontend i18n](m7b-frontend-i18n.md): every user-facing frontend string moved into an English locale catalogue.
- [M8, event sources](m8-event-sources.md): Sysmon events, Defender's verdict and the memory dump with Volatility3 findings; ETW was dropped from v1.
- [M9, beyond one run](m9-beyond-one-run.md): PCAP and memory-image import, a cross-analysis Search page, and parallel analyses on several guests.
- [M10, guest proofs](m10-guest-proofs.md): the four guest proofs run for real, and the nine problems they found fixed.
- [M11, hardening and release](m11-hardening-and-release.md): the security review, its fixes, the docs move and the release gates.

## Finish line and follow-ups

- [Finish line](finish-line.md): the roadmap from M7 to the release, with the decisions taken on the open questions.
- [M11 follow-ups](m11-followups.md): the items the security review left open after its fix waves, some fixed the same day and the rest scheduled or accepted as risk.

## Spike and notes folders

- [m4-sigma-spike/](m4-sigma-spike/): the Sigma rules the M4 spike proposed for the default ruleset.
- [m5-r0-spike/](m5-r0-spike/): the R0 spike for the report: a process-tree SVG prototype, the report template and its fonts.
- [m6-spikes/](m6-spikes/): findings and notes of the M6 guest spikes S0a to S0e.
- [m6-notes/](m6-notes/): the per-step notes of M6 (B1 to G1 and the C-series fixes).
- [m7-spikes/](m7-spikes/): the M7 spikes: the `+60s` finish timing (S1), the anti-VM display adapter (S2) and the P1 to P3 results.
- [m7b-notes/](m7b-notes/): the M7b spike findings and notes, and the script that compares screenshots.
- [m8-spikes/](m8-spikes/): the M8 spike findings and notes, with the Defender, Sysmon, ETW and Volatility3 fixtures.
- [m9-spikes/](m9-spikes/): the M9 spike findings (P1 to P3), the PCAP and memory fixtures, and the scripts that built them.
- [m10-notes/](m10-notes/): the notes of the M10 proof runs and of the fixes they led to.
- [m11-notes/](m11-notes/): the M11 security reviews (G1 to G6) and fix waves (C1 to C5), kept as the record behind [docs/security.md](../security.md).
