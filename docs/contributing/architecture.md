# Architecture for contributors

One page: which containers exist, how one analysis moves through them, and where the guest
isolation lives. The full component map, the network tables and the process model are in the
[architecture](../architecture.md) document. Each part's detail is in the [specs](../specs/).

## Containers

| Container | Built from | What it does |
|---|---|---|
| `frontend` | `frontend/` (nginx in production, the Vite dev server in dev) | Serves the Quasar PWA and proxies `/api` and `/ws` to the backend. The only port published to the host: `127.0.0.1:8080` |
| `backend` | `backend/` (FastAPI, uvicorn) | REST and WebSocket API, the live collector, the report ingester, the Sigma matcher, the query compiler, exports, the job runner and the queue runner. It is a client of the guest control service and has no libvirt and no Docker socket |
| `cape` | the repo root, for `cape/` and `guest/` | CAPE, KVM and libvirt, the rooter, Suricata, INetSim, guacd and the guest control service. It is privileged |
| `postgres` | `postgres:16` | Two databases: `tartarus` (metadata) and `cape` (CAPE's task database) |
| `opensearch` | `opensearchproject/opensearch:3.9.0` | One index per analysis, holding every event |

Source: `docker-compose.yml`. No MongoDB is used; the final report is read from `report.json`.

## One analysis, end to end

1. **Submit.** The GUI posts to `POST /api/analyses`. The backend stores the sample and writes an
   `analysis` row with status `queued` (`backend/app/analyses/submission.py`).
2. **Queue.** The queue runner (`backend/app/analyses/runner.py`) sends queued analyses to CAPE
   through apiv2, one at a time per guest, and keeps `cape_task_id`. All of its state is in the
   database, so a restarted runner carries on.
3. **Run.** CAPE starts the guest on the isolated `tt-guest` bridge. capemon in the guest streams
   per-process BSON logs to CAPE's ResultServer, which writes them into the task's `logs/` folder.
4. **Live.** The collector (`backend/app/live/collector.py`) watches that folder and reads only the
   new bytes of each file. `LiveCapemon` (`backend/app/ingest/live_capemon.py`) turns each record
   into an ECS event with a deterministic id. Sigma runs in the stream. Batches go to OpenSearch and
   to the live WebSocket (`backend/app/ws/live.py`).
5. **Finish.** CAPE writes `reports/report.json` and calls `POST /internal/cape/callback`
   (`backend/app/api/internal.py`).
6. **Final ingest.** The runner drains the live collector first. The report ingester
   (`backend/app/ingest/ingester.py`) then runs the normalisers from `default_normalizers()` over
   `report.json` and the files beside it: signatures, network, Sysmon, Defender and Volatility. API
   calls are not indexed a second time, and deterministic ids make a re-run harmless. Sigma runs over
   the whole ingest, live and final events alike. The analysis becomes `done`.
7. **Views and exports.** Every view, query and export reads OpenSearch through the backend
   (`backend/app/views/`, `backend/app/export/`). The GUI never talks to OpenSearch.

Detail: [backend, live collector](../specs/backend.md#live-collector) and
[data model](../specs/data-model.md).

## Networks

The compose networks are split so that each service sees only its peers:

- `tartarus-db` (backend and postgres), `tartarus-search` (backend and OpenSearch),
  `tartarus-cape-db` (cape and postgres) and `tartarus-control` (cape and backend) are all
  `internal: true`: no route out.
- `tartarus-search` holds only the backend and OpenSearch because OpenSearch has no authentication.
- `tartarus-control` holds the guest control service, which nothing else may reach.
- `tartarus-internal` (cape and backend) keeps a route out, because CAPE's guest traffic leaves
  through it.

The guests' bridge `tt-guest` exists only inside the `cape` container's network namespace. It is
never bridged to the host LAN. Full table: [architecture, networks](../architecture.md#networks).

## Where guest isolation lives

A guest runs malware, so the guest network is treated as hostile. Two layers in `cape/` enforce it:

- **CAPE's rooter** (CAPE's own code, in the container) adds iptables rules for each analysis's
  route: INetSim, no egress, internet, or a tunnel.
- **Tartarus's guard** (`cape/guest_engine/firewall.py`) is an nftables table named `tartarus_guest`
  at a priority before iptables' chains. The rooter cannot reorder or remove it. It has three parts:
  an `inet` input rule (a guest reaches the gateway address and nothing else the container owns), an
  `inet` forward rule (a guest is never routed back onto the bridge, nor to a reserved private range
  or to a network the container is on), and a `bridge` rule (a port must use its own MAC, and an
  address owned by a running guest may only come from that guest's port). The module docstring
  explains each rule.

The rules are applied by `cape/bin/guest-firewall`. libvirt runs it for each QEMU domain event
through the hook `cape/libvirt/qemu-hook`, which passes the domain XML on stdin. The unit tests are
`cape/tests/test_guest_firewall.py` and `cape/tests/test_isolation.py`. Only `make verify-isolation`
proves the rules on a real guest, and it needs the real stack; see [running the tests](running-the-tests.md).

## Security stance

Tartarus is a local tool for one analyst. It has no accounts, binds to `127.0.0.1` and has no
authentication in v1. Three points shape most changes:

- The `cape` container is privileged, so the control service is root-equivalent there. The backend
  is the only client, and it has neither the libvirt socket nor the Docker socket.
- The backend parses data that malware produces. Samples are stored zipped at rest.
- OpenSearch is unauthenticated, so only the backend may reach it.

The threat model, the review findings and the accepted risks are in [security](../security.md).
