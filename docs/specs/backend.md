# Backend

The backend is Python 3.12 and FastAPI, running as one Uvicorn worker. It owns the REST API, the
WebSocket feeds, the live collector, the report ingester, Sigma, the query compiler, exports
and the client of the guest control service (the guests themselves are built and kept by that service, in the
`cape` container). The frontend talks **only** to this service.

## Module layout (`backend/app/`)

| Module | Responsibility |
|---|---|
| `main.py` | App factory, lifespan (start collector, queue runner, job runner, rule loader). No static files: the frontend container serves the PWA |
| `config.py` | Settings from env (pydantic-settings) |
| `api/` | Routers: `analyses`, `events`, `processes`, `network`, `artifacts`, `detections`, `annotations`, `rules`, `export`, `guests`, `jobs`, `system`, `internal` |
| `ws/` | WebSocket endpoints: `live`, `desktop` (an analysis's and a guest build's), `system` |
| `cape/` | apiv2 client, task options mapping, storage path helpers |
| `collector/` | Directory watcher, per-file offset tailer, CAPE BSON parser (ported from CAPE `lib/cuckoo/common/netlog.py`), ETW JSON tailer |
| `normalize/` | Source → ECS mappers (`capemon.py`, `sysmon.py`, `etw.py`, `suricata.py`, `volatility.py`, `cape_report.py`), derived-event rules, `tartarus.summary` builders |
| `rules/` | Sigma loader (pySigma + ECS pipeline), compiled in-memory matcher, detection emitter |
| `ingest/` | Report ingester (report.json → enrichment events + analysis summary), catch-up pass |
| `search/` | OpenSearch client, index template, bulk indexer, query helpers (search, facets, histogram) |
| `query/` | KQL-like grammar (lark), AST → OpenSearch DSL compiler, field catalog and aliases |
| `export/` | STIX 2.1, MISP JSON, CSV, HTML/PDF report (Jinja2 + WeasyPrint) |
| `guest/` | The client of the guest control service and what is built on it (M6): `client.py` (`GuestControl`, an HTTP client with the bearer token and its errors), `schemas.py` (the control service's JSON), `health.py` (the aggregate guest check), `build_job.py` (the `guest_build` job and its reattach), `selftest_runner.py`, `selftest_verdict.py` and `selftest_evidence.py` (the self-test). No `libvirt-python`, no Docker socket: libvirt's TCP endpoint stays off and the only way to the guests is the control service |
| `analyses/` | `guest_choice.py` (which guest an analysis runs on, the package check; pure) and `submission.py` (`AnalysisSubmitter`, the one path `POST /analyses` and the self-test queue an analysis through) |
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
| `GET /system/health` | `{cape, guest, opensearch, postgres}`, each `ok` / `degraded` / `down` with a message. `guest` is the aggregate of every guest's state from the control service alone (CAPE is not asked, so a guest CAPE has locked for a run is not unhealthy): `ok` when every guest is `ready`; `degraded` when some are not (the message lists them, for example "lab4 is building" or "lab6 is failed"); `down` when there is no guest, none is ready, or the control service cannot be reached |
| `GET /system/disk` | Total and free bytes, Tartarus usage (indices, artefacts, guest images), thresholds |
| `GET /system/queue` | **Built (M9).** `{running[], queued_count, queued[]}`: each running analysis with `id`, `filename`, `guest`, `status`, `started_at`, `elapsed_s` (oldest first), each queued one with `id`, `filename`, `guest` and its `position` on that guest's line. The same snapshot `/ws/system` pushes as `queue` |
| `GET /settings`, `PUT /settings` | Defaults: route, timeout, interactive, disk thresholds, and `default_guest`: the guest an analysis runs on when its options name none (a guest name or `null`; a guest that is not ready or no longer exists counts as `null`, meaning the first ready guest by name) |

### Analyses
| Method & path | Purpose |
|---|---|
| `POST /analyses` | **Built (M1a, `guest` from M6).** multipart: `file` and `options` (a JSON string: `route`, `timeout` 60 to 1200 s default 180, `package` default `auto`, `interactive` default `false`, `memory_dump` default `false`, `keep_memory_dump` default `false`, `guest`; unknown keys are rejected; tags are not in M1a). `memory_dump` asks CAPE for a dump of the guest's RAM (the form field `memory=1`, stored in `analysis.options`, no migration) and has the runner read it with Volatility3 (see the memory step under Ingest); `keep_memory_dump` keeps the dump after its findings are read and is `422` at `["body","options","keep_memory_dump"]` without `memory_dump`. `guest` is the name of the guest to run on; omitted, it is Settings' `default_guest` while that guest is ready, else the first ready guest by name. The guest chosen is written into `analysis.options.guest` (no migration; an analysis from before guests has none), and the runner submits the CAPE task with `machine=<guest>` (the backend always sends it: CAPE alternates between machines when it is left out). `package` is checked against the chosen guest's profile: `auto` or one of its `packages`. `interactive` is stored in `analysis.options` and makes the backend submit the CAPE task with the options string and task fields of the guest's profile (`agent.interactive`; Windows: `interactive=1,nohuman=yes`); the run then lasts the whole timeout (see the desktop tunnel below). `201` with the analysis, always `queued`, and `warnings[]` (strings for the analyst; empty unless a memory dump was accepted with little disk left); the analysis carries `guest` (the stored name, shown even after the guest is deleted) and `guest_badges` (the badges the guest's profile derives from its options, such as `DEFENDER ON`; empty when the guest is gone or the control service cannot be asked). Checked in this order: the form (`422` with field locations), then the guest and the package, then the upload (`422` for an empty file at `["body","file"]`, `413` past 512 MiB). The guest check answers `409` with the reason, and stores nothing, when no guest has been built, the named guest does not exist ("There is no guest named x") or is not `ready` ("x is failed: it cannot run an analysis"), no guest is ready, or any guest is being built or tested ("A guest is being built: wait for it to finish"), because registering a guest restarts `cape` and would kill the run; a memory dump is refused with `409` when the CAPE storage has less free space than `max(50,000 MB (CAPE's own `freespace` floor, below which it silently takes no dump), disk_block_gb + the guest's RAM)`, naming both numbers ("A memory dump needs 48.8 GB free and 18.2 GB is available", in GB of 1024 MB), also when the storage's free space or the guest's RAM cannot be read, and stores nothing; with more than that but less than `disk_warn_gb + the guest's RAM` free it is accepted and `warnings[]` says how little is left. The free space is `shutil.disk_usage` of `/cape-storage` (the read-only mount of the volume CAPE writes to), behind the `FreeSpaceProbe` port: nothing else in the backend reads it (`disk_block_gb` and `disk_warn_gb` were stored settings only); a package the guest does not accept is `422` at `["body","options","package"]` naming what it accepts; `502` when the control service cannot be asked. Two identical uploads at once are fine; a failed submission leaves no file or row. If the guest is deleted before the runner submits, the analysis fails with "Guest x no longer exists". |
| `POST /analyses/import`, `POST /analyses/import/memory-image` | **Built (M9).** multipart: `file`. Both paths run one handler; the second exists because nginx streams it unbuffered to 5 GiB, and takes a PCAP too. The first bytes are sniffed (`sniff_import`): PCAP and PCAPNG are kind `pcap`, an ELF core or Windows crash dump is `memory_image`, anything else `415`; a memory image on the first path is `415` naming the second. Past the limit of its kind (`import_pcap_max_bytes` 512 MiB, `import_memory_image_max_bytes` 5 GiB) `413`; an empty file is `422` at `["body","file"]`; nothing is kept on any failure. The upload is streamed in 1 MiB chunks, hashed on the way, into `<imports_dir>/.incoming-*` and moved to `<imports_dir>/<analysis id>/upload` (no extension; `Settings.imports_dir`, default `/imports`, the volume `cape` mounts read-only, so the file is mode 0644) once the analysis exists. `201` with the analysis: `kind` `imported`, `queued`, no guest, `options.import = {kind: "pcap" or "memory_image", filename, size}` (the sanitised name). The sample is registered in the sample table by its hashes and size only, through the same `queue_analysis` a submission uses, but **not copied into the sample store** (a 5 GiB image would be written twice and zipped for nothing): its `stored_path` is the imports directory and the bytes are found by analysis id. The runner is nudged as for a normal submission. Deleting the analysis removes `<imports_dir>/<analysis id>/`. |
| `GET /analyses` | **Built.** `{items, total}`, newest first; `limit`, `offset`, `q` (filename or hash substring) and `status`; each item carries `queue_position`, computed for the page in one query. (`tag` and `sort` come with M5 and later.) |
| `GET /analyses/{id}` | **Built.** The analysis with its typed `summary` (duration, process count, signatures with severity, ATT&CK ids with the signatures that raised them, network counts, files and registry keys written, the sample's name and type) once the report is read; `queue_position` (1 is served next on its guest's line, counting only the analyses waiting for that guest; imports queue apart; `null` unless `queued`; also on every item of the list and on the `POST` response); `404` in the error envelope when unknown. Once the analysis is `done`, `summary.lane_counts` maps each lane to its number of indexed events, `summary.missing_exports` lists each event-log channel the guest could not export with its `reason` (`[]` when none, see [cape-integration](cape-integration.md#event-logs-module)), `summary.warnings` says the same in plain words, one sentence per channel (`"Sysmon events were not exported: the guest did not answer within 120 s"`; `[]` when none), recomputed from the module's record by every ingest, never added to, and shown on the Summary and Events tabs, `summary.hidden_events` counts the Sysmon events left out as Windows background by reason (`cape-tooling`, `windows-background`, `monitor-artefact`, `sysmon-service`, `unmapped-event`; `{}` without a Sysmon file) and `summary.defender` says what Windows Defender did: `{status (clean, detected, removed, failed, no_export), sample_removed, blocked_before_run (the sample was removed and the run monitored no process), threats[]}`, a threat being a detection of the sample or of a file it dropped, one per file: detections with the same threat, path and scope (Defender can re-detect a file under a new Detection ID) are collapsed, failed over removed over pending (`{detection_id, threat_id, name, severity, category_id, scope (sample, dropped), path, process, user, detected_at, action, outcome (removed, failed, pending), removed_at}`; CAPE's own tooling is never listed). `no_export` means the guest left no export; `null` means the ingest ran without a Defender source, as does a summary stored before M8, which also has `hidden_events` `{}`. Both come from the same normaliser run as the events, and every ingest builds its own normalisers, so ingests of different analyses can run side by side. The process tree comes with M1b. |
| `POST /analyses/{id}/finish` | **Built.** Ends a `running` analysis early (an interactive run otherwise lasts its whole timeout). Asks the guest control service (`POST /tasks/{id}/finish` with the analysis's guest name in the body) to have that guest's agent create the folder CAPE's analyzer watches for; the service looks up the guest's address, agent port and finish folder in its own record, and the backend never supplies one; the analyzer notices within about a second and the runner then tracks the task on to `processing` as usual. `200` with the analysis, whose `status` is still `running`; finishing again is harmless. `404` when unknown; `409` (error envelope, readable message) unless the analysis is `running`: a `queued` one should be cancelled, a `starting` one cannot be finished yet, anything later is already over; `409` too for a running analysis with no CAPE task or one that records no guest; `502` when the control service or the guest agent cannot be reached or refuses. `409` also while the analyzer's monitor has not started in the guest (no `logs/*.bson` yet): CAPE says `running` about 14 s before that (S1 measured the window closing 16.0 to 17.5 s after `started_at`), and ending the run in the gap leaves the guest agent dead for minutes. |
| `POST /analyses/{id}/extend` | **Built (M7).** `{seconds}`, 1 to 600 (`422` otherwise). Moves an interactive run's `deadline_at` later by `seconds`, never past `started_at` + 1200 s, and answers the analysis with its new `deadline_at`. `409` (with the reason) unless the analysis is an interactive run that is `running` with its deadline set, or its deadline is already at the 20-minute limit; `404` when unknown. See the [M7 plan](../plans/m7-foundations.md), decision 5 |
| `POST /analyses/{id}/cancel` | **Built.** Only while `queued`: `200` with the cancelled analysis; `409` once it has started or ended; `404` when unknown. |
| `POST /analyses/{id}/reingest` | **Built (M1b).** Only for a `done` or `report_failed` analysis: clears `error` and `finished_at`, moves it to `ingesting`, wakes the runner and returns `200` with the analysis. The runner then reads CAPE's `reported` status and indexes the report again, replacing the index. `409` (error envelope) when the analysis is in any other state, or while any analysis (a run or an import) is starting, running, processing or ingesting: one conditional `UPDATE` checks that none is, so the re-ingest never overlaps another ingest; `404` when unknown. If CAPE no longer knows the task the analysis ends `report_failed` ("CAPE no longer knows task N"). |
| `DELETE /analyses/{id}` | **Built.** `409` while active (starting, running, processing, ingesting). Otherwise deletes the CAPE task (asking CAPE for its status first, because CAPE deletes only reported tasks unless given the task's own status), then our rows, then the stored sample only if no other analysis uses it; `204`. Then drops the analysis's event index (after the CAPE task, before the rows). A missing CAPE task or index counts as already gone, and an unreachable CAPE or OpenSearch does not make the analysis undeletable (logged, and the leftover is skipped). |

#### Queue and runner (M9)

The runner follows every active analysis in its own task, so one analysis' ingest or memory step never
delays another's deadline. It claims the oldest queued run whose guest has no active analysis: each guest
runs one analysis at a time, several guests run together, and a queued run behind a busy guest does not hold
up an idle guest's. An import (`kind` `imported`, no guest) queues and runs apart from runs. When no guest is
named and Settings' default is busy, the idle ready guest is chosen instead. The room check for a memory dump
counts the RAM of the dumps that queued and active analyses will still write.

#### Ingest (M1b)

When CAPE reports a task, the runner reads the summary from `report.json`, runs the memory step if the analysis asked for a dump, then the ingester
indexes the report's events (the `capemon`, `cape-network` and `cape-signatures` normalisers)
into `tartarus-events-<analysis id>`:

- The index template is put on every ingest (idempotent), so OpenSearch being down at boot breaks
  nothing. Any existing index of the analysis is dropped first, so ingesting twice gives the same
  index.
- `event.sequence` is renumbered while the three sources are streamed into one ordinal, unique
  across sources; events are counted per `tartarus.lane`.
- With Sigma rules active, the ingester then runs the engine over the complete event set in
  `@timestamp` order (ties in stream order, since the sources are not merged in time order) and
  indexes the alerts after the other events, numbered in the same sequence and counted in the
  same lane totals (`event_count` includes them). The rules are those active when the ingest
  starts. Only the events some rule category covers are held in memory for this; the rest is
  streamed. This result is authoritative: a re-ingest gives an old analysis its Sigma alerts.
- Events are bulk-indexed in chunks, then `refresh_interval` is set to `30s` and the index is
  refreshed.
- On success the analysis is `done` with `event_count`, `summary.lane_counts`, `summary.hidden_events` `summary.defender` and, for an analysis that asked for a dump, `summary.memory`. On any indexing
  failure (unreadable report, OpenSearch down, events rejected) the half-built index is dropped
  and the analysis ends `report_failed` with the reason in `error` and `event_count` 0, never
  `done` with a missing or partial index. `POST /analyses/{id}/reingest` retries it.

**The memory step** (`app/analyses/memory_step.py`) belongs to an analysis whose `options.memory_dump` is true and never fails it.
After the report is read and before the ingest, the runner calls the control service's `POST /memory/{cape_task_id}/analyse` (bearer
token, 300 s timeout): `200` Volatility3 ran and left `memory/run.json` in the analysis folder for the Volatility normaliser,
`404` CAPE took no dump (below its 50 GB floor), `409` already being analysed, `502` or `500` an error text. Once the ingest has
succeeded, and unless `keep_memory_dump` is set, it calls `DELETE /memory/{cape_task_id}/dump` (`204` and `404` both count as deleted;
the backend's mount is read-only, so only the service can delete it). A failed ingest leaves the dump for the re-ingest. A re-ingest does
not repeat the step: it keeps `summary.memory`, and retries only a delete that had failed. What happened is `summary.memory`:
`{dump_taken, findings (ok, unavailable, failed), error, dump_bytes, dump_deleted}`. `findings` is `unavailable` when there was no
dump, `failed` when the service could not run Volatility3 or every plugin failed, and `ok` otherwise (`error` then names any
plugin that failed); `dump_bytes` is the size of `memory.dmp`; `dump_deleted` is `true` or `false` after a delete, `null` when the
dump was kept or never taken. A summary stored before M8, or of an analysis without a dump, has `memory: null`. A kept dump is listed as
`memory_dump` by `GET /analyses/{id}/artifacts` and goes when the analysis is deleted.

### Events and query
| Method & path | Purpose |
|---|---|
| `POST /analyses/{id}/events/search` | **Built.** Body: `{query, filters[], time_range?, lanes?, pids?, sort: "@timestamp"\|"-@timestamp", size ≤ 500, search_after?, columns[]?}`. Returns `{events[], total, next_cursor}`; `columns` (at most 12 catalog fields or aliases) adds each event's `fields`. Uses `search_after` paging so it works with millions of events. |
| `POST /analyses/{id}/events/facets` | **Built.** Same filter body plus `fields[]` (default: `process.name`, `tartarus.lane`, `event.action`, `api.name`, `destination.domain`, `rule.name`). Returns the top 10 values per field with counts; a facet ignores the chips on its own field (see Events API). |
| `POST /analyses/{id}/events/histogram` | **Built.** Same filter body plus `{interval: auto\|ms}`. Returns buckets per lane (`date_histogram` × `terms(tartarus.lane)`) and detection markers, for the timeline. |
| `GET /analyses/{id}/events/{event_id}` | **Built.** Full event including `tartarus.raw`, annotations and related events (annotations wait for M5). |
| `POST /query/validate` | **Built.** `{query}` → `{ok, errors: [{start, end, message, suggestion}]}` (no `ast`). |
| `GET /query/fields` | **Built.** Field catalog for autocomplete: name, type, aliases, description, example, lane, members, searchable. |
| `GET /analyses/{id}/query/values?field=&prefix=&limit=` | **Built.** Top values for value autocomplete (terms aggregation with `include` regex). |

`filters[]` items are the quick-filter chips, `{field, value, negate}` as built (see "Events API (as
built)"). The backend ANDs them with the compiled `query`.

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
| `POST /search` | **Built (M9).** Across analyses: the body of `POST /analyses/{id}/events/search` (query, chips, filters, sort, `size`, `search_after`, `columns`), answering `{events[], total, next_cursor}` where each event carries its `analysis_id`. The cursor orders ties by analysis; a query or chip that does not compile is `422`. |
| `GET /iocs/{kind}/{value}/analyses` | **Built (M9).** The analyses whose events hold the indicator, `[{analysis_id, count}]`, most matching events first. `kind` is one of the IOC types of `iocs` (`domain`, `ip`, `url`, `registry`, `file`, `hash`); `mutex` is `422` (`unpivotable_ioc`). The value may contain slashes. |
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
| `GET /rules` | Every loaded rule as `{id, title, description, level, status, tags[], logsource_category, validity (valid\|invalid\|unsupported), error, enabled, path, hits}`; `hits` is the total Sigma detections across analyses, one terms aggregation over `tartarus-events-*` on `rule.id` (`event.kind: alert`, `rule.ruleset: sigma`), never stored. Filtering is the client's |
| `GET /rules/{id}` | The same plus `yaml`, the text of the rule's file; `404` for an unknown rule or a file that is gone or resolves outside the rules directory |
| `PATCH /rules/{id}` | `{enabled}`; answers with the rule. The flag is stored and survives reloads and restarts |
| `POST /rules/reload` | Re-scan `rules/sigma/` (also done automatically on file change, debounced) and answer as `GET /rules` |
| `GET /analyses/{id}/rules/hits` | `[{rule_id, count}]` for one analysis, most hit first, from that analysis's index |

### Export
| Method & path | Purpose |
|---|---|
| `GET /analyses/{id}/export/iocs?format=stix\|misp\|csv` | File download |
| `POST /analyses/{id}/export/report` | `{format: html\|pdf, include: {notes, screenshots, raw_iocs}}` → job. `GET /jobs/{id}/download` when done |

### Guests
Built in M6. The backend keeps no guest state: guests, builds and the media list belong to the **guest
control service** in the `cape` container ([cape-integration](cape-integration.md#guest-vm-build-wizard)),
and every route below is one request to it (`GUEST_CONTROL_URL`, with the bearer token
`GUEST_CONTROL_TOKEN`, over the `tartarus-control` network). The service validates every build and clone
parameter itself; the backend relays its answers. What differs between operating systems arrives as data,
from `GET /guests/profiles` ([guest profiles](guest-profiles.md)), so none of these routes names an OS.

The guest-changing routes (build, clone, resume, restart, continue, delete, check and self-test retry) answer `409` while
any analysis is queued, starting or running, on any guest. The message names each holder by analysis and guest
(`analysis 42 on lab3, analysis 43 on lab5`); with none starting or running yet, it names the queued ones.

**Errors** from the service pass through when they are the analyst's to read: its `404` is `404
not_found`, its `409` is `409 conflict` with its message, and its `422` (or `400`) is `422
validation_error` with one entry in `details.fields` per refused parameter, `location` `["body", "<dotted
path>"]` (`name`, `media.file`, `identity.machine`, `options.defender`, `resources.vcpus`) and `type`
`rejected`. Any other refusal, an unreachable service, a wrong token, a timeout and an unreadable answer
are `502 bad_gateway` with a fixed message that never contains the URL or the token.

| Method & path | Purpose |
|---|---|
| `GET /guests` | Every guest: `name`, `state` (`building`, `testing`, `ready`, `failed`, or `broken` for a record that cannot be read, which is listed with its `error` so it can be seen and deleted), `profile`, `kind` (`build` or `clone`), `cloned_from`, `media`, `options` (a `secret` option such as a product key reads `***`), `identity` (account, computer name and password: the password is shown so the analyst can log into the desktop), `resources`, `ip`, `machine` (UUID, MAC, serials), `work_dir`, `snapshot`, `selftest` (the last verdict), `adopted`, `giveaways` (for an adopted guest: what a sample can see), `badges` (derived by the profile from the options) and `build_id` (the guest's latest build or clone, which the build page opens). `502` when the control service is down |
| `GET /guests/media` | The installation media in `data/iso`, one entry per file and the profile that recognised it: `file`, `size`, `profile`, `kind` (`installer` or `disk_image`), `variants` (for Windows the editions: `index`, `name`, `edition_id`, `languages`, `build`), `version`, `build`, `language`, `arch`. A file nothing recognised is listed with an `error` saying why (not an ISO, truncated, no `install.wim`, not a Windows image) |
| `GET /guests/profiles` | What the wizard and the cards render from, per profile: `id`, `display_name`, `family`, `arch`, `resources` (defaults and `min_disk_gb`), `media.kinds`, `options` (key, label, type, default, help, choices, `requires_user_step`, `changeable_on_clone`), `identity` rules, `clone.computer_name_editable`, `badges`, `packages`, `agent.interactive` and `selftest.signals` |
| `POST /guests/build` | Starts a build: `{profile, name, media: {file, variant?}, options?, identity?: {account?, machine?, password?}, resources?: {vcpus?, ram_mb?, disk_gb?}}`. `202` with `{job_id, build_id, guest}`. The service refuses with `422` (per field) a `name` that is not 2 to 32 lower-case letters, digits or hyphens starting with a letter, is taken, is `kvm` or ends in `-clean` (that suffix names another guest's snapshot files); a `profile` that is not installed; a `media.file` that is not a plain name in the media list, not recognised by that profile or of a kind the profile has no pipeline for; a missing or unlisted `media.variant`; an option the profile does not have or a value of the wrong type; an identity value that does not match the profile's pattern, is reserved, or contains a giveaway word (`tartarus`, `sandbox`, `malware`, `virus`, `cuckoo`, or `cape`, `test`, `admin`, `analy...` as a whole word); resources outside the limits. Blank identity values are generated. `409` while an analysis is queued, starting or running, while another build, clone, check or self-test check is active, and when five guests are building, testing or ready (a `failed` one does not count, but it keeps its name and address until deleted) |
| `POST /guests/{name}/clone` | Clones a `ready` guest: `{name, options?, identity?: {machine?}, resources?: {vcpus?, ram_mb?}}`. Only what the profile marks `changeable_on_clone` may change (Windows: Defender, decoys), the account, password and disk size are the source's and a different value is `422`, and a computer name equal to the source's is refused. `202` with `{job_id, build_id, guest}` where `guest` is the new one. `404` for an unknown source; `409` when the source is not `ready` (and under the build rules above) |
| `GET /guests/builds/active` | The build a job is following now: `{build_id, guest, job_id}`; `404` when none is |
| `GET /guests/builds/{build_id}?tail=200` | The build: `id`, `guest`, `kind`, `status` (`running`, `paused`, `failed`, `succeeded`), `step` (the index of the current one), `steps[]` (`name`, `status`, `started`, `finished`, `exit_code`, `weight`, `timeout_s`, `desktop`, `progress`), `percent`, `message`, `pause` (`{instructions}` or `null`), `desktop` (the current step shows the guest's screen), and `log` (the last `tail` lines, 1 to 2000). `404` for an unknown id. A `succeeded` build is not yet a `ready` guest: the self-test follows |
| `POST /guests/builds/{build_id}/resume` | Runs a `failed` (or `paused`) build again from the step that stopped it. `202` as for a build; `409` under the build rules, or when the build is running or succeeded |
| `POST /guests/builds/{build_id}/restart` | Runs it again from the first step, discarding what was done. Same answers |
| `POST /guests/builds/{build_id}/cancel` | **Built (M7).** Stops a running or paused build: the running step's process group is stopped and the build ends `failed` with the message "the build was cancelled", so it can be resumed, restarted or its guest deleted. `202`; `409` when the build is neither running nor paused, or while an analysis is queued, starting or running; `404` when unknown |
| `POST /guests/builds/{build_id}/continue` | Carries on a `paused` build once the analyst has done what the pause asked: the step that paused runs again. `409` when the build is not paused |
| `GET /guests/{name}` | One guest's record; `404` when unknown |
| `DELETE /guests/{name}` | Unregisters the guest from CAPE, then removes its VM, snapshot, disks and nvram; `204`. Analyses that used it keep their data and the stored name. `409` while an analysis is queued, starting or running, while that guest's build is running or it is the source of the clone being made. A paused build's guest can be deleted. Deleting a different guest during a build is not refused, although it restarts `cape` under the build's registration step (an open item of the plan) |
| `POST /guests/{name}/check` | Runs the health checks now and answers `{name, checks: [{id, ok, message}]}` for `domain` (the VM is defined), `snapshot` (it exists), `registration` (CAPE's machine list shows it) and `agent` (the snapshot is restored and the agent answers; skipped when the first two fail; takes up to two minutes and leaves the guest off). `409` while an analysis is queued, starting or running, or while a build or clone is active; `404` when unknown |
| `POST /guests/{name}/selftest` | Runs the self-test again for a `failed` guest whose build finished (its disks and snapshot are kept, it is unregistered, and its record holds the failing verdict). The control service registers it with CAPE again (the register step of a build: `guests.conf`, restart `cape`, check the machine list) and sets it `testing`; the backend then follows it with the same `guest_build` job, whose self-test is the one a build runs, and the verdict makes the guest `ready` or `failed` again with the new verdict stored. `202` with `{job_id, build_id, guest}`, where `build_id` is the guest's last build. `404` for an unknown guest; `409` while an analysis is queued, starting or running, while a build, clone, check or self-test check is active, when five guests are building, testing or ready, when the guest is not `failed` ("lab1 is ready; only a failed guest has its self-test run again"), and when its build never finished, because it failed during a step and has no snapshot ("lab1 never finished building: restart or resume its build instead"), and when CAPE could not list it again (the guest stays `failed`) |

The route order matters: `/guests/media`, `/guests/profiles` and `/guests/builds/...` come before
`/guests/{name}`, so none of them is read as a guest called `media` or `builds`.

**The build job.** Every call that starts or continues a build, `build`, `clone`, `resume`, `restart` and
`continue`, makes sure a `guest_build` job is following that build and answers with it. A self-test retry starts the same job with `kind` `selftest`: the build had already succeeded, so the job skips following it (no build log is replayed) and goes straight to the self-test. A build has at most
one such job at a time, so `continue` on a paused build resumes the job that is waiting instead of starting
a second (the `job_id` it answers is that job's). The job only relays: the control service owns the build
and runs it whether the job lives or not, so a job that ends, is cancelled or is lost with the backend never
stops or undoes a build. A build that is deleted while its job still follows it (the analyst cancels it and
deletes its guest at once) ends the job `failed` with "the build was removed before it finished", logged without a
traceback; a 404 on the job's very first read is still an error.

- It polls the build every 2 s and passes on the step and percent (the build's steps fill the job's bar up
  to 90%, the self-test up to 99%), the new log lines, and the pause: when the build pauses the job's
  status becomes `paused` and its `result` is `{"pause": {"instructions": "..."}}`; when the analyst
  continues, the job is `running` again.
- A `failed` build fails the job with the build's message. The guest control service being unreachable
  is retried for 60 s, then the job fails; the build goes on inside the service and can be followed again.
- **Reattach.** After a backend restart the job runner marks jobs left `pending`, `running` or `paused`
  `interrupted` as for any job. Once the runner has started, the backend asks the service for its guests
  and submits a new job for each `building` guest whose build is still running or paused, and each
  `testing` guest whose build succeeded but whose verdict never came. A control service that is down at that
  moment is only logged.
- **Self-test.** When the build succeeds the job runs the guest's self-test: the profile's benign sample
  is fetched from the control service and queued as an ordinary analysis through `AnalysisSubmitter` with
  `gate=False` (so it can run on a guest that is `testing` while no other may), `guest` set to the new guest,
  `route=inetsim`, `timeout=60`, `interactive=false`, the package taken from the sample's extension when the
  profile lists it, and the tag `self-test`, so it shows on the Dashboard. The job waits for it (five
  minutes at most, polling every 2 s), reads the signals the profile lists out of the analysis's own
  data, then asks the service to run the guest-side checks (`facts`, `giveaways`, `proofs`; the
  checks take minutes). `selftest_verdict.judge` is a pure function of those: the analysis must be `done`;
  each listed signal must pass (see the [signal catalog](guest-profiles.md#self-test): the backend judges
  `events.process`, `events.file`, `events.registry`, `report.present` and `report.dns_answer`, and a signal it
  cannot judge fails); the guest must report no giveaway and no failed proof. The verdict
  (`{message, analysis_id, signals, proofs, giveaways, facts_summary}`) is sent to the service, which makes
  the guest `ready` or `failed` (unregistered, files kept) and stores it on the card; a failed verdict fails
  the job with "The self-test of x failed: ...". Not being able to start the test (the sample cannot be built
  or queued) is also a failing verdict. A control service that cannot be reached, or a database error, fails
  the job and leaves the guest `testing`.
- While any guest is `building` or `testing` the exclusion of
  [cape-integration](cape-integration.md#building-checking-deleting-and-analysing-exclude-each-other) holds:
  `POST /analyses` is `409`.

### Jobs
`GET /jobs/{id}` returns the status. `GET /jobs/{id}/download` returns the job's result file
when it has one.

A job's `status` is `pending`, `running`, `paused`, `done`, `failed` or `interrupted`. `paused` is for a job
that waits for a person: the instructions are in its `result` as `{"pause": {"instructions": "..."}}`, and
the job goes back to `running` when the person has acted. Only the `guest_build` job pauses today. A job
left `pending`, `running` or `paused` by a dead backend is marked `interrupted` at the next start. The
`guest_build` job (`params` `{guest, build_id, kind}`) follows one guest build or clone for the GUI; see
[Guests](#guests).

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
| `status` | `{status, phase, elapsed_s, remaining_s}`, sent on change and every 1 s while running. `remaining_s` counts down to the analysis's `deadline_at` once it is set (an interactive run, once the monitor has started in the guest; `AnalysisRead` carries the same field, `null` otherwise); before that it is `options.timeout` less the elapsed time |
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
`interactive`, or when CAPE ran the task on another guest than the analysis' (`desktop_machine_mismatch`), and `4408` ("desktop not available yet") when CAPE has not recorded the guest's VNC
port in the task's `options` within 90 s (polled every second through `tasks/view`). The first
frame is the tunnel's internal instruction (`0.,36.<uuid>;`) and internal `ping`s are echoed.
`guacd` is always told to connect to `127.0.0.1` at the recorded port, with clipboard off in both
directions; of the browser's instructions only `mouse`, `key`, `size`, `sync`, `ack`, `blob`,
`end` and `nop` reach `guacd`. An `error` from `guacd` (it follows `ready` when the guest is off)
is forwarded and then the tunnel closes, as it does when `guacd` hangs up or the analysis leaves
`starting`/`running` (checked every 2 s). There is no authentication: one local analyst, bound to
127.0.0.1.

### `WS /ws/guests/{name}/desktop`
The same tunnel for the screen of a guest while its build is at a step that shows one (the install, the
provisioning, a pause for the analyst); the two routes differ only in who may open one and where `guacd`
is pointed. The socket is accepted with the `guacamole` subprotocol, then closed with a code when refused:
`4404` for a guest that does not exist (or a name that is not a guest name), `4409` unless the guest has a
build that is `running` or `paused` whose current step is marked `desktop` in its profile's pipeline (so a
`ready` guest's desktop is never served here), and `4408` ("desktop not available yet") when the guest's VNC
display does not appear in time (it is defined a little before the step starts it; the wait is up to 90 s,
asked of the control service every second). `1011` closes it when the control service cannot be asked.
`guacd` is told to connect to the display address the control service reports for that guest inside the
`cape` container, not to anything the browser sent. Everything else is as for the analysis desktop:
clipboard off, the same allowlist of the browser's instructions, `error` forwarded, the tunnel closed when
the build leaves a desktop step (checked every 2 s), no authentication. The tunnel was proven by the
Guacamole handshake and the first drawing instructions of a real clone's `reconfigure` step; no browser
drove a build desktop for real.

### `WS /ws/system`
Pushes `health`, `queue`, `disk` and `job` (progress, step, status and pause instructions for guest builds
and exports; a `paused` job carries its instructions in `result`). `queue` is the `GET /system/queue` snapshot,
sent on connect and whenever it changes; the running clock (`elapsed_s`) does not count as a change.

## Live collector

- Starts when the analysis status becomes `running` and watches `analyses/<task>/logs/` and
  `analyses/<task>/aux/`.
- Keeps a per-file `(path, offset, record_index)` saved in memory and checkpointed in the `job`
  row every 5 s, so it can resume after a restart.
- Reads only complete BSON records. A partial trailing record waits for more bytes.
- capemon logs start with process and API-description messages. The parser keeps that state
  per file so it can map call indices to API names and argument names.
- The pipeline per batch (one poll, every log read) is: normalise → derive semantic events →
  Sigma match → enqueue to the bulk indexer and pub/sub. The batch is matched in event-time
  order and its alerts are appended to it, so an alert reaches the LIVE panel in the batch of the
  event that triggered it. The engine is built when the collector starts, with the rules active at
  that moment: a rule switched on or off mid-run applies from the next run.
- Live alerts are provisional. A repeat inside the suppression window raises
  `tartarus.detection.repeated` on the alert; when the alert is in an earlier batch the index
  document is rewritten by id and the hub is not sent the alert again. Logs can be read late, so
  an event may arrive older than ones already matched; the engine takes it as it comes (inside an
  open window it counts as a repeat), and the final ingest, which sorts, replaces the result.
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
- **Default ruleset (decided: a curated subset, see [M4](../plans/m4-sigma.md)):** ship a curated subset of SigmaHQ `rules/windows/` (process_creation,
  file_event, registry_*, network_connection, dns_query, image_load, create_remote_thread,
  process_access) with status `stable` or `test`, in `rules/sigma/default/`. Tartarus's own
  rules (the one the e2e's benign sample triggers) are in `rules/sigma/tartarus/`. The user can
  add their own rules to `rules/sigma/custom/`.
- A detection is emitted once per (rule, process) per 60 s window of event time, to suppress
  floods. The suppressed count goes into `tartarus.detection.repeated`. A detection's `event.id`
  depends only on the analysis, the rule and the triggering event, so live and final agree.

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

### Query language (as built)

Code: `app/query/` (`grammar.lark`, `parser.py`, `compiler.py`, `clauses.py`, `limits.py`,
`field_resolution.py`, `fields_api.py`), the field and alias tables in `app/search/fields.py`.
`compile_query(text)` returns `Compiled(query, errors)`: `query` is the OpenSearch query (`None` for an
empty query, which matches everything, and whenever `errors` is not empty), and a bad query is an error
value, never an exception. Where the grammar above is silent:

**Tokens.**
- A word directly followed by `:` or a comparison operator is a field name. Text that contains a colon
  (`http://x`, `C:\dir`) is written in quotes to be searched as free text; after `field:` a value may
  hold colons freely (`url:http://x/a?b=c`).
- Keywords are recognised wherever a term can start, so a free-text search for the word `or` is
  `"or"`. After `field:` they are plain values (`process.name:and`); inside `field:( ... )` only `OR`
  is a keyword.
- Bare words and quoted strings share one backslash rule: `\\` is one backslash, `\"` is a quote, any
  other backslash stays. The spec's `file.path:*\\AppData\\Roaming\\*.exe` and the single-backslash
  `*\AppData\Roaming\*.exe` are the same query; a UNC path needs four leading backslashes. A quoted
  string cannot end in a single backslash.
- `*` and `?` are wildcards in bare and quoted values and cannot be escaped. A bare `*` after `field:`
  is the exists test (`field:"*"` is a wildcard value). There is no regular-expression syntax:
  `/a.*b/` is a wildcard pattern.
- Field names and aliases are case-insensitive. Values are case-insensitive on keyword and flat-object
  fields, so `process.name:CMD.EXE` works; the argument name in `api.arguments.FileName` keeps its case.
- Precedence is `NOT`, then `AND` (explicit or adjacent), then `OR`.

**Field types.**

| Type | `field:value` | Ranges `> >= < <=` | Wildcards |
|---|---|---|---|
| keyword | `term` on the lowercased value | error | `wildcard`, case-insensitive |
| keyword with text (`file.path`, `process.command_line`, `process.executable`, `tartarus.summary`) | the exact value (`term`) OR a `match_phrase` on `<field>.text` | error | `wildcard` on the keyword |
| text (`rule.description`, `tartarus.detection.match`) | `match_phrase` | error | per-word `wildcard`; error if the pattern holds spaces |
| number | `term` | `range` | error |
| date | `range` with the value on both bounds, so `@timestamp:2026-10-13` is the whole day | `range`; ISO 8601 (date required) or epoch milliseconds (all digits) | error |
| boolean | `term`, `true` or `false` | error | error |
| ip | `term`, a CIDR range works | `range` on one address | error (use a CIDR range) |
| flat object (`api.arguments`) | case-insensitive `term` on any argument value; `api.arguments.<Name>:value` on one argument (verified on the real mapping) | error | `wildcard` |
| disabled object (`tartarus.raw`) | error: stored but not searchable | error | error |

A group of plain values on a keyword, number, boolean or ip field is one `terms` query; any other group
is a `bool` `should`. Wildcard patterns have their backslashes doubled, because OpenSearch gives `\` the
meaning of an escape inside a pattern (found on the real index: `c:\users*` matched nothing, `c:\\users*`
matched). Keyword values are lowercased code point by code point, as Lucene's lowercase filter does.

**Boolean structure.** `AND` is `bool.filter`, with its negated terms folded into `must_not`; `OR` is
`bool.should` with `minimum_should_match: 1`; `NOT` is `must_not`. Nested ANDs and nested ORs are
merged. `NOT x` alone matches every event without `x`, including events that lack the field.

**Free text** is searched as "contains", case-insensitively, in `tartarus.summary`,
`process.command_line`, `file.path`, `url.full` and every value of `api.arguments`: a `wildcard`
`*word*` on each keyword (and on the flat object), plus a `match_phrase` on the `.text` subfield for the
fields that have one. `powershell -enc` is two ANDed searches.

**Aliases.** The catalog's aliases: `pid`, `ppid`, `tid`, `proc` and `process` (process.name), `cmd` and
`cmdline`, `image`, `api`, `path`, `filename`, `sha256`, `reg`, `ip` and `dst.ip`, `port` and `dst.port`,
`src.ip`, `src.port`, `dns` (dns.question.name), `url`, `user_agent`, `lane`, `action`, `kind`,
`category`, `summary`, `rule`, `ruleset`, `sev` and `severity`, `technique` and `attack`, `tactic`. The
one composite alias is `domain` = `dns.question.name` OR `destination.domain` (`COMPOSITE_ALIASES` in
`fields.py`; it is no longer an alias of `destination.domain` alone).

**Errors** are `{start, end, message, suggestion}` with character offsets into the query text, one
syntax error at a time and every unknown field and bad value of a well-formed query together. An
unknown field suggests the closest names and aliases (`suggestion` is the best one, `message` lists up to
three); a value that does not fit its field's type is underlined at the value, a range operator on a
field that cannot take it at the whole comparison.

**Limits:** 2000 characters, 20 levels of `AND`/`OR`/`NOT` nesting, 100 terms (every value of a group and
every `field:*` counts), 25 wildcard terms (a leading wildcard is allowed and counted; a free-text word
counts as one because it is a contains search). Each is an error at the first place it is exceeded, and a
query over a limit is not compiled further.

`field_catalog()` and `suggest_fields(prefix)` in `fields_api.py` give the autocomplete endpoints their
data: every field and composite alias with type, aliases, description, example and lane, and a prefix
search by name, then by alias, then inside a name.

### Events API (as built)

Code: `app/api/events.py` and `app/api/query.py` (routers), `app/events/` (pure body builders and
response readers: `filters.py`, `search.py`, `cursor.py`, `facets.py`, `histogram.py`, `detail.py`,
`values.py`, `columns.py`; `execution.py` runs a search; `service.py` chains several), `app/schemas/events_api.py`
(request and response models). Operation ids are `events_search`, `events_facets`,
`events_histogram`, `events_detail`, `query_validate`, `query_fields`, `query_values`.

**The filter body** (search, facets, histogram) is `{query, filters[], time_range?, lanes?, pids?}`,
all ANDed. A chip is `{field, value, negate}`: `field` is a catalog name or alias resolved by the query
compiler's own resolution (`compile_filter_chip` in `app/query/compiler.py`), so a chip is exactly
`field:value` with the value taken whole (no quoting, wildcards still work); `negate` puts it in
`must_not`. `time_range` is `{from?, to?}`, both ends inclusive, a time without a zone is UTC, and
the range is applied to `@timestamp` at millisecond precision. `lanes` is a list of lane names and
`pids` of process ids; an empty list matches nothing. At most 50 chips and 1000 pids.

**Errors** use the one envelope `{error: {code, message, details}}`. A query or chip that does not
compile is `422` with `code: invalid_query` and `details.errors`: a list of `{start, end, message,
suggestion, filter_index}`; `filter_index` is null for an error in the query text and the chip's
position in `filters[]` for a chip, whose spans count characters of the text `field:value`. A
malformed or foreign cursor is `422 invalid_cursor`; a facet field that cannot be aggregated (text,
flat object, unsearchable, a composite alias, unknown) is `422 invalid_facet_field`; a values field
that is not a keyword is `422 invalid_value_field`; a search column that cannot be shown (unknown,
a composite alias, `tartarus.raw`, or one argument such as `api.arguments.FileName`) is `422
invalid_column` naming it. More than 12 columns is the framework's validation `422`. An unknown analysis (or event) is `404 not_found`.
An analysis whose index does not exist answers search, facets, histogram and values with empty
results, not an error. Every search carries `timeout: 10s` and the client a 15 s request timeout;
either, or a partial result, is `504 search_timeout`, and any other OpenSearch failure is `502
search_failed` (logged; the OpenSearch error is not returned).

**Search paging.** Events are sorted by `(@timestamp, event.sequence, event.id)`, all three in the
direction of `sort`. The ingester numbers events uniquely, so the id only matters if two events share
a time and a sequence (events without a sequence sort last), but it makes the order total, so paging
reaches every event exactly once. The body asks for `size + 1` events: if the extra one arrives there
is a next page, and `next_cursor` is built from the last event of the page; the last page, even a full
one, has `next_cursor: null`. The cursor is `base64url(JSON {sort, after: [ms, sequence, id]})`
without padding, sent back as `search_after`. A cursor issued for the other sort is refused.
`total` is exact (`track_total_hits`). The page's events leave out `tartarus.raw`.

**Search columns.** `columns` lists catalog fields or aliases (any searchable field except the
disabled `tartarus.raw`, and no composite alias such as `domain`) that the table shows beyond the
typed `Event`. Each is resolved by the query's own field resolution (`app/events/columns.py`,
sharing `aggregatable.py` with facets and values); an alias is keyed by its canonical name and a
repeat is collapsed. Each returned event has `fields`, `{canonical name: value}`, read from the
document by its nested path, so a value is a string, number, boolean, list, or for the flat object
`api.arguments` a dictionary; a column the event has no value for is left out, and without `columns`
`fields` is `{}`. With columns the body asks OpenSearch for `_source` `includes`: the fields of
`EVENT_SOURCE_FIELDS` (what the typed `Event` reads) plus the columns, so `tartarus.raw` and
everything else stays behind; without them it is the old `excludes: [tartarus.raw]`. In the OpenAPI
schema the value is the recursive `JsonValue` (`string | number | boolean | JsonValue[] |
{[key]: JsonValue} | null`), and `Event.fields` is required.

**Event** (`Event`) is the typed subset the table needs: id, time, sequence, lane, kind, category,
action, module, dataset, summary, severity (name), process `{pid, name, entity_id}`, api name, rule
name and ruleset, destination `{ip, port, domain}`, DNS query, URL, file path and registry path.
`GET events/{id}` returns `{event, source, related}`: `source` is the whole stored document including
`tartarus.raw`; `related.references` are the events named in this event's `related.events` (at most 50,
oldest first, `total` counting those that exist in the index) and `related.referenced_by` the events
whose `related.events` names this one's id (at most 50, `total` all of them). The id is the path
remainder (`{event_id:path}`), so slashes and colons work encoded or not.

**Facets** return `{facets: [{field, values: [{value, count}], total}]}` in the order requested, `field`
as requested, `total` the number of events with any value. Booleans and dates come back as
text. Fields default to the six of the table above; at most 20.

A facet ignores the chips on its own field (multi-select faceting), so after `process.name: cmd.exe`
the process facet still lists the other processes and a negated value still shows with its count.
A chip counts as being on a field when the query compiler's own resolution (`resolve_query_field`)
of its name or alias has that field among its targets, so `proc` is `process.name` and the composite
`domain` is on both `dns.question.name` and `destination.domain`. For each facet the counts, and its
`total`, are under the filter without those chips; the query text, the chips on other fields, the
lanes, pids and time range apply to every facet. The body is built so: the request's `query` is the
filter without any chip on a requested facet field (the part every facet shares, so a chip on a field
that is not a facet stays in it), and each facet is a `filter` aggregation `facet_<n>` holding only the
chips on the other facets, with its `terms` (`values`) and `exists` (`present`) aggregations inside.
The filter is compiled once (`compile_filter` in `filters.py`), so a bad chip is the one `422
invalid_query` with its `filter_index`. A facet's values can still sum to less than its `total` (only
the top ten are listed), and to more for a field that holds several values per event.

**Histogram** returns `{interval_ms, from, to, total, buckets: [{time, total, by_lane}], detections}`.
The span is the time range where it names an end, else the first and last matching event (`from` and
`to` are null when nothing matches and the range gives none). `auto` is the smallest of a fixed list of
steps (1, 2, 5, 10, 20, 50, 100, 200, 500 ms; 1, 2, 5, 10, 15, 30 s; 1, 2, 5, 10, 15, 30 min; 1, 2, 3,
6, 12 h; 1, 2, 7, 14, 30 days) that makes at most 120 buckets; an explicit `interval` (ms, at least 1)
is widened just enough to stay within 2000. Buckets are aligned to the epoch and contiguous from the
one holding `from` to the one holding `to`, empty ones included; they sum to `total`, and each
bucket's `by_lane` sums to its `total` (an event without a lane counts under `unknown`). `detections`
are the matching `event.kind: alert` events, oldest first, at most 500, as `{time, id, name,
severity, ruleset}`.

**Query validation and catalog.** `POST /query/validate` runs the compiler without a search. `GET
/query/fields` lists the whole catalog (including composite aliases and the unsearchable
`tartarus.raw`, `searchable: false`); with `prefix` it is `suggest_fields`, searchable fields only, at
most 50.

**Value autocomplete** takes `field`, `prefix` and `limit` (1 to 50, default 10) and runs a `terms`
aggregation per field with `include` set to the prefix, lowercased and with every Lucene regex
character escaped, so the match is case-insensitive and literal. Only keyword fields are accepted; the
composite alias `domain` queries both members and sums the counts of equal values. Values are as
indexed, that is lowercase. It looks at the whole analysis, not at the current filter.

## Exports

| Format | Content |
|---|---|
| **STIX 2.1** bundle | `identity` (Tartarus), `malware` (families, if detected, else "unknown"), `file` SCOs + `indicator`s for sample, dropped and payload hashes, `domain-name` / `ipv4-addr` / `url` indicators, `attack-pattern`s for ATT&CK techniques, `relationship`s (indicator `indicates` malware, malware `uses` attack-pattern), `note`s from the analyst's notes |
| **MISP** event JSON | Event info `Tartarus analysis #id – filename`, attributes (sha256, md5, domain, ip-dst, url, filename, regkey, mutex) with `to_ids` set for network IOCs and hashes, tags (`tlp:amber` default, analyst tags, ATT&CK galaxy tags) |
| **CSV** | `type,value,context,first_seen,source_process` |
| **HTML report** | Self-contained single file in the Tartarus theme: summary, score, families, ATT&CK, process tree (static SVG), key events, network, IOCs, detections, screenshots, the analyst's tags and notes |
| **PDF report** | Same content from the same template, rendered by WeasyPrint in a print variant: white background, ice-blue accents and the same severity colours |

## Configuration (`.env`)

`TARTARUS_PORT=8080` (the frontend's published port; the backend listens on `8000` internally), `TZ`, `OPENSEARCH_HEAP=1536m`,
`GUEST_SUBNET=192.168.150.0/24`, `CAPE_REF=<commit>`, `DEFAULT_ROUTE=inetsim`,
`DEFAULT_TIMEOUT=180`, `DISK_WARN_GB=50`, `DISK_BLOCK_GB=20`, optional `VPN_*` / `WG_*` /
`SOCKS5_*`. Secrets such as the CAPE API token and the callback token are generated on first
start into `data/secrets.env`.

The backend reads `GUEST_CONTROL_URL` (compose sets `http://cape-control:8002`: the name `cape-control` exists
only on the `tartarus-control` network, so the control service is not reached over `tartarus-internal`) and
`GUEST_CONTROL_TOKEN` (required: compose refuses to start without it; `openssl rand -hex 32` makes one, 32
characters at least, and `make preflight` checks it). With no token the client answers `502`. There is no
longer a `GUEST_LABEL` setting: which guest an analysis runs on is a per-analysis option. The guest's size
and name belong to the build (wizard, or `make build-guest`, whose `GUEST_*` variables are read only by that
script).

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
- Guests: the control client is tested against answers captured from the real service
  (`backend/tests/guest/fixtures/`) behind a fake `GuestControl`, so every state (none, one ready, several, a
  failed one, building, control down) is a test with no container; `make verify-wizard` drives the public API
  against the real stack (about six minutes: it clones a ready guest with Defender the other way round, checks
  that analyses and a second clone are refused meanwhile, runs an analysis on it, and deletes it).
- End-to-end: the guest self-test sample (see cape-integration) runs in the dev environment, and `make e2e`
  (`scripts/e2e.sh`, helpers in `scripts/lib/`, browser tests in `frontend/tests/e2e/`) checks the real stack:
  step (a) submits it and checks the report views and, in `e2e-query.sh`, that the finished analysis answers
  the query API (validation, paging in both sorts, query and chip narrowing, error answers, facets, histogram,
  event detail, value autocomplete, columns) with counts equal to the analysis record's own; the browser flow
  repeats the filtering through the Events and Timeline tabs. The bash assertions have their own tests
  (`scripts/tests/test_e2e_query.sh`, `test_e2e_cleanup.sh`) against fake APIs, each fault of which must be
  caught by its check.
