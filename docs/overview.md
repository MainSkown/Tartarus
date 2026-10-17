# Tartarus overview

> *Tartarus: the abyss where the dangerous things are locked away and watched.*

Tartarus is a **local malware-analysis workbench** for a single analyst. You drop a Windows
sample in, it detonates inside an isolated, hardened Windows VM, and you watch it happen **live**:
- processes spawning;
- files, registry and network activity;
- API calls;
- detections firing.

You can also click around inside the guest desktop while it runs. Afterwards you dig through
everything with linked views and a query bar, annotate what matters, and export IOCs and a
report.

It's the blue-team sibling of the developer's red-team tool (Momos) and shares its cyberpunk
terminal look, recoloured ice blue.

## Why not just CAPE?

[CAPEv2](https://github.com/kevoreilly/CAPEv2) is the detonation engine, and it's excellent at
monitoring, payload and config extraction, and signatures. Tartarus adds what CAPE's web UI
doesn't have:

| Need | CAPE web UI | Tartarus |
|---|---|---|
| Watch the run as it happens | Post-mortem report only | Live event stream, process tree and detections within ~2 s |
| Interact with the guest | KVM Guacamole view, no auth, separate page | Embedded interactive desktop, proxied safely |
| Explore huge logs | Behaviour tab struggles with large API logs | OpenSearch-backed, paged, faceted, query bar |
| Visualise | Static process tree, bingraph images | Interactive process graph, multi-lane timeline, ATT&CK matrix |
| Detection | CAPE signatures + YARA | + Sigma, live, on a normalised ECS event stream |
| Analyst workflow | Minimal | Tags and notes on analyses, processes and events. STIX, MISP and CSV export, HTML and PDF reports |
| Setup | Manual Ubuntu host + manual guest prep | `docker compose up` on any Linux distro plus a guided guest build |

## Components

| Component | What it is | Spec |
|---|---|---|
| GUI | Vue 3 + Quasar web app, installable PWA | [specs/gui.md](specs/gui.md) |
| Backend | Python/FastAPI: API, live collector, ingester, Sigma, query, export | [specs/backend.md](specs/backend.md) |
| Database | OpenSearch (events, ECS) + PostgreSQL (metadata) | [specs/data-model.md](specs/data-model.md) |
| Sandbox | CAPEv2 + KVM in a privileged Ubuntu container; Windows guests, built from profiles ([specs/guest-profiles.md](specs/guest-profiles.md)) | [specs/cape-integration.md](specs/cape-integration.md) |
| Look & feel | Ice-blue cyberpunk design system | [design/design-system.md](design/design-system.md) |

[architecture.md](architecture.md) explains how they fit together. The v1 scope, decisions and
open questions are in [features/tartarus-v1.md](features/tartarus-v1.md).

## Who it's for

One analyst on their own Linux workstation or lab box. There are no accounts, no sharing and no
remote access. Everything binds to `127.0.0.1`.

## Roadmap

### v1 milestones (proposed order)
| # | Milestone | Outcome |
|---|---|---|
| M0 | **Container spike** | **Done.** The privileged `cape` container runs a script-built Windows 11 guest and completes a CAPE analysis end to end (libvirt, KVM, rooter, INetSim, guacd, capemon on build 26200). See the [M0 plan](plans/m0-cape-spike.md). |
| M1 | **Stack and final-report path** | **Done and approved.** M1a (submit a sample, the queue, the CAPE callback, the Dashboard, the Submit dialog and the analysis page) and M1b (the event index, the capemon, network and signature normalisers, and the Processes, Network, Artifacts and Detections views). Verified end to end on the real stack by `make e2e DRILLS=1`. See the [M1a](plans/m1a-submit-and-report.md) and [M1b](plans/m1b-explore-a-report.md) plans. |
| M2 | **Live** | **Built and verified on the real stack** ([plan](plans/m2-live.md)): collector (capemon BSON logs), live WebSocket, LIVE tab with event stream and process tree, interactive desktop (guacd tunnel and panel). ETW tailing and live detections wait for later sources and M4. |
| M3 | **Query and timeline** | **Built and approved** ([plan](plans/m3-query-and-timeline.md)): KQL-like query compiler, facets, Events tab, timeline, event detail drawer; `make e2e` proves the query API and the two tabs on a real run (73 checks). |
| M4 | **Sigma** | **Done** ([plan](plans/m4-sigma.md)): rule loader, in-stream matcher, Rules page, detections in the live feed; `make e2e` proves the rules live and final on a real run (85 checks). Closed by the user on 2026-10-17. |
| M5 | **Analyst workflow** | **Done and approved** ([plan](plans/m5-analyst-workflow.md)): tags and notes, IOC exports (STIX, MISP, CSV), HTML and PDF report. |
| M6 | **Guest wizard** | **Done** ([plan](plans/m6-guest-wizard.md)). Guests are built, cloned, checked and deleted from the GUI through a token-authenticated control service in the `cape` container; there can be up to five, the analyst picks one for each analysis, and an operating system is a [guest profile](specs/guest-profiles.md) (Windows is the first). Verified on the real stack through the public API with the user's Polish Windows 11 25H2 ISO: a build (about 16 minutes) and clones (about 5) reached `ready` through their self-tests, Defender went off by a scripted step and on again, a failing self-test left a guest `failed` and unregistered, and builds survived a backend restart and a control-service stop. Not run for real: a failing install step, a Windows 10 ISO, another UI language, the manual Defender pause, the build desktop in a browser, and a Linux profile (paper design only). |
| M7 | **Foundations** | **Done 2026-10-17** ([plan](plans/m7-foundations.md)): a build can be cancelled, interactive runs can be extended with `+60s` (the backend ends them at the deadline), the resume race is fixed, failed guests are off the cap, `finish-run` is gone, run-mode guests have no optical drives, the wizard has a browser e2e in `make e2e`, and the open questions are closed. |
| M7b | **Frontend i18n** | Planned ([finish line](plans/finish-line.md#m7b-frontend-i18n-english-only)): every user-facing string of the frontend moves into a locale catalogue, English only, before M8's and M9's new screens; the screenshots must come out identical. |
| M8 | **More event sources** | Planned: Sysmon, ETW and Volatility3 events (final phase), the memory-dump option, and what Defender did in an analysis. |
| M9 | **Beyond one run** | Planned: PCAP and memory-image import, a cross-analysis Search page with IOC pivot, parallel analyses on several guests. |
| M10 | **Guest proofs** | Planned: the manual Defender pause, a failing install step, a Windows 10 ISO and an English-language Windows ISO, run for real. |
| M11 | **Hardening and release** | Planned: security review, CI on GitHub Actions, docs cleanup, GPL-3.0 and release files, a clean-host install test, `v1.0.0`. |

### Next up

M0 to M7 are built and M7b (frontend i18n) is next, then M8. The rest of v1 is M7b to M11, decided with the user on 2026-10-17 and written down in the
[finish line](plans/finish-line.md): foundations, then features, then guest proofs, then hardening and release.
Open questions are closed there too (see the [v1 open questions](features/tartarus-v1.md#open-questions)).

### After v1 (not designed yet)
- **Windows hosts (experimental), dropped from the v1 finish line until a Windows host is available to test on:** the same compose stack inside WSL2 with nested KVM (see
  [cape-integration](specs/cape-integration.md#windows-hosts-post-v1-experimental)).
- **ISO drop zone:** drag a Windows ISO onto the Guest VM page instead of copying it into
  `data/iso` by hand. Needs a chunked, resumable upload (an ISO is about 5 GB, and the nginx
  limit set for samples is 512 MB), a disk-space check first, and validation on arrival: read
  the edition and build from `sources/install.wim` and, for evaluation ISOs, compare the SHA256
  against Microsoft's published hashes. Until then the wizard lists `data/iso` and explains where
  to put the file. Windows itself is never bundled or downloaded for the user (licence).
- URL and archive submission. (PCAP and memory-image import are M9.)
- Compare two analyses (behaviour diff).
- **A Linux profile and the normaliser that reads Linux runs.** The profile is a new directory under
  `guest/profiles/` ([guest profiles](specs/guest-profiles.md), with the checklist from S0e); CAPE's
  Linux support is community-grade and its monitor is `strace` text, so the events of a Linux run need
  their own normaliser, and until it exists a Linux guest could be built and run by CAPE but its analyses
  would show report-level data only.
- **Linked clones** that share the source's disk, to save the 22 GB per guest (at the cost of tying two
  guests' lifetimes).
- **Profile `extends`**, so two Linux distributions can share an apt and systemd base.
- Custom Tartarus rules and sequence detections. Sigma correlation rules.

## Glossary

| Term | Meaning |
|---|---|
| **Analysis** | One detonation of one sample (Tartarus id `#42`; maps to one CAPE task) |
| **Guest** | A VM the sample runs in (Windows today). There can be several, each reverted to its clean snapshot for every analysis; the analyst picks one per analysis |
| **Guest profile** | The directory that holds what differs between operating systems: how to read the media, install, provision, name and test a guest |
| **capemon** | CAPE's monitor DLL injected into processes in the guest; hooks APIs |
| **Live phase / final phase** | Events streamed while running / enrichment after CAPE processing |
| **Lane** | One of six event categories (process, file, registry, network, memory, api) used for the timeline and colouring |
| **Detection** | An alert from Sigma, a CAPE signature, YARA or Suricata |
| **Route** | Network mode for an analysis (INetSim, none, drop, internet, VPN…) |
| **ECS** | Elastic Common Schema, the field naming used for events |
| **IOC** | Indicator of compromise (hash, domain, IP, URL, mutex, registry key…) |
