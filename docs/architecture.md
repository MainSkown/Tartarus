# Architecture

This document covers how Tartarus is put together: the containers, the data flows, the network
isolation and the tech stack. The details of each part are in the [specs](specs/).

## Component map

```
 ┌──────────────────────────── Linux host (any distro: KVM + Docker) ─────────────────────────────┐
 │                                                                                                │
 │  Browser / installed PWA ──HTTP + WS──► 127.0.0.1:8080 (the only published port)               │
 │                                  │                                                             │
 │  ┌────────────────────── docker compose: network "tartarus-internal" ───────────────────────┐  │
 │  │                                  ▼                                                       │  │
 │  │  ┌─ frontend (nginx) ───────────────────────────────────────────┐                        │  │
 │  │  │ Quasar PWA build · proxies /api and /ws to backend:8000      │                        │  │
 │  │  └──────────────────────────────┬───────────────────────────────┘                        │  │
 │  │                                 ▼                                                        │  │
 │  │  ┌─ backend (FastAPI, Python) ────────────────────────────────────────────────┐          │  │
 │  │  │ REST /api · WS /ws                                                         │          │  │
 │  │  │ collector ─► normaliser (ECS) ─► Sigma matcher ─► bulk indexer ─► pub/sub  │          │  │
 │  │  │ report ingester · query compiler · export · guest client · job runner      │          │  │
 │  │  └──┬────────────┬───────────────────┬────────────────────────┬───────────────┘          │  │
 │  │     │ SQL        │ HTTP              │ apiv2 · guacd · control  │ read-only              │  │
 │  │     ▼            ▼                   ▼                        ▼ storage volume           │  │
 │  │  ┌──────────┐ ┌────────────┐      ┌─ cape (privileged Ubuntu 24.04) ──────────────┐      │  │
 │  │  │ postgres │ │ opensearch │      │ cape · cape-processor · cape-web (apiv2)      │      │  │
 │  │  │ tartarus │ │ events     │      │ rooter · suricata · inetsim · guacd           │      │  │
 │  │  │ + cape DB│ │            │      │ libvirtd + QEMU · guest-control · /dev/kvm    │      │  │
 │  │  └──────────┘ └────────────┘      │        │ bridge "tt-guest" (isolated)         │      │  │
 │  │                                   │        ▼                                      │      │  │
 │  │                                   │ guests (Windows 11): capemon · agent · Sysmon │      │  │
 │  │                                   └───────────────────────────────────────────────┘      │  │
 │  └──────────────────────────────────────────────────────────────────────────────────────────┘  │
 │                                                                                                │
 └────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The diagram shows `tartarus-internal`. `backend` and `cape` also share a second network,
`tartarus-control`, that nothing else joins: the guest control service in `cape` listens only there.

## Compose services

| Service | Image | Purpose | Exposed to host |
|---|---|---|---|
| `frontend` | `tartarus/frontend` (built from `frontend/`; targets `dev-stage` = Vite dev server, `production-stage` = nginx) | Serves the Quasar PWA build and reverse-proxies `/api` and `/ws` to `backend:8000` | `127.0.0.1:8080` only (prod) |
| `backend` | `tartarus/backend` (built from `backend/`; targets `dev` = uvicorn `--reload`, `prod`) | API, WebSocket, collector, ingester, rules, export, jobs, the client of the guest control service | nothing in prod (dev: `127.0.0.1:8000`) |
| `cape` | `tartarus/cape` (built from the repo root: `cape/` and `guest/`) | CAPE + KVM/libvirt + rooter + Suricata + INetSim + guacd + the guest control service | nothing |
| `opensearch` | `opensearchproject/opensearch:3.9.0` (single node, security plugin disabled, internal network only) | Event store | nothing |
| `postgres` | `postgres:16` | Two databases: `tartarus` (Tartarus metadata) and `cape` (CAPE's task DB) | nothing |

CAPE's Mongo-backed report viewer is **not used**: `web.conf [web_reporting]` and
`reporting.conf [mongodb]` stay at their shipped defaults (both `off`). Tartarus's calls
(`tasks/create/file`, `tasks/status`, `tasks/delete`, `machines/list`, `cuckoo/status`) only
touch CAPE's SQL task DB, and the final report is read from `report.json` (written by the
`jsondump` module, which has no Mongo dependency) — so there's no `mongo` service at all. The
`cape` image still has `pymongo` installed (an unconditional import in `apiv2/views.py` for
`bson.objectid.ObjectId`), but nothing ever opens a connection with it.

- **One command:** `docker compose up -d`. Config lives in `.env` (see `.env.example`).
- **Development:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --watch`
  (wrapped by `make dev`). The dev override switches `frontend` and `backend` to their dev build
  targets, syncs source with compose `develop.watch` (rebuilding on `pyproject.toml`/`uv.lock`/
  `package.json` changes), and publishes debug ports on `127.0.0.1` only: Vite `5173` (proxies
  `/api` and `/ws` to the backend), backend `8000` (OpenAPI docs at `/docs`), Postgres `5432`,
  OpenSearch `9200`.
- **Backend → guests (the control service):** the backend never talks to libvirt and has no Docker access.
  Building, cloning, checking and deleting guests is done by `guest-control`, a small stdlib HTTP service
  that runs in the `cape` container (a supervisord program) over the guest engine (`cape/guest_engine/`),
  and exposes only those operations, with every parameter validated. It listens on a **second compose
  network, `tartarus-control`** (`internal: true`, so it has no route out), that only `cape` and `backend`
  join, and every request but its health probe needs the bearer token `GUEST_CONTROL_TOKEN` from `.env`. So
  libvirt's unauthenticated TCP endpoint stays **off** (`libvirtd` runs without `--listen`), `libvirt-python`
  is not used, and the Docker socket is **never** mounted into any container: it is root on the host, and the
  backend handles malware artefacts and untrusted report data. `make verify-cape` enforces all of it: the
  token is required, the service is unreachable from `frontend`, `opensearch` and `postgres`, and nothing
  listens on `16509`. The container is privileged, so the service is root-equivalent there; a compromised
  backend can build and delete guests, not run anything else. The design and the routes are in
  [CAPE integration](specs/cape-integration.md#the-control-service); what differs between operating
  systems is a guest profile, described in [guest profiles](specs/guest-profiles.md). The guest build runs in the control
  service, not in the backend: a backend job only follows it, so a backend restart does not stop a build.
- **Guests on disk:** the `guest-images` volume holds each guest's disk, snapshot files and nvram under
  `images/` and `nvram/`, the registry of guests (`tartarus/guests/<name>/guest.json` and the builds'
  records), the download cache, and the single CAPE registration file (`tartarus/kvm.conf.d/guests.conf`). The
  registry is the one source of truth; the libvirt domains and the CAPE registration are derived from it.
- **Host prerequisite for OpenSearch:** `vm.max_map_count ≥ 262144` (checked by the preflight
  script).
- **Volumes:** `pg-data`, `os-data`, `cape-storage` (CAPE `storage/`; mounted
  read-write in `cape` and **read-only** in `backend`), `guest-images` (qcow2 disks and
  snapshots, and the guest registry), `./data/iso` (bind mount, read-only in `cape`, where the user
  drops installation media), `./rules` (bind mount for Sigma rules).
- **Only the frontend (nginx) is reachable from the host**, and only on `127.0.0.1`. The backend,
  guacd, libvirtd, CAPE apiv2,
  OpenSearch and the databases are reachable on the internal compose network only, and the guest
  control service on `tartarus-control` only.
- **Resources (defaults in `.env`):** OpenSearch heap 1.5 GB, guest 2 vCPU / 4 GB RAM, CAPE
  processing 2 workers. Minimum host 16 GB RAM, 4 cores and 200 GB free disk; recommended 32 GB.
  Each guest is about 22 GB on disk and there can be at most five.

## Repository layout

```
tartarus/
├── docker-compose.yml
├── .env.example
├── backend/            FastAPI app (see specs/backend.md)
│   ├── pyproject.toml
│   ├── app/
│   └── alembic/
├── frontend/           Quasar app, PWA mode (see specs/gui.md)
│   └── src/api/             @hey-api/openapi-ts output (do not edit; `npm run api:sync`)
├── cape/               Dockerfile (built from the repo root), supervisord config, CAPE conf overrides,
│   │                   entrypoint
│   ├── bin/                 guest-control (the control service), guest-build (its command-line client),
│   │                        wait-then-exec, ...
│   ├── guest_engine/        the guest engine behind the control service: profiles, registry, sequencer,
│   │                        validation, registration, self-test; it never names an operating system
│   └── conf/
├── guest/              what a guest is made of (copied into the cape image; see specs/guest-profiles.md)
│   ├── profiles/<id>/       one directory per operating system: profile.json and its own steps and files
│   │   └── windows/         the only profile so far
│   ├── steps/               generic build and clone steps (preflight, fetch, define, copy, snapshot, ...)
│   ├── domain/              libvirt domain template and the hardware fragments
│   └── personas/            the SMBIOS persona shared by every profile
├── rules/sigma/        Sigma rules (bind-mounted, user-editable)
├── data/iso/           user-supplied installation media (git-ignored)
└── docs/
```

## Data flow

### 1. Submission
GUI → `POST /api/analyses` (multipart) → the backend stores the sample, writes an `analysis` row
(`queued`) and, when the queue is free, calls CAPE `apiv2/tasks/create/file` with options
(the guest to run on as the CAPE `machine`, route, timeout, package, memory dump, interactive). It saves `cape_task_id` and starts watching
the task.

### 2. Live phase (while the guest runs)
1. capemon in the guest streams per-process BSON over TCP to CAPE's ResultServer, which appends
   to `storage/analyses/<task>/logs/<pid>.bson`. ETW aux modules write JSON under `aux/`.
2. The backend **collector** watches that directory (inotify via `watchfiles`) and reads only new
   bytes from each file, keeping an offset per file. It parses records with CAPE's BSON log
   format (code reused from CAPE's `netlog.py`).
3. The **normaliser** maps each record to an ECS document (see
   [data-model](specs/data-model.md)) with a deterministic `event.id`.
4. The **Sigma matcher** checks every normalised event in-stream. A match emits a `detection`
   event linked to the triggering event(s).
5. The **bulk indexer** writes batches to OpenSearch every ≤250 ms or 500 events, whichever
   comes first.
6. **Live pub/sub** (in-process asyncio broadcast) pushes the same batches to subscribed
   WebSocket clients. The target is under 2 s from CAPE writing a record to it appearing in the
   GUI.
7. **Interactive desktop:** the GUI opens `WS /ws/analyses/{id}/desktop`, and the backend tunnels
   the Guacamole protocol to `guacd` in the `cape` container, which connects to the guest's
   QEMU VNC.

### 3. Final phase (after the guest stops)
1. CAPE processes the task (behaviour, network, Suricata, CAPE payloads/configs, YARA,
   signatures, ATT&CK, optional Volatility3) and writes `reports/report.json`.
2. CAPE's `callback` reporting module calls `POST /internal/cape/callback` with `{task_id}`.
3. The **report ingester** first runs a collector catch-up pass, reading any BSON bytes not yet
   tailed. It then reads `report.json` from the shared volume and indexes the *enrichment*:
   signatures, TTPs, network (DNS/HTTP/TLS/flows with process attribution), Suricata alerts,
   dropped files, payloads and configs, YARA, Volatility3 findings, Sysmon EVTX events,
   screenshots and malscore. API calls are **not** re-indexed from the report because the
   collector already has them, so deterministic IDs make re-runs idempotent.
4. Sigma runs again over the events that only exist in the final phase (Sysmon, Suricata,
   Volatility).
5. The analysis becomes `done` with `phase = final`, and a WebSocket `phase` message tells the
   GUI to refresh its views.

### 4. Viewing and querying
All views read from OpenSearch through the backend. The GUI never queries OpenSearch directly.
Query-bar strings are compiled by the backend (KQL-like grammar → OpenSearch DSL), scoped to one
analysis index. Process tree, network summary and IOCs come from dedicated endpoints that
aggregate events and report data.

## Network and isolation model

- Each guest's NIC is attached to bridge `tt-guest` (default `192.168.150.0/24`, host side `.1`, guests
  on static addresses from `.10`, and a DHCP pool `.100` to `.119` only for a guest that cold-boots). The bridge exists **only inside the `cape` container's network namespace** and is
  never bridged to the host LAN.
- CAPE's rooter (inside `cape`) applies the per-analysis route with iptables in that namespace:
  - `inetsim` (default): all guest traffic is DNAT'd to INetSim on the bridge gateway.
  - `none` / `drop`: no egress.
  - `internet`: NAT out through the container's interface. RFC1918, link-local and the Docker
    networks are **blocked** so the sample can't reach the host LAN or other containers.
  - `vpn` / `wireguard` / `socks5`: through the configured tunnel. Same RFC1918 block.
- Ports guests can reach: the ResultServer (2042) and the gateway services required by the
  route. The agent (8000) is reached from CAPE to the guest only.
- The PCAP is captured on `tt-guest` by CAPE (tcpdump), so every packet is recorded no matter
  which route is used.
- Samples are stored zipped at rest. Downloads are always zip archives with password `infected`.
- No authentication: the frontend's nginx binds `127.0.0.1:8080` and is the only published port. Exposing it beyond localhost is
  explicitly unsupported in v1.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Sandbox | CAPEv2 (pinned commit), KVM/QEMU patched by `kvm-qemu.sh`, libvirt | Inside privileged `cape` container |
| Backend | Python 3.12, FastAPI, Pydantic v2, Uvicorn (1 worker; collector and pub/sub run in-process) | |
| Backend libs | SQLAlchemy 2 + asyncpg + Alembic; opensearch-py (async); watchfiles; pySigma (rule parsing + ECS pipeline); lark (query grammar); stix2; Jinja2 + WeasyPrint (reports); pyguacamole-style tunnel | |
| API client | `@hey-api/openapi-ts`, generated from the running backend's `/openapi.json` into `frontend/src/api` | Same setup as Momos. Regenerate with `npm run api:sync` (or `make api-sync`); the output is committed |
| Frontend | Vue 3 + Quasar (Vite, TypeScript), Pinia, Vue Router, PWA mode | Dark only. Theme in [design-system](design/design-system.md) |
| Viz | Cytoscape.js + cytoscape-dagre (process graph); custom canvas timeline (d3-scale / d3-zoom); guacamole-common-js (desktop) | |
| Stores | OpenSearch 3.x (events), PostgreSQL 16 (metadata + CAPE task DB) | No Mongo service; see Compose services above |
| Packaging | Docker Compose | |

## Process model and concurrency

- One analysis at a time: the backend's **queue runner** submits the next queued analysis only
  when the current one reaches a terminal state.
- Long jobs (guest build, PDF export, delete, re-ingest) go through a small **job runner**
  (asyncio tasks persisted in the `job` table) so progress survives a browser reload. If the
  backend restarts, a running job is marked `interrupted`. A guest build is the exception that
  shows why a job is only a follower: the build lives in the control service, and the backend
  starts a new job for it at start-up. Builds, deletes and analyses exclude each other, because
  registering or deleting a guest restarts `cape` (see
  [CAPE integration](specs/cape-integration.md#building-checking-deleting-and-analysing-exclude-each-other)).
- On backend start, the collector resumes any running analysis from the stored file offsets.
