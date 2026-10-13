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
| Sandbox | CAPEv2 + KVM in a privileged Ubuntu container; Windows 10/11 guest | [specs/cape-integration.md](specs/cape-integration.md) |
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
| M1 | **Stack and final-report path** | **Foundation done** (compose stack, backend skeleton, generated API client, Quasar shell with theme, Settings). **Still to do:** submission, CAPE callback, report ingestion to OpenSearch, Dashboard and Overview, Processes, Network, Artifacts and Detections views |
| M2 | **Live** | Collector (BSON/ETW tailing), live WebSocket, LIVE tab with event stream and process tree, interactive desktop proxy |
| M3 | **Query and timeline** | KQL-like query compiler, facets, Events tab, timeline, event detail drawer |
| M4 | **Sigma** | Rule loader, in-stream matcher, Rules page, detections in the live feed |
| M5 | **Analyst workflow** | Tags and notes, IOC exports, HTML and PDF report |
| M6 | **Guest wizard** | Automated hardened guest build, health checks, self-test. **Seeded by M0b:** `make build-guest` and `make verify-guest` already do the build and the checks; the wizard adds the UI, the ISO scan and the manual Defender step. |

### Next up

Nothing blocks M1 now. libvirt's unauthenticated TCP endpoint is switched off until the guest
wizard needs it (question 1), and Defender's Tamper Protection stays on until the wizard too
(question 5). M1 proper: submit a sample from the UI, receive CAPE's callback, ingest
`report.json` into OpenSearch, and the first analysis views.

### After v1 (not designed yet)
- **Windows hosts (experimental):** the same compose stack inside WSL2 with nested KVM (see
  [cape-integration](specs/cape-integration.md#windows-hosts-post-v1-experimental)).
- **ISO drop zone:** drag a Windows ISO onto the Guest VM page instead of copying it into
  `data/iso` by hand. Needs a chunked, resumable upload (an ISO is about 5 GB, and the nginx
  limit set for samples is 512 MB), a disk-space check first, and validation on arrival: read
  the edition and build from `sources/install.wim` and, for evaluation ISOs, compare the SHA256
  against Microsoft's published hashes. Until then the wizard lists `data/iso` and explains where
  to put the file. Windows itself is never bundled or downloaded for the user (licence).
- URL and archive submission, PCAP and memory-image import.
- Compare two analyses (behaviour diff).
- Search and IOC pivot across all analyses (OpenSearch alias over the per-analysis indices).
- Parallel analyses (several guests).
- Linux guests (CAPE community support via strace/Tracee).
- Custom Tartarus rules and sequence detections. Sigma correlation rules.

## Glossary

| Term | Meaning |
|---|---|
| **Analysis** | One detonation of one sample (Tartarus id `#42`; maps to one CAPE task) |
| **Guest** | The Windows VM the sample runs in. It's reverted to the clean snapshot for every analysis |
| **capemon** | CAPE's monitor DLL injected into processes in the guest; hooks APIs |
| **Live phase / final phase** | Events streamed while running / enrichment after CAPE processing |
| **Lane** | One of six event categories (process, file, registry, network, memory, api) used for the timeline and colouring |
| **Detection** | An alert from Sigma, a CAPE signature, YARA or Suricata |
| **Route** | Network mode for an analysis (INetSim, none, drop, internet, VPN…) |
| **ECS** | Elastic Common Schema, the field naming used for events |
| **IOC** | Indicator of compromise (hash, domain, IP, URL, mutex, registry key…) |
