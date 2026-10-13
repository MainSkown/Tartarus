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
| `POST /analyses` | multipart (max 512 MB, enforced by the frontend's nginx; proposed): `file`, `options` (JSON: `route`, `timeout` 60–1200 s, `package` (`auto` default), `memory_dump` bool, `interactive` bool, `tags[]`). Returns `201 {analysis}`. Rejected with `409` if the guest isn't ready or the disk is below the block threshold. |
| `GET /analyses` | Paged list with `q` (filename/hash substring), `status`, `tag`, and `sort` (`submitted_at` desc default) |
| `GET /analyses/{id}` | Detail: sample, status, phase, options, score, max severity, families, counts per lane and per severity, tags, timing |
| `POST /analyses/{id}/stop` | Stop a running task early; it proceeds to processing |
| `POST /analyses/{id}/extend` | `{seconds}`. Only while running and interactive (see the open question in cape-integration) |
| `POST /analyses/{id}/cancel` | Remove a queued analysis |
| `POST /analyses/{id}/reingest` | Re-run ingestion from CAPE storage (job) |
| `DELETE /analyses/{id}` | `409` if running. Otherwise starts a delete job |

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
| `GET /analyses/{id}/processes` | Tree: nodes `{pid, ppid, name, executable, command_line, start, end, integrity, max_severity, detection_count, injected_into[], network_hosts[], event_counts_by_lane}` |
| `GET /analyses/{id}/processes/{pid}` | One process plus its loaded modules, handles summary and top APIs |
| `GET /analyses/{id}/network` | `{dns[], http[], tls[], flows[], alerts[], hosts[]}` with process attribution |
| `GET /analyses/{id}/artifacts` | `{dropped[], payloads[], procdumps[], memory_dump?, pcap, screenshots[], configs[]}`. Each artefact has id, name, size, hashes, type, YARA hits and source process. |
| `GET /analyses/{id}/artifacts/{artifact_id}/download` | Password-protected zip (`infected`). `GET …/screenshots/{n}` returns a raw PNG. |
| `GET /analyses/{id}/registry` | Registry changes grouped by key |
| `GET /analyses/{id}/detections` | All detections grouped by ruleset, sorted by severity |
| `GET /analyses/{id}/attack` | ATT&CK matrix: tactics → techniques with hit count and detection ids |
| `GET /analyses/{id}/iocs` | Deduplicated IOCs: hashes, domains, IPs, URLs, mutexes, registry keys and file paths, each with context and source events |

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
A Guacamole protocol tunnel (text frames, Guacamole instruction format) between
`guacamole-common-js` and `guacd`. The server rejects it with code `4409` if the task isn't
running or isn't interactive.

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
