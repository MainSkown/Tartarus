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
- [ ] `docker-compose.yml`: `frontend`, `backend`, `cape`, `opensearch`, `postgres` (DBs `tartarus` + `cape`); `docker-compose.dev.yml` override with watch and debug ports. No `mongo` service — resolved, see Decisions.
- [ ] Volumes and bind mounts: `cape-storage` (read-only in backend), `guest-images`, `data/iso`, `rules/`
- [ ] Only `frontend` (nginx, proxying `/api` and `/ws` to the backend) is exposed, on `127.0.0.1:8080`
- [ ] `.env.example` with all settings; secrets generated on first start
- [ ] Host preflight script (KVM, CPU flags, RAM, disk, Docker)

### CAPE layer ([cape-integration](../specs/cape-integration.md))
- [ ] M0 spike: libvirt, rooter, INetSim and guacd inside the privileged container
- [ ] `cape` image pinned to `CAPE_REF`, built with `kvm-qemu.sh` + `cape2.sh`, supervisord
- [ ] Generated CAPE config overrides (kvm, routing with RFC1918 block, aux, processing, reporting/callback, api)
- [ ] Isolated guest bridge `tt-guest` inside the container namespace; INetSim as the default route

### Backend ([backend](../specs/backend.md), [data-model](../specs/data-model.md))
- [ ] FastAPI app with operation ids, serving the schema at `/openapi.json` for `@hey-api/openapi-ts`
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
- [ ] Quasar PWA shell: header with health, queue and disk; mini nav; theme from `src/css/app.css`
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
| Defender in the guest is the user's choice, **on by default** (a guest-build option; off means one manual step) | Which is right depends on the malware. Known malware is detected either way, but newer samples may check whether Defender is running and behave differently when it is off, since that suggests a sandbox; and leaving it on shows how a sample gets past Defender. Turning it off helps when Defender would remove a sample before it runs. On by default also means the default build needs no manual step. Turning Tamper Protection off cannot be scripted. |
| Separate `frontend` container: Vite in dev, nginx in prod proxying `/api` and `/ws` | Same pattern as the user's Momos project; fast HMR; still one published port |
| The guest wizard (M6) will control libvirt via `qemu+tcp://cape/system`, off until then; never mount the Docker socket | The Docker socket is root on the host, and the backend processes untrusted malware data |
| No `mongo` service | Verified from CAPE source: `tasks/create/file`, `tasks/status`, `tasks/delete`, `machines/list` and `cuckoo/status` only touch CAPE's SQL task DB; CAPE's scheduler skips the `mongodb` reporting module when it's disabled (the shipped default); `jsondump` (what Tartarus reads) has no Mongo dependency; and the one startup check that requires Mongo or Elasticsearch only fires if `web.conf [web_reporting]` is enabled, which also ships off. Keep both at their defaults. `pymongo` stays installed in the `cape` image (an unconditional import for `bson.objectid.ObjectId`), but no connection is ever opened. |

## Open questions
1. **How to protect libvirt's TCP endpoint when the guest wizard needs it (M6, not before).**
   Resolved for now by switching the endpoint off: it has no authentication, and the container is
   privileged, so any container on `tartarus-internal` reaching it would be host root. `make
   verify-cape` enforces that it stays off. For M6 the options are: (a) a network shared only by
   `cape` and `backend`; (b) SASL or TLS client certificates; (c) drop the remote libvirt API for a
   small control service inside `cape` that exposes only define, snapshot, start and stop.
   Recommended: (a) plus (b) or (c), since the backend parses untrusted malware reports.
2. **Stop and extend a running task:** which CAPE mechanism stops a task early and extends an
   interactive one? If extending isn't supported, the `+60s` button is dropped and the timeout
   is only set at submission.
3. **Sysmon timing:** CAPE probably collects the Sysmon EVTX only at the end of the run, so
   Sysmon events would be final-phase only. Add a live forwarder in the guest later?
4. **Default Sigma ruleset:** ship a curated SigmaHQ subset (proposed) or start empty?
5. **Defender: how the choice is offered (decided: optional, on by default; details for M6).**
   Defender's state is a property of the analysis environment, so the guest wizard offers it as an
   option, and the default build leaves it on, which needs no manual step. Turning it off cannot
   be scripted (Tamper Protection ignores the policy keys and `Set-MpPreference`; bypass methods
   were not tried), so choosing "off" makes the wizard pause once for the user to switch Tamper
   Protection off in Windows Security on the live desktop, then re-apply the settings. Open for M6:
   - **One guest, or two?** The state is baked into the snapshot, so one guest is one state. The
     v1 proposal is one guest with the option chosen at build time. Letting the analyst pick per
     submission needs two registered guests (two domains with their own snapshots, sharing the
     base image as a backing file); CAPE's current one-registration-at-a-time limit (M0b) has to
     be lifted first, so that is post-v1.
   - **Report what Defender did.** When it is on, record its verdict: the Windows Defender
     operational event log (detections and remediation), and whether the sample file or its
     process was removed, so an analysis says "Defender removed the sample" instead of showing an
     empty run. A self-test for the option with the EICAR antivirus test string (harmless, and
     detected by design) would prove Defender is really on or really off.
6. **Default analysis timeout:** 180 s is proposed.
7. **App icon:** design a PWA and app icon (a descending pit or gate motif in ice blue).
8. **PDF report styling:** a print variant (white background, blue accents) is proposed instead
   of a black PDF.
9. **Maximum sample upload size:** 512 MB is proposed (nginx `client_max_body_size` on `/api/`).
10. **Remaining sandbox-detection tells (from M0b):** remove the two empty optical drives once the
    guest is installed? The display adapter is "Microsoft Basic Display Adapter" (no GPU driver).
    Both are cheap to leave and moderately cheap to fix; decide how far to go.
11. **The guest's default password** (`Tartarus1!`, overridable with `GUEST_PASSWORD`) is in the
    repo and stored in plain text for autologon. Fine for a throwaway account in an isolated
    guest; say so if you want a generated one per build instead.

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
