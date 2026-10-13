# Backend

The backend is Python 3.12 and FastAPI, running as one Uvicorn worker. It owns the REST API, the
WebSocket feeds, the live collector, the report ingester, Sigma, the query compiler, exports
and the guest builder. The frontend talks **only** to this service.

## Module layout (`backend/app/`)

| Module | Responsibility |
|---|---|
| `main.py` | App factory, lifespan (start collector, queue runner, job runner, rule loader). No static files: the frontend container serves the PWA |
| `config.py` | Settings from env (pydantic-settings) |
| `api/` | Routers: `analyses`, `events`, `processes`, `network`, `artifacts`, `detections`, `annotations`, `rules`, `export`, `guest`, `system`, `internal` |
| `ws/` | WebSocket endpoints: `live`, `desktop`, `system` |
| `cape/` | apiv2 client, task options mapping, storage path helpers |
| `collector/` | Directory watcher, per-file offset tailer, CAPE BSON parser (ported from CAPE `lib/cuckoo/common/netlog.py`), ETW JSON tailer |
| `normalize/` | Source → ECS mappers (`capemon.py`, `sysmon.py`, `etw.py`, `suricata.py`, `volatility.py`, `cape_report.py`), derived-event rules, `tartarus.summary` builders |
| `rules/` | Sigma loader (pySigma + ECS pipeline), compiled in-memory matcher, detection emitter |
| `ingest/` | Report ingester (report.json → enrichment events + analysis summary), catch-up pass |
| `search/` | OpenSearch client, index template, bulk indexer, query helpers (search, facets, histogram) |
| `query/` | KQL-like grammar (lark), AST → OpenSearch DSL compiler, field catalog and aliases |
| `export/` | STIX 2.1, MISP JSON, CSV, HTML/PDF report (Jinja2 + WeasyPrint) |
| `guest/` | Guest build pipeline steps and health checks (M6). Will use `libvirt-python` over `qemu+tcp://cape/system`, which is switched off until then; no Docker socket |
| `jobs/` | Persistent job runner, queue runner |
| `pubsub.py` | In-process broadcast: topics `analysis:{id}` and `system` |
| `db/` | SQLAlchemy models, session, Alembic |

## REST API

Base path `/api`. JSON is served everywhere except uploads and downloads. Errors use the shape
`{"error": {"code": "string", "message": "string", "details": {}}}` with the right HTTP status.
- `code` is the lowercased HTTP phrase (`not_found`, `method_not_allowed`, `conflict`, …),
  except `validation_error` (422) and `internal_error` (500, generic message, never internals).
- For 422, `details` is `{"fields": [{"location": ["body", "timeout"], "message": "...",
  "type": "..."}]}`, so the GUI can attach each message to its field.
- `ErrorEnvelope` is the `default` response of every operation, so the generated client has its
  type.

All request and response bodies are Pydantic models. Operation ids are generated as
`<tag>_<route name>` (e.g. `system_health`), so the generated client has clean function names
(see [API client](#api-client)). Every route must have a tag; an untagged route fails at
startup. Tests that inspect routes read `app.openapi()["paths"]`, because FastAPI ≥ 0.143 no
longer lists included routes in `app.routes`.

### System
| Method & path | Purpose |
|---|---|
| `GET /system/health` | `{cape, guest, opensearch, postgres}`, each `ok` / `degraded` / `down` with a message |
| `GET /system/disk` | Total and free bytes, Tartarus usage (indices, artefacts, guest images), thresholds |
| `GET /system/queue` | Running analysis and queued analyses |
| `GET /settings`, `PUT /settings` | Defaults: route, timeout, interactive, disk thresholds |

### Analyses
| Method & path | Purpose |
|---|---|
| `POST /analyses` | **Built (M1a).** multipart: `file` and `options` (a JSON string: `route`, `timeout` 60 to 1200 s default 180, `package` default `auto`, `interactive` default `false`; unknown keys are rejected; `memory_dump` and tags are not in M1a). `interactive` is stored in `analysis.options` and makes the backend submit the CAPE task with `interactive=1,nohuman=yes`; the run then lasts the whole timeout (see the desktop tunnel below). `201` with the analysis, always `queued`. Checked in this order: the form (`422` with field locations, including an empty file at `["body","file"]`), then the guest is ready (`409`, nothing stored), then the upload (`413` past 512 MiB). Two identical uploads at once are fine; a failed submission leaves no file or row. |
| `GET /analyses` | **Built.** `{items, total}`, newest first; `limit`, `offset`, `q` (filename or hash substring) and `status`; each item carries `queue_position`, computed for the page in one query. (`tag` and `sort` come with M5 and later.) |
| `GET /analyses/{id}` | **Built.** The analysis with its typed `summary` (duration, process count, signatures with severity, ATT&CK ids with the signatures that raised them, network counts, files and registry keys written, the sample's name and type) once the report is read; `queue_position` (1 is served next, `null` unless `queued`; also on every item of the list and on the `POST` response); `404` in the error envelope when unknown. `summary.lane_counts` maps each lane to its number of indexed events once the analysis is `done`. The process tree comes with M1b. |
| `POST /analyses/{id}/stop` | Stop a running task early; it proceeds to processing |
| `POST /analyses/{id}/extend` | `{seconds}`. Only while running and interactive (see the open question in cape-integration) |
| `POST /analyses/{id}/cancel` | **Built.** Only while `queued`: `200` with the cancelled analysis; `409` once it has started or ended; `404` when unknown. |
| `POST /analyses/{id}/reingest` | **Built (M1b).** Only for a `done` or `report_failed` analysis: clears `error` and `finished_at`, moves it to `ingesting`, wakes the runner and returns `200` with the analysis. The runner then reads CAPE's `reported` status and indexes the report again, replacing the index. `409` (error envelope) when the analysis is in any other state, or while another analysis is active, because the runner follows one at a time; `404` when unknown. If CAPE no longer knows the task the analysis ends `report_failed` ("CAPE no longer knows task N"). |
| `DELETE /analyses/{id}` | **Built.** `409` while active (starting, running, processing, ingesting). Otherwise deletes the CAPE task (asking CAPE for its status first, because CAPE deletes only reported tasks unless given the task's own status), then our rows, then the stored sample only if no other analysis uses it; `204`. Then drops the analysis's event index (after the CAPE task, before the rows). A missing CAPE task or index counts as already gone, and an unreachable CAPE or OpenSearch does not make the analysis undeletable (logged, and the leftover is skipped). |

#### Ingest (M1b)

When CAPE reports a task, the runner reads the summary from `report.json`, then the ingester
indexes the report's events (the `capemon`, `cape-network` and `cape-signatures` normalisers)
into `tartarus-events-<analysis id>`:

- The index template is put on every ingest (idempotent), so OpenSearch being down at boot breaks
  nothing. Any existing index of the analysis is dropped first, so ingesting twice gives the same
  index.
- `event.sequence` is renumbered while the three sources are streamed into one ordinal, unique
  across sources; events are counted per `tartarus.lane`.
- Events are bulk-indexed in chunks, then `refresh_interval` is set to `30s` and the index is
  refreshed.
- On success the analysis is `done` with `event_count` and `summary.lane_counts`. On any indexing
  failure (unreadable report, OpenSearch down, events rejected) the half-built index is dropped
  and the analysis ends `report_failed` with the reason in `error` and `event_count` 0, never
  `done` with a missing or partial index. `POST /analyses/{id}/reingest` retries it.

### Events and query
| Method & path | Purpose |
|---|---|
| `POST /analyses/{id}/events/search` | Body: `{query, filters[], time_range?, lanes?, pids?, sort: "@timestamp"\|"-@timestamp", size ≤ 500, search_after?}`. Returns `{events[], total, next_cursor}`. Uses `search_after` paging so it works with millions of events. |
| `POST /analyses/{id}/events/facets` | Same filter body plus `fields[]` (default: `process.name`, `tartarus.lane`, `event.action`, `api.name`, `destination.domain`, `rule.name`). Returns the top 10 values per field with counts. |
| `POST /analyses/{id}/events/histogram` | Same filter body plus `{interval: auto\|ms}`. Returns buckets per lane (`date_histogram` × `terms(tartarus.lane)`) and detection markers, for the timeline. |
| `GET /analyses/{id}/events/{event_id}` | Full event including `tartarus.raw`, annotations and related events |
| `POST /query/validate` | `{query}` → `{ok, errors: [{start, end, message}], ast?}` |
| `GET /query/fields` | Field catalog for autocomplete: name, type, aliases, description, example |
| `GET /analyses/{id}/query/values?field=&prefix=` | Top values for value autocomplete (terms aggregation with `include` regex) |

`filters[]` items look like `{field, op: "is"|"is_not"|"exists"|"range", value}`. These are the
quick-filter chips. The backend ANDs them with the compiled `query`.

### Analysis views
| Method & path | Purpose |
|---|---|
| `GET /analyses/{id}/processes` | `{roots[], total}`: the tree as nested nodes `{entity_id, pid, ppid, name, executable, command_line, start, end, integrity, max_severity, detection_count, injected_into[], network_hosts[], event_counts_by_lane, children[]}`. Built from the indexed events by aggregation (at most 1000 processes). A process whose parent pid is not in the set is a root; a reused pid parents only the processes started after it. `end` is the `process-terminated` event; `injected_into` the `tartarus.inject.target_pid` of `inject-*` events; `network_hosts` the distinct DNS names, domains and IPs of network events attributed to the process. CAPE signatures carry no process, so `detection_count` and `max_severity` come from the processes owning the calls an alert references in `related.events` (an alert counts once per process; one with no resolvable call counts for none). `integrity` is always null: no source sets `process.integrity_level` yet. |
| `GET /analyses/{id}/processes/{pid}` | The node fields (no `children`) plus `modules[]` (`{name, path, base_address, loaded_at}`: distinct libraries from `LdrLoadDll` and the loader's `DllLoadNotification` loads, one per base address), `top_apis[]` (`{name, count}`, 15 most called), `events[]` (`{time, action, summary, lane, event_id}`: the 200 most recent process, file, registry and network events, newest first) and `event_total`. `404` for a pid the analysis never saw (the first process, if the pid was reused). No handles summary: capemon handle data is not indexed. |
| `GET /analyses/{id}/network` | `{dns, http, tls, flows, alerts, hosts, simulated}`, each list `{items[], total}`. `?limit=` (1 to 2000, default 500) cuts every list to its first rows by time; `total` counts them all; there is no offset (deeper browsing is the Events tab). Rows carry `process: {pid, name}\|null`, set only where the normaliser attributed the record exactly. A capemon-derived row the pcap also holds (same DNS name, ip:port or URL) is dropped, so a lookup is one row; one only capemon saw (nothing on the wire) stays. `dns`: `{query, type, answers[]}`; `http`: `{method, url, host, status, user_agent}`; `flows`: `{transport, source_ip, source_port, destination_ip, destination_port}`; `hosts`: `{host, kind: ip\|domain, count, related[]}` (an address counts its connections and lists the names that resolve to it; a name counts its lookups and requests and lists its addresses), most contacted first. `tls` and `alerts` are empty until Suricata is a source. `simulated` is true when `options.route` is `inetsim`. Built from at most the first 10 000 network events. |
| `GET /analyses/{id}/artifacts` | `{dropped[], payloads[], procdumps[], memory_dump, pcap, screenshots[], configs[]}`, computed on demand from `<cape storage>/analyses/<task>/reports/report.json` and the analysis folder (nothing is indexed); a missing or unreadable report gives empty lists and nulls. An artifact is `{id, name, size, sha256, md5, type, cape_type, yara[], source_process: {pid, name}\|null, guest_path, downloadable}`: `dropped` from `dropped[]`, `payloads` from `CAPE.payloads`, `procdumps` from `procdump[]` and `procmemory[]` (named after their process), `memory_dump` is `memory.dmp` and `pcap` is `dump.pcap` of the folder (hash from `network.pcap_sha256`; both null without the file). `id` is an opaque 20-hex token of kind + sha256 (+ occurrence number for a repeated hash), never a path. `downloadable` is false when the file is not in the folder; the file is always found at `files/`, `CAPE/` or `procdump/` + the sha256 (the report's own `path` is ignored, the hash must be 64 lowercase hex) and must resolve inside the analysis folder, so a link out of it is not served. `screenshots[]` is `{n, name, size}` for the images in `shots/` (`_small` thumbnails left out), `n` counted from 1. `configs[]` is `{id, family, data}` per family of `CAPE.configs`; configs are data, not files, and have no download. |
| `GET /analyses/{id}/artifacts/{artifact_id}/download` | The artifact as an AES zip, password `infected`, one file named after the artifact (reduced to a plain file name), through the sample store's zip writer, built in a temporary file that is deleted after the response. An id not in the computed list, or whose file is gone, is `404`: the id is only looked up, never joined into a path. |
| `GET /analyses/{id}/artifacts/screenshots/{n}` | The raw image (`image/png` or `image/jpeg` by extension); `404` outside `1..len`. |
| `GET /analyses/{id}/pcap` | The raw capture, `application/vnd.tcpdump.pcap`, `404` without `dump.pcap`. The pcap also downloads as a zip through the artifact route. |
| `GET /analyses/{id}/registry` | `{keys[], total}`: changes grouped by hive and key (case-insensitive), groups ordered by first change, each `{key, hive, changes[]}` with `changes` `{event_id, time, action, value_name, data_type, data[], process}` in time order. `total` counts the change events. Built from at most the first 10 000. |
| `GET /analyses/{id}/detections` | `{groups[], total}`: every `event.kind: alert` event (at most 1000; `total` counts them all) grouped by `rule.ruleset` in the order sigma, cape, yara, suricata, then others alphabetically. Each group is `{ruleset, detections[]}`, most severe first, then by name. A detection is `{id (event.id), name, description, severity, ruleset, techniques[], match, references[], time, process: {pid, name}\|null, related_events[], related_event_total}`. `related_events` resolves the first 50 `related.events` ids with one query, as `{id, time, lane, action, summary, process}` in the alert's order (ids not in the index are dropped); `related_event_total` counts all the ids. CAPE signatures carry no process, so `process` falls back to the first related event's. |
| `GET /analyses/{id}/attack` | `{tactics[], attack_version}`: `tactics` are `{id, name, techniques[]}` in kill-chain order (reconnaissance to impact, from the bundled table), only those with a hit, a technique under each of its tactics, as `{id, name\|null, hit_count, severity, detection_ids[]}` ordered by id (`hit_count` is the number of detections that raised it, `severity` the highest of them). Tactic names and technique names come from `backend/app/data/attack_techniques.json`, generated from MITRE's enterprise STIX bundle by `scripts/build-attack-table.py` (current and not revoked techniques and sub-techniques; the file records its ATT&CK version). An id missing from the table lands under the last tactic `unknown`, with no name. |
| `GET /analyses/{id}/iocs` | `{iocs[], truncated_types[]}`; an IOC is `{type, value, count, context, source_event_ids[] (at most 10), process}`, ordered by type (hash, domain, ip, url, mutex, registry, file), then count, then value. Events give `domain` (`dns.question.name`), `ip` (`destination.ip`, never the sandbox network `192.168.150.0/24`), `url` (`url.full`), `registry` (`registry.path` of the registry lane) and `file` (`file.path` of the file lane) through one terms aggregation per type (at most 500 values each; `truncated_types` names the types that had more); values that differ only in case are one IOC and show the first event's spelling, `count` is the number of events and `context` the first event's summary. The report gives `hash` (the submitted sample, always, from the database; dropped files and payloads from the artifact list; a hash seen twice is one IOC with count 2) and `mutex` (`behavior.summary.mutexes`); these have no source events. |

### Annotations
| Method & path | Purpose |
|---|---|
| `GET /tags` | All tags with usage counts |
| `GET /analyses/{id}/annotations` | Tags and notes for an analysis, a process or an event (`?target_type=&target_ref=`) |
| `POST /analyses/{id}/tags` | `{tag, target_type, target_ref}` (creates the tag if new) |
| `DELETE /analyses/{id}/tags/{link_id}` | |
| `POST /analyses/{id}/notes`, `PATCH /notes/{id}`, `DELETE /notes/{id}` | Plain-text notes |

### Rules
| Method & path | Purpose |
|---|---|
| `GET /rules` | Sigma rules with validity, enabled, level and the total hit count across analyses |
| `PATCH /rules/{id}` | `{enabled}` |
| `POST /rules/reload` | Re-scan `rules/sigma/` (also done automatically on file change) |
| `GET /analyses/{id}/rules/hits` | Hit counts per rule for one analysis |

### Export
| Method & path | Purpose |
|---|---|
| `GET /analyses/{id}/export/iocs?format=stix\|misp\|csv` | File download |
| `POST /analyses/{id}/export/report` | `{format: html\|pdf, include: {notes, screenshots, raw_iocs}}` → job. `GET /jobs/{id}/download` when done |

### Guest
| Method & path | Purpose |
|---|---|
| `GET /guest` | Current guest VM and its health checks |
| `GET /guest/isos` | ISOs found in `data/iso` with detected edition and version |
| `POST /guest/build` | Wizard inputs → job |
| `POST /guest/build/{job_id}/resume`, `POST /guest/build/{job_id}/restart` | |
| `POST /guest/check` | Run the health checks now |

### Jobs
`GET /jobs/{id}` returns the status. `GET /jobs/{id}/download` returns the job's result file
when it has one.

### Internal
`POST /internal/cape/callback` takes `{task_id}`. It is accepted only from the internal compose
network (checked by source subnet plus a shared token header), and it triggers ingestion.

## WebSockets

All messages are JSON: `{type, ts, data}`.

### `WS /ws/analyses/{id}/live`
Client → server:
- `{type: "subscribe", data: {query?, filters?}}` sets an optional server-side filter on the
  live stream. It can be re-sent at any time.
- `{type: "ping"}`

Server → client:

| type | data |
|---|---|
| `status` | `{status, phase, elapsed_s, remaining_s}`, sent on change and every 1 s while running |
| `events` | `{events: [ECS docs, trimmed: no tartarus.raw], dropped: n}`. Batched ≤ 250 ms. If the client falls behind, the server keeps the newest events and reports how many it `dropped`; the GUI shows "N events skipped, open table". |
| `detection` | A single detection document, sent immediately |
| `process` | Process-tree delta `{op: "add"\|"update"\|"end", node}` |
| `counts` | `{by_lane, by_severity, total}` every 2 s |
| `phase` | `{phase: "final"}` when ingestion completes, so the GUI reloads its views |
| `error` | `{code, message}` |

When the client connects, the server sends the current `status` and the process tree, then
streams new events. The GUI backfills the latest events through REST, so the live feed never
replays history.

### `WS /ws/analyses/{id}/desktop`
A Guacamole protocol tunnel (text frames, one instruction each) between `guacamole-common-js`
and `guacd` (`GUACD_HOST`, default `cape`, and `GUACD_PORT`, default `4822`). The socket is
accepted with the `guacamole` subprotocol, then closed with a code when refused: `4404` for an
unknown analysis, `4409` unless the analysis is `starting` or `running` and was submitted
`interactive`, and `4408` ("desktop not available yet") when CAPE has not recorded the guest's VNC
port in the task's `options` within 90 s (polled every second through `tasks/view`). The first
frame is the tunnel's internal instruction (`0.,36.<uuid>;`) and internal `ping`s are echoed.
`guacd` is always told to connect to `127.0.0.1` at the recorded port, with clipboard off in both
directions; of the browser's instructions only `mouse`, `key`, `size`, `sync`, `ack`, `blob`,
`end` and `nop` reach `guacd`. An `error` from `guacd` (it follows `ready` when the guest is off)
is forwarded and then the tunnel closes, as it does when `guacd` hangs up or the analysis leaves
`starting`/`running` (checked every 2 s). There is no authentication: one local analyst, bound to
127.0.0.1.

### `WS /ws/system`
Pushes `health`, `queue`, `disk` and `job` (progress and step for guest builds and exports).

## Live collector

- Starts when the analysis status becomes `running` and watches `analyses/<task>/logs/` and
  `analyses/<task>/aux/`.
- Keeps a per-file `(path, offset, record_index)` saved in memory and checkpointed in the `job`
  row every 5 s, so it can resume after a restart.
- Reads only complete BSON records. A partial trailing record waits for more bytes.
- capemon logs start with process and API-description messages. The parser keeps that state
  per file so it can map call indices to API names and argument names.
- The pipeline per record is: normalise → derive semantic events → Sigma match → enqueue to the
  bulk indexer and pub/sub.
- When the task leaves `running`, the collector does a final drain and stops.

## Sigma engine

- Rules are loaded from `rules/sigma/**/*.yml` at start and on change (watchfiles). Rules that
  fail to parse are kept with `valid = false` and their error is shown on the Rules page.
- Only rules with `logsource.product: windows` (or no product) and a category supported by the
  mapping (see [data-model](data-model.md#sigma-field-mapping)) are compiled. Others are
  marked "unsupported logsource" and stay inactive.
- Compilation uses pySigma to parse the rule and apply the ECS Windows pipeline, then builds a
  Python predicate tree. It supports the modifiers `contains`, `startswith`, `endswith`, `all`,
  `re`, `cidr`, `base64`/`base64offset`, `windash`, `exists`, `gt/gte/lt/lte`, and the
  `1 of`/`all of` selection conditions.
- Rules are indexed by logsource category, so each event is only tested against rules for its
  category.
- Correlation and aggregation rules (`count() > n`, Sigma correlation rules) are **not
  supported in v1**. They are listed as unsupported.
- **Default ruleset (proposed, still an open question):** ship a curated subset of SigmaHQ `rules/windows/` (process_creation,
  file_event, registry_*, network_connection, dns_query, image_load, create_remote_thread,
  process_access) with status `stable` or `test`. The user can add their own rules to
  `rules/sigma/custom/`.
- A detection is emitted once per (rule, process) per 60 s window, to suppress floods. The
  suppressed count goes into `api.repeated`-style metadata.

## Query language (KQL-like)

The grammar is written with lark and compiled to OpenSearch bool, term, wildcard, range and
exists queries.

```
query      := or_expr
or_expr    := and_expr ("OR" and_expr)*
and_expr   := not_expr (("AND")? not_expr)*        # adjacent terms are ANDed
not_expr   := "NOT" not_expr | primary
primary    := "(" query ")" | comparison | free_text
comparison := FIELD ":" value_group
            | FIELD (">" | ">=" | "<" | "<=") VALUE
            | FIELD ":" "*"                        # field exists
value_group:= VALUE | "(" VALUE ("OR" VALUE)* ")"
VALUE      := QUOTED_STRING | BARE_WORD            # * and ? wildcards allowed in both
free_text  := VALUE                                # searches summary, command_line, paths, url, api args
```

Examples:
- `process.name:cmd.exe AND lane:network`
- `api:(NtWriteVirtualMemory OR NtCreateThreadEx) NOT process.name:"explorer.exe"`
- `file.path:*\\AppData\\Roaming\\*.exe`
- `destination.port >= 1024 AND dns.question.name:*.onion`
- `rule.ruleset:sigma AND event.severity >= 3`
- `powershell -enc` (free text)

Rules:
- Keywords (`AND`, `OR`, `NOT`) are case-insensitive. Field names are validated against the
  catalog, and an unknown field gives an error with a "did you mean" suggestion.
- **Aliases:** `pid` → `process.pid`, `ppid` → `process.parent.pid`, `proc` → `process.name`,
  `cmd` → `process.command_line`, `api` → `api.name`, `path` → `file.path`,
  `reg` → `registry.path`, `ip` → `destination.ip`, `port` → `destination.port`,
  `domain` → `dns.question.name` OR `destination.domain`, `url` → `url.full`,
  `lane` → `tartarus.lane`, `action` → `event.action`, `rule` → `rule.name`,
  `sev` → `event.severity`, `technique` → `threat.technique.id`.
- Values on keyword fields are case-insensitive (lowercase normalizer). On numeric fields,
  ranges are allowed. Paths keep backslashes, and `\\` in quoted strings means a literal
  backslash.
- Errors return `{start, end, message}` so the GUI can underline the exact span.

## Exports

| Format | Content |
|---|---|
| **STIX 2.1** bundle | `identity` (Tartarus), `malware` (families, if detected, else "unknown"), `file` SCOs + `indicator`s for sample, dropped and payload hashes, `domain-name` / `ipv4-addr` / `url` indicators, `attack-pattern`s for ATT&CK techniques, `relationship`s (indicator `indicates` malware, malware `uses` attack-pattern), `note`s from the analyst's notes |
| **MISP** event JSON | Event info `Tartarus analysis #id – filename`, attributes (sha256, md5, domain, ip-dst, url, filename, regkey, mutex) with `to_ids` set for network IOCs and hashes, tags (`tlp:amber` default, analyst tags, ATT&CK galaxy tags) |
| **CSV** | `type,value,context,first_seen,source_process` |
| **HTML report** | Self-contained single file in the Tartarus theme: summary, score, families, ATT&CK, process tree (static SVG), key events, network, IOCs, detections, screenshots, the analyst's tags and notes |
| **PDF report** | Same content from the same template, rendered by WeasyPrint in a print variant: white background, ice-blue accents and the same severity colours |

## Configuration (`.env`)

`TARTARUS_PORT=8080` (the frontend's published port; the backend listens on `8000` internally), `TZ`, `OPENSEARCH_HEAP=1536m`, `GUEST_VCPUS=2`, `GUEST_RAM_MB=4096`,
`GUEST_SUBNET=192.168.150.0/24`, `CAPE_REF=<commit>`, `DEFAULT_ROUTE=inetsim`,
`DEFAULT_TIMEOUT=180`, `DISK_WARN_GB=50`, `DISK_BLOCK_GB=20`, optional `VPN_*` / `WG_*` /
`SOCKS5_*`. Secrets such as the CAPE API token and the callback token are generated on first
start into `data/secrets.env`.

## API client

- FastAPI generates the schema and serves it at `/openapi.json`; there is no exported or committed
  copy. The frontend generates its client with **`@hey-api/openapi-ts`**, the same setup as
  Momos: `"api:sync": "openapi-ts -i http://localhost:8000/openapi.json -o ./src/api"`.
- `npm run api:sync` (or `make api-sync`) needs the dev stack running (`make dev` publishes the
  backend on `127.0.0.1:8000`). The generated client in `frontend/src/api/` is committed, so
  builds and CI never need a running backend, and it is only ever changed by re-running the sync.
- The generator owns `src/api/` and may clean it on every run, so hand-written code never lives
  there.
- Every route sets `operation_id` (e.g. `analyses_create`, `events_search`) so the generated
  function names stay stable.
- WebSocket message types are defined as Pydantic models too. They're exported via a dummy
  schema route so the generated client also has `LiveMessage` and similar types.

## Testing

- Unit tests:
  - Normalisers, using recorded BSON, EVTX and report fixtures (from a handful of real CAPE runs
    of benign test binaries).
  - The query compiler, using a golden AST → DSL table.
  - The Sigma matcher, using SigmaHQ rule test cases with synthetic events.
  - Exports, validated with the `stix2` validator and a MISP JSON schema.
- Integration tests: an OpenSearch and Postgres testcontainer. The collector is replayed
  against a fixture analysis directory that is written incrementally to simulate a live run.
- End-to-end: the guest self-test sample (see cape-integration) runs in the dev environment.
