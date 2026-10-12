# Tartarus v1

## Summary
Tartarus v1 is a local malware-analysis workbench for a single analyst on a Linux host. It uses
CAPEv2 (in a privileged Ubuntu container, with KVM) to detonate files in a hardened Windows 10/11
guest. It adds:
- live monitoring and an interactive guest desktop;
- linked visualisations;
- a KQL-like query bar over OpenSearch;
- in-stream Sigma detection;
- tags and notes, and IOC and report export.

Everything ships as one `docker compose` stack, and the GUI is a Vue 3 + Quasar PWA in an
ice-blue cyberpunk theme.

The detailed design lives in [overview](../overview.md), [architecture](../architecture.md),
and the [specs](../specs/) and [design system](../design/design-system.md). This file is the
**scope checklist, decision log and open-questions list**.

## Goals
- Submit a file and watch it detonate live: processes, events and detections appear within ~2 s.
- Interact with the guest desktop during the run.
- Explore an analysis through linked views: process graph, timeline, events, network,
  artifacts/IOCs, detections and ATT&CK.
- Filter everything with a query bar plus quick-filter chips.
- Detect with Sigma (live), CAPE signatures, YARA and Suricata.
- Annotate with tags and notes; export STIX, MISP and CSV IOCs and HTML or PDF reports.
- Install on any Linux distro with KVM and Docker via `docker compose up`, plus a guided guest
  build.

## Non-goals (v1)
- Windows hosts. Planned after v1 as experimental, via WSL2 + nested KVM.
- Linux, Android or other guests.
- URL and archive submission; PCAP or memory-image import.
- Parallel analyses.
- Comparing analyses and searching across analyses.
- Custom rule language, sequence rules, Sigma correlation/aggregation rules.
- Multi-user, auth, remote access.
- Automatic retention or cleanup.
- Native desktop wrapper (Electron/Tauri). Markdown notes.

## Changes

### Infrastructure ([architecture](../architecture.md))
- [ ] `docker-compose.yml`: `backend`, `cape`, `opensearch`, `postgres` (DBs `tartarus` + `cape`). No `mongo` service — resolved, see Decisions.
- [ ] Volumes and bind mounts: `cape-storage` (read-only in backend), `guest-images`, `data/iso`, `rules/`
- [ ] Only `backend` is exposed, on `127.0.0.1:8080`
- [ ] `.env.example` with all settings; secrets generated on first start
- [ ] Host preflight script (KVM, CPU flags, RAM, disk, Docker)

### CAPE layer ([cape-integration](../specs/cape-integration.md))
- [ ] M0 spike: libvirt, rooter, INetSim and guacd inside the privileged container
- [ ] `cape` image pinned to `CAPE_REF`, built with `kvm-qemu.sh` + `cape2.sh`, supervisord
- [ ] Generated CAPE config overrides (kvm, routing with RFC1918 block, aux, processing, reporting/callback, api)
- [ ] Isolated guest bridge `tt-guest` inside the container namespace; INetSim as the default route

### Backend ([backend](../specs/backend.md), [data-model](../specs/data-model.md))
- [ ] FastAPI app with operation ids; OpenAPI export for `@hey-api/openapi-ts`
- [ ] PostgreSQL models + Alembic: sample, analysis, tag, tag_link, note, sigma_rule, guest_vm, job, setting
- [ ] OpenSearch index template (ECS + `tartarus.*` + `api.*`), one index per analysis
- [ ] Submission + one-at-a-time queue runner
- [ ] Live collector (BSON + ETW tailing, offsets, resume)
- [ ] Normalisers for capemon (with derived semantic events), Sysmon, ETW, Suricata, Volatility3 and CAPE report
- [ ] Report ingester (callback → catch-up → enrichment; idempotent)
- [ ] Sigma engine (pySigma ECS pipeline → in-memory matcher; flood suppression)
- [ ] KQL-like query compiler with aliases, validation and autocomplete endpoints
- [ ] Views: processes, network, artifacts, registry, detections, ATT&CK, IOCs
- [ ] WebSockets: live, desktop (Guacamole tunnel), system
- [ ] Annotations API (tags + plain-text notes)
- [ ] Exports: STIX 2.1, MISP, CSV, HTML and PDF report (job)
- [ ] Artefact downloads as password-protected zips (`infected`)
- [ ] Analysis delete (CAPE task, index, rows, unreferenced sample); disk usage
- [ ] Guest build pipeline and health checks

### GUI ([gui](../specs/gui.md), [design system](../design/design-system.md))
- [ ] Quasar PWA shell: header with health, queue and disk; mini nav; theme from `tartarus-theme.css`
- [ ] Dashboard: analyses table, queue, system, disk, empty states
- [ ] Submit dialog
- [ ] Workspace header, query bar + chips, event detail drawer, URL-synced state
- [ ] Tabs: Live (desktop, process tree, detections, stream), Overview, Processes (graph + tree), Timeline, Events (facets), Network, Artifacts, Detections (+ ATT&CK), Notes
- [ ] Export menu
- [ ] Rules page
- [ ] Guest page with build wizard
- [ ] Settings page
- [ ] Loading, empty, error, partial and disconnected states

### Docs
- [ ] README quick start, safety guide, query-syntax cheat sheet (also shown in the app)

## Acceptance criteria
- On a fresh Linux host with KVM and Docker, `docker compose up` plus the guest wizard gives a
  working sandbox with no manual CAPE configuration.
- Submitting an EXE shows the guest desktop and the first process events within seconds of the
  sample starting. Events appear in the GUI ≤ 2 s after CAPE writes them.
- The analyst can click a dialog inside the guest from the LIVE tab.
- A Sigma rule for remote thread creation fires in the live detections feed during the run.
- After the run, the process graph, timeline, network and IOC views are populated. Selecting a
  process in the graph filters the timeline and events to it.
- `proc:cmd.exe AND lane:network` returns only matching events. "Filter out" on a value adds a
  negated chip. An unknown field shows an underlined error with a suggestion.
- A tag and a note added to a process appear in the exported HTML and PDF report.
- The STIX export validates with the `stix2` validator, and the MISP export imports into MISP.
- With the default route, no packet from the guest reaches the host LAN or the internet.
- Deleting an analysis frees its disk space and removes it from every view.
- The UI matches the design system: black surfaces, 0 radius, ice-blue accents, the warm
  severity scale, and category lanes in the validated order.

## Decisions
| Decision | Reason |
|---|---|
| Solo analyst, local only, no auth, bind 127.0.0.1 | Simplest scope; the user's use case |
| Linux hosts in v1; Windows post-v1 via WSL2 + nested KVM (experimental) | CAPE is Linux-only. A container makes the software portable but still needs KVM. Nested KVM in Hyper-V is unsupported by Microsoft and unpredictable. |
| CAPE in a privileged Ubuntu 24.04 container; everything in Docker Compose | Any distro; the user's preferred deployment style |
| Windows 10/11 guests only | CAPE's Linux guest support is community-grade |
| Backend: Python + FastAPI; client via `@hey-api/openapi-ts` | Reuse CAPE/Python tooling. Same pattern as the user's Momos project |
| Custom live collector tailing BSON/ETW; final data via `callback` + report.json on the shared volume | CAPE has no streaming feed |
| OpenSearch (events) + PostgreSQL (metadata) | Full-text log search is the main UX |
| ECS field names + `tartarus.*` / `api.*` extensions | Standard; pySigma's ECS pipeline works out of the box |
| One OpenSearch index per analysis | Instant delete; no cross-run search in v1 |
| Custom KQL-like query grammar → OpenSearch DSL | Autocomplete, precise errors, field whitelisting |
| Sigma evaluated in-stream in the collector | Detections arrive at about the same time as the event |
| Frontend: Vue 3 + Quasar, PWA (no Electron/Tauri) | User knows Vue. Low RAM. Fits docker-compose. Quasar has a built-in PWA mode and data-heavy components |
| Quasar components only (Notify for toasts, plain-text notes) | No extra deps; the Momos md-editor and toastify themes were ported into Quasar overrides |
| Ice-blue accent (`#38bdf8` family), black surfaces, 0 radius, glow on focus | The user's Momos aesthetic, recoloured for blue team |
| Severity uses the warm threat scale (red, orange, amber, slate) | Threats must never look like UI decoration |
| Event-category colours: validated six-lane palette with icons and labels | Colour-blind safe on the dark surface; never colour-only |
| Interactive live desktop (Guacamole via backend proxy), clipboard disabled | ANY.RUN-style interaction, safely |
| Default route INetSim; others per run | Safe default that still captures C2 attempts |
| One analysis at a time; file submissions only; keep data forever (manual delete) | Solo-workstation scope |
| Guided auto-build of the guest from a user ISO | Guest prep is the hardest part of running CAPE |
| Sources: capemon, Sysmon, ETW, Suricata/PCAP, Volatility3 | User's choice; Sysmon and ETW complement user-mode hooks |
| Extra workflows: tags/notes and export/report only | User's choice |
| No `mongo` service | Verified from CAPE source: `tasks/create/file`, `tasks/status`, `tasks/delete`, `machines/list` and `cuckoo/status` only touch CAPE's SQL task DB; CAPE's scheduler skips the `mongodb` reporting module when it's disabled (the shipped default); `jsondump` (what Tartarus reads) has no Mongo dependency; and the one startup check that requires Mongo or Elasticsearch only fires if `web.conf [web_reporting]` is enabled, which also ships off. Keep both at their defaults. `pymongo` stays installed in the `cape` image (an unconditional import for `bson.objectid.ObjectId`), but no connection is ever opened. |

## Open questions
1. **Container spike (M0):** will libvirtd, the rooter's iptables, INetSim and guacd work
   inside the privileged `cape` container with its own network namespace? The fallback is host
   libvirt, which would tie Tartarus to Ubuntu hosts.
2. **Stop and extend a running task:** which CAPE mechanism stops a task early and extends an
   interactive one? If extending isn't supported, the `+60s` button is dropped and the timeout
   is only set at submission.
3. **Sysmon timing:** CAPE probably collects the Sysmon EVTX only at the end of the run, so
   Sysmon events would be final-phase only. Add a live forwarder in the guest later?
4. **Default Sigma ruleset:** ship a curated SigmaHQ subset (proposed) or start empty?
5. **Defender Tamper Protection:** can the guest wizard disable it fully unattended on current
   Windows builds, or is the one manual step unavoidable?
6. **Default analysis timeout:** 180 s is proposed.
7. **App icon:** design a PWA and app icon (a descending pit or gate motif in ice blue).
8. **PDF report styling:** a print variant (white background, blue accents) is proposed instead
   of a black PDF.

## Research references
- CAPEv2: https://github.com/kevoreilly/CAPEv2. Docs: https://capev2.readthedocs.io/en/latest/
  (host install, guest requirements, machinery, results layout, apiv2, interactive desktop,
  routing)
- CAPE `hyperv` machinery (March 2026, minimal): `modules/machinery/hyperv.py`
- Nested virtualization (Microsoft): https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/user-guide/nested-virtualization
- WSL config (`nestedVirtualization`): https://learn.microsoft.com/en-us/windows/wsl/wsl-config
- ECS: https://www.elastic.co/guide/en/ecs/current/index.html. pySigma: https://github.com/SigmaHQ/pySigma
- UX references: ANY.RUN (live interactive), Triage, DRAKVUF Sandbox, Elastic Security
  timeline/analyzer
