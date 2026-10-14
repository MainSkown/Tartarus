# Data model

Tartarus stores data in three places:
- **PostgreSQL** (`tartarus` database) holds the metadata Tartarus owns.
- **OpenSearch** holds every event, one index per analysis.
- **The filesystem** (the CAPE storage volume and the Tartarus sample store) holds the
  artefacts.

CAPE's own PostgreSQL task database is a CAPE internal, and Tartarus never writes to it directly
(only through apiv2). There is no MongoDB: Tartarus doesn't use CAPE's Mongo-backed report
viewer, and the final report is ingested from the `report.json` file CAPE's `jsondump` module
writes to the shared storage volume. See [architecture](../architecture.md#compose-services).

## PostgreSQL (SQLAlchemy 2 models, Alembic migrations)

### `sample`
| Column | Type | Notes |
|---|---|---|
| `sha256` | text PK | |
| `sha1`, `md5` | text | |
| `size` | bigint | |
| `file_type` | text | From `file`/TrID (e.g. "PE32+ executable") |
| `original_name` | text | Name from the first submission |
| `stored_path` | text | Zipped with password `infected` at rest |
| `first_seen` | timestamptz | |

### `analysis`
| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK (identity) | Shown in the UI as `#42` |
| `sample_sha256` | FK → sample | A sample can be analysed many times |
| `filename` | text | Name as submitted |
| `cape_task_id` | int, nullable | Set when submitted to CAPE |
| `status` | enum | `queued`, `starting`, `running`, `processing`, `ingesting`, `done`, `failed`, `report_failed`, `cancelled` |
| `phase` | enum | `live`, `final` |
| `options` | jsonb | `{route, timeout, package, memory_dump, interactive}` |
| `score` | numeric(3,1), nullable | CAPE malscore 0–10 |
| `max_severity` | enum, nullable | `info`, `low`, `medium`, `high`, `critical` |
| `detected_families` | text[] | From CAPE detections and config extraction |
| `event_count` | bigint | Updated by the indexer |
| `disk_bytes` | bigint | Index size + artefacts. Recomputed after ingest and on demand |
| `error` | text, nullable | Shown on failure |
| `submitted_at`, `started_at`, `finished_at` | timestamptz | |

### Annotations
| Table | Columns |
|---|---|
| `tag` | `id`, `name` (unique, lowercase, `[a-z0-9._-]{1,40}`), `created_at` |
| `tag_link` | `id`, `tag_id` FK, `analysis_id` FK (cascade), `target_type` enum(`analysis`,`process`,`event`), `target_ref` text (`""` for analysis, `pid` for process, `event.id` for event); unique(`tag_id`,`analysis_id`,`target_type`,`target_ref`) |
| `note` | `id`, `analysis_id` FK (cascade), `target_type`, `target_ref`, `body` text (plain text, ≤ 20 000 chars), `created_at`, `updated_at` |

Processes are identified by `pid` within an analysis. Windows reuses PIDs only rarely within one
short run; if reuse is detected, the process key becomes `pid@start_ts`.

### Rules, guest, jobs, settings
| Table | Columns |
|---|---|
| `sigma_rule` | `id` (the Sigma rule UUID), `title`, `level`, `status` (Sigma status), `path`, `content_sha256`, `enabled` bool (default true), `valid` bool, `error` text, `loaded_at` |
| `guest_vm` | `id`, `name`, `os_label` (e.g. "Windows 11 23H2 Pro"), `vcpus`, `ram_mb`, `disk_gb`, `ip`, `snapshot`, `state` enum(`building`,`ready`,`broken`), `last_check` jsonb, `created_at` |
| `job` | `id`, `type` enum(`guest_build`,`ingest`,`reingest`,`export_report`,`delete_analysis`), `analysis_id` nullable, `status` enum(`pending`,`running`,`done`,`failed`,`interrupted`), `step` text, `progress` 0–100, `log` text (tail), `result` jsonb, `created_at`, `updated_at` |
| `setting` | `key` text PK, `value` jsonb: default route, default timeout, default interactive, disk warn/block thresholds, timeline aggregation threshold |

## OpenSearch

### Index layout
- **One index per analysis:** `tartarus-events-<analysis_id>`. Deleting an analysis drops its
  index, which is fast and frees disk immediately. Cross-analysis search is out of scope for v1.
  If it's added later, it can use an alias across these indices.
- Created from the index template `tartarus-events` (priority 100, pattern `tartarus-events-*`):
  1 shard, 0 replicas, `refresh_interval: 1s` while live and `30s` after ingest, and
  `best_compression` codec.
- `mappings.dynamic: false`. Only declared fields are indexed. Unknown source fields are kept in
  `_source` under `tartarus.raw` (not indexed) so they still show in the event detail.
- Keyword fields use a `lowercase` normalizer, so queries are case-insensitive. Windows paths
  and API names are case-insensitive.

### Event document (ECS + `tartarus.*` and `api.*` extensions)

Common fields on every document:

| Field | Type | Notes |
|---|---|---|
| `@timestamp` | date (ms) | Event time in UTC. capemon times are shifted by the report's calibrated guest clock offset ([time in a CAPE report](#time-in-a-cape-report)) |
| `event.id` | keyword | Deterministic: `sha1(analysis_id, source, source_file, record_index)` |
| `event.sequence` | long | Order within the analysis |
| `event.kind` | keyword | `event` or `alert` (detections) |
| `event.category` | keyword[] | ECS categories (`process`, `file`, `registry`, `network`, `malware`, `intrusion_detection`, …) |
| `event.type` | keyword[] | ECS types (`start`, `end`, `creation`, `deletion`, `change`, `access`, `connection`, `protocol`, `info`, `indicator`) |
| `event.action` | keyword | Specific action, e.g. `process-created`, `file-written`, `reg-value-set`, `dns-query`, `api-call`, `inject-thread` |
| `event.module` | keyword | `capemon`, `sysmon`, `etw`, `suricata`, `volatility`, `cape`, `sigma`, `yara`, `tartarus` |
| `event.dataset` | keyword | e.g. `capemon.api`, `sysmon.evtx`, `etw.dns`, `suricata.alert`, `cape.signature` |
| `event.severity` | integer | 0 info, 1 low, 2 medium, 3 high, 4 critical (alerts only) |
| `tartarus.analysis_id` | long | |
| `tartarus.lane` | keyword | `process`, `file`, `registry`, `network`, `memory`, `api`. The timeline lane, which drives category colour |
| `tartarus.phase` | keyword | `live` or `final` (which phase produced it) |
| `tartarus.summary` | text + keyword | One-line human summary, e.g. `cmd.exe wrote C:\Users\…\a.ps1` |
| `tartarus.raw` | object, `enabled: false` | Original record, for the detail view |

Process context (on every event that has one):

| Field | Type |
|---|---|
| `process.pid`, `process.parent.pid`, `process.thread.id` | long |
| `process.name`, `process.parent.name` | keyword |
| `process.executable`, `process.command_line` | keyword + text subfield |
| `process.parent.executable`, `process.parent.command_line` | keyword + text subfield: the parent's path and command line, on `process-created` events only (Sigma `ParentImage`, `ParentCommandLine`) |
| `process.entity_id` | keyword (`<analysis>:<pid>@<start_ts>`) |
| `process.start` | date |
| `process.integrity_level` | keyword (custom) |
| `tartarus.inject.target_pid` | long: the process an `inject-*` event acts on, when the call names it (lane `process`) |
| `tartarus.inject.target_name` | keyword: that process's image file name, when the run has seen it (lane `process`) |
| `tartarus.inject.target_executable`, `tartarus.inject.target_command_line` | keyword + text subfield: its path and command line, when the run has seen them (lane `process`) |

Category fields:

| Lane | Fields |
|---|---|
| file | `file.path` (keyword + text), `file.name`, `file.extension`, `file.size`, `file.hash.sha256`, `file.target_path` (rename/move) |
| registry | `registry.path`, `registry.hive`, `registry.key`, `registry.value`, `registry.data.type`, `registry.data.strings` |
| network | `source.ip`/`port`, `destination.ip`/`port`/`domain`, `network.transport`, `network.protocol`, `dns.question.name`, `dns.question.type`, `dns.answers.data`, `url.full`, `http.request.method`, `http.response.status_code`, `user_agent.original`, `tls.server.sni`, `tls.server.ja3s`, `tls.client.ja3` |
| api | `api.name` (keyword), `api.category` (capemon category: process, filesystem, registry, network, synchronisation, crypto, …), `api.status` (bool), `api.return_value` (keyword), `api.arguments` (`flat_object`: arbitrary argument names without mapping explosion), `api.repeated` (count when capemon collapsed repeats) |
| memory | `tartarus.memory.plugin` (Volatility plugin), `tartarus.memory.address`, `tartarus.memory.protection`, `tartarus.memory.dump_ref` (artefact id) |

Detections (`event.kind: alert`, lane = the lane of the triggering event, drawn on the
detections track):

| Field | Notes |
|---|---|
| `rule.id`, `rule.name`, `rule.description`, `rule.ruleset` | ruleset ∈ `sigma`, `cape`, `yara`, `suricata` |
| `rule.reference` | URLs |
| `threat.technique.id` / `.name`, `threat.tactic.name` | ATT&CK mapping (Sigma tags `attack.t1055` → `T1055`) |
| `related.events` | `event.id`s that triggered it |
| `related.hash`, `related.ip`, `related.hosts` | Pivots |
| `tartarus.detection.match` | Text of the matched condition, for the detail view |
| `tartarus.detection.repeated` | long: how many repeats of this detection the 60 s suppression window swallowed |

### Mapping from sources

The **source** lane lists the input; the **ECS action** and **ECS lane** columns are what it
becomes in the event document.

| Source | Source lane | ECS action | ECS lane |
|---|---|---|---|
| capemon `CreateProcessInternalW`, `NtCreateUserProcess` | api | `process-created` (also emitted as a derived process event) | process |
| capemon `NtTerminateProcess` | api | `process-terminated` (derived) | process |
| capemon `NtWriteFile`, `NtCreateFile`, `NtDeleteFile`, `MoveFileWithProgressW` | api | `file-*` (derived) | file |
| capemon `RegSetValueExW`, `NtSetValueKey`, `RegCreateKeyExW`, `RegDeleteValueW` | api | `reg-*` (derived) | registry |
| capemon `connect`, `InternetOpenUrlW`, `WinHttpSendRequest`, `getaddrinfo`, `DnsQuery_*` | api | `net-*` (derived) | network |
| capemon `NtWriteVirtualMemory` (cross-process), `NtCreateThreadEx`/`CreateRemoteThread` (remote), `NtQueueApcThread`, `NtMapViewOfSection` (remote) | api | `inject-*` (derived) | process |
| Any other capemon call | api | `api-call` | api |
| Sysmon EID 1 / 5 | n/a | `process-created` / `process-terminated` | process |
| Sysmon EID 3 / 22 | n/a | `network-connection` / `dns-query` | network |
| Sysmon EID 7 | n/a | `image-loaded` | process |
| Sysmon EID 8 / 10 | n/a | `create-remote-thread` / `process-access` | process |
| Sysmon EID 11 / 23 / 26 | n/a | `file-created` / `file-deleted` | file |
| Sysmon EID 12 / 13 / 14 | n/a | `reg-key` / `reg-value-set` / `reg-rename` | registry |
| ETW DNS / network / WMI / AMSI | n/a | `dns-query` / `network-*` / `wmi-*` / `amsi-scan` | network / network / process / process |
| Suricata flow, http, dns, tls | n/a | `flow` / `http-request` / `dns-query` / `tls-handshake` | network |
| Suricata alert | n/a | detection, `rule.ruleset: suricata` | network |
| CAPE signature | n/a | detection, `rule.ruleset: cape` | lane of the referenced call, or `process` |
| YARA hit (file, memory or payload) | n/a | detection, `rule.ruleset: yara` | file or memory |
| Volatility3 findings (malfind, hollowprocesses, …) | n/a | `memory-finding` | memory |

"Derived" means the raw API call stays in the `api` lane, and the backend also emits a
higher-level event in the semantic lane. That derived event links back through
`related.events`. This way the process, file, registry and network views work from capemon
alone, without Sysmon.

#### capemon derivation rules (as built)

Written from the real report (`behavior.processes[].calls[]`) and implemented in
`backend/app/ingest/capemon_rules.py`; the arguments marked (spec) are not in the sample report
yet and follow capemon's argument names, so they need a second real report to confirm.

Every call yields one `api-call` event (lane `api`, `event.dataset: capemon.api`). A call that
matches a row yields one more event (dataset `capemon.derived`), placed directly after it, whose
`related.events` holds the `api-call` event id. Both carry the owning process; the derived event
shares the call as `tartarus.raw`. A rule that finds its argument missing or unusable derives
nothing and never raises. "Ok" means the call's `status` is true.

| Calls | Derives | Condition | Fields from the call |
|---|---|---|---|
| `NtCreateUserProcess`, `CreateProcessInternalW` | `process-created` | Ok, `ProcessId` > 0, and no earlier call (by timestamp, then call id) created the same pid | `process` is the **child** (pid `ProcessId`, `parent.pid` the caller, `command_line` from `CommandLine`, executable and start from the child's own process record, else `ImagePathName`/`ApplicationName`); `parent.name`, `parent.executable` and `parent.command_line` are the calling process's own, each left out when the report does not carry it |
| `NtTerminateProcess` | `process-terminated` | Ok and `ProcessHandle` is the current-process pseudo handle (`0xffffffff`); handle `0` (ending the other threads) and real handles derive nothing | owning process |
| `NtWriteFile` | `file-written` | Ok and `HandleName` is a filesystem path (`C:\`, `\??\`, or a UNC `\\server\`); `\Device\ConDrv`, pipes and other devices derive nothing | `file.path` = `HandleName` |
| `NtCreateFile` | `file-created` | Ok and `ExistedBefore` = `no` | `file.path` = `FileName` |
| `NtDeleteFile` (spec) | `file-deleted` | Ok and `FileName` is a filesystem path | `file.path` = `FileName` |
| `MoveFileWithProgressW` (spec) | `file-moved` | Ok and both `ExistingFileName` and `NewFileName` are filesystem paths | `file.path`, `file.target_path` |
| `RegCreateKeyExA/W` | `reg-key-created` | Ok and `Disposition` = `1` (a new key; 2 is an existing key being opened) | `registry.*` from `FullName` |
| `RegSetValueExA/W`, `NtSetValueKey` | `reg-value-set` | Ok and a path in `FullName` (else `ObjectAttributes`) | `registry.*` from the path, `ValueName`, the pretty `Type`, `Buffer` as `registry.data.strings` |
| `RegDeleteValueA/W`, `NtDeleteValueKey` (spec) | `reg-value-deleted` | Ok and a registry path | as above |
| `RegDeleteKeyA/W`, `RegDeleteKeyExA/W`, `NtDeleteKey` (spec) | `reg-key-deleted` | Ok and a registry path | `registry.*` |
| `getaddrinfo`, `GetAddrInfoW`, `GetAddrInfoExW` | `dns-query` | `NodeName` present (an attempt counts, ok or not) | `dns.question.name` = `NodeName` |
| `DnsQuery_A/W/UTF8` (spec) | `dns-query` | `Name` present | `dns.question.name` = `Name` |
| `connect`, `WSAConnect` (spec) | `network-connection` | `ip` present (an attempt counts) | `destination.ip` = `ip`, `destination.port` = `port` |
| `InternetOpenUrlA/W` (spec) | `http-request` | `URL` present | `url.full` |
| `NtWriteVirtualMemory`, `WriteProcessMemory` (spec) | `inject-write-memory` | Ok and the call targets another process (below) | owning process; the summary names the target pid; `tartarus.inject.target_pid` when the call carries a pid, and `target_name`, `target_executable`, `target_command_line` of the process that held that pid at the call's time (below) |
| `NtCreateThreadEx`, `NtCreateThread`, `CreateRemoteThread(Ex)` (spec) | `inject-thread` | Ok and another process | as above |
| `NtMapViewOfSection` (spec) | `inject-map-section` | Ok and another process | as above |
| `NtQueueApcThread(Ex)`, `QueueUserAPC` (spec) | `inject-apc` | Ok and `ProcessId` names another process | as above |

*Another process*: the target pid (`ProcessId`, else `ProcessIdentifier`) differs from the
caller's; with no pid in the call, `ProcessHandle` is neither `0` nor the current-process pseudo
handle. Handles are not resolved to pids.

*Process context of the target*: the derivation keeps every process it has seen, in the order seen.
`target_*` come from the process that held the pid at the call's time: the latest one that started
at or before the call, else the first seen when the call precedes them all (a log can open a moment
after the first write into a suspended child). A pid the run has not seen (a process capemon never
logged) gets only `target_pid`; a missing field is left out, never empty and never guessed. A
reused pid therefore names different processes at different times. The `process-created` parent
needs no lookup: it is the process that made the call, so its identity is the caller's by
construction, whatever the pid's history.

Choices that differ from the mapping table above:
- Network actions are `dns-query`, `network-connection` and `http-request`, the Sigma-facing names
  already used for Sysmon and ETW, not a capemon-only `net-*` family.
- `WinHttpSendRequest` is not derived: the call carries no URL (capemon logs headers and data),
  so HTTP for it comes from the CAPE network records.
- Calls with no row (`NtClose`, `EventUnregister`, `LdrGetDllHandle`, `NtQueryValueKey`, `NtOpenFile`,
  `NtAllocateVirtualMemory`, ...) stay `api-call` only.

Event fields on every capemon event:
- `@timestamp` is the call's `timestamp` plus the report's guest clock offset (below), so it is UTC.
  A call whose timestamp cannot be read takes the analysis start, which is already UTC and is not
  shifted. `process.start` and the `entity_id` built from it use the same shifted `first_seen`, so an
  `entity_id` carries the calibration: it changes if the clock offset does (live to final, see below).
- `event.sequence` numbers the events in emission order: calls sorted by timestamp, then call id,
  then report order; a derived event directly follows its call.
- `api.arguments` maps each argument name to its `value` (the first of a repeated name); the
  pretty form stays in `tartarus.raw`. `event.category` of an `api-call` follows the call category
  (`filesystem` is `file`, `registry`, `network`, `process` and `threading` are `process`, anything
  else is `host`).
- `event.severity` is 0 on every capemon event; only detections carry a higher level.
- `event.id` is `sha1(analysis_id, "capemon", "processes/<pid>", call position in that process)`; a
  derived event uses the file `processes/<pid>#derived`, so the two never collide. The id is per
  process (not one running number over the whole report) so the live collector, which reads each
  process's log as it grows, can compute the same id before it knows how long the other processes'
  logs will be. The live path matches the report path exactly except where CAPE merged consecutive
  identical calls (and renumbered the rest), which the live parser does not do.
- The parent and injection-target fields are filled by the same derivation code (`DerivationRun`) in
  both paths, so a live document equals the final one for the same calls (tested on a scripted run
  with a creation, injections into a known, an unknown and a reused pid, fed in every batch size).
  One exception: live resolves a target from the process logs opened so far, so an injection read
  before the target's log has opened carries only `target_pid`; the final ingest, authoritative,
  fills the rest. A `process-created` event waits for the child's log (above) but an injection does
  not, since its target may never log.

### CAPE report normalisers (as built)

`cape-network` and `cape-signatures` read the same `report.json` as capemon
(`backend/app/ingest/{cape_network,cape_signatures,attribution,clock}.py`). Every event they emit has
`event.module: cape`, `phase: final`, and a deterministic id from `(analysis, source, list name,
position in the list)`.

#### Time in a CAPE report

True UTC is the CAPE host's: `info.started`/`ended` and the epoch floats of `network.*`. capemon's
call timestamps and `behavior.processes[].first_seen` come from the guest monitor's clock, which is
behind the host's by two things, both measured per analysis in `app/ingest/clock.py`, never assumed:

- **The host's UTC offset** (2 hours in summer, 1 in winter in Warsaw): `info.started - earliest
  process first_seen`, rounded to the nearest 15 minutes (the raw gap is the true offset minus the 13
  to 33 seconds between machine start and the first process).
- **A skew of seconds**: CAPE sets the guest's clock to the task's creation time (`Date set to:` in
  `analysis.log`, `task.clock`), not to the moment it is set, so the guest runs 4.4 to 7.1 s behind
  the host (eight real analyses). The skew is **constant within a run** (7.143 to 7.147 s over the 12
  processes and 140 s of an interactive run; the first and last process agree to 4 ms) and differs
  between runs, so one number per analysis is exact.

The exact anchor is the host's own record of a process registering: ResultServer logs
`Task N: Process PID (parent P): name, path ...` in the task's `cuckoo.log` with a millisecond host
time, and logs it before it writes the process's first bytes (`BsonStore.handle`). `registration time
- first_seen` of the same process is the whole offset, skew included.

- `host_registrations(log_text)` reads those lines into `{pid: host time}` (first registration of a
  pid wins; any other line, garbage and a missing or unreadable file give nothing, never an error).
  The ingester reads `<task folder>/cuckoo.log`, two levels above `reports/report.json`, into
  `IngestContext.host_registrations`.
- `guest_clock_offset(report, registrations)` uses the earliest process the log knows:
  `registered_at - first_seen`, added to every capemon timestamp and process start. The anchor is
  used only when it agrees with the rounded offset to within 5 minutes (`ANCHOR_TOLERANCE`), which
  rejects a pid reused for another process or a log in another zone; otherwise, and when the log has
  no process of the report, the offset is the rounded one (the previous behaviour).
- A report that cannot be calibrated (no readable `info.started`, no process, a gap beyond 14 hours)
  has offset 0; the helper never raises.
- `IngestContext.started_at` is `info.started` read as UTC (`analysis_started(report)`); the caller
  builds the context with it.
- **Live uses the rounded offset only.** CAPE's per-task `cuckoo.log` is opened buffered and never
  flushed (`lib/cuckoo/core/log.py`, `TaskHandler`): its lines reach the disk 8 KiB at a time or when
  the task ends, so there is nothing to read when the first process record arrives. The collector's
  context has no registrations; live events sit the skew (5 to 7 s) earlier than the final index's,
  and so do their `process.entity_id`s. The final ingest rebuilds the index and is authoritative. The
  live and report paths are the same code and give identical events whenever both are given the same
  registrations (tested on the real task 45 files).
- Result on the eight real analyses (the sample's own `getaddrinfo` against the pcap's DNS record of
  the same name): 4.4 to 7.1 s apart with the rounded offset, 11 to 51 ms with the anchor (the packet
  leaves the guest a few milliseconds after the call). Events of different sources can be ordered
  against each other at that precision.

#### `cape-network`

| Record | Event | Time |
|---|---|---|
| `dns[]` | `dns-query`: `dns.question.name/type`, `dns.answers.data` (every answer's `data`), `network.protocol: dns`, answers that are IP addresses also in `related.ip` | `first_seen` (epoch, UTC) |
| `tcp[]`, `udp[]` | `network-connection`: `source.ip/port`, `destination.ip/port`, `network.transport` | `context.started_at` plus the relative `time` (below) |
| `http[]` | `http-request`: `http.request.method`, `url.full` (`uri`), `user_agent.original`, `destination.domain` (`host`) and `port`, `network.protocol: http` | `first_seen` when present, else the `dns[]` record for the same host, else the analysis start |

- A DNS answer's address is not `destination.ip`: that is the resolver. It goes to `related.ip`.
- `domains` and `hosts` add no events: `hosts` was empty, and `domains[].ip` disagrees with the `dns[]`
  answers for the same name in the fixture, so its provenance is unclear.
- A record missing its essential field (`request`, `dst`, both `host` and `uri`) is skipped; a flow
  with an unreadable `time` takes the analysis start.
- **Relative flow time.** `tcp`/`udp` carry only `time`, seconds since the first packet of the pcap, and
  the pcap's start is not in the report. The base is `info.started`: it is the only absolute instant the
  report gives for the whole run, and a flow can then never be placed before the analysis or (on all
  four real reports) after it. On those reports the pcap actually starts 1.7 to 3.2 seconds after
  `info.started`, estimated by pairing the sample's DNS lookup with its UDP/53 flow, so flows sit up to
  about 3 seconds early. The pairing is not reliable in general (CAPE reuses source ports, so some
  queries have no UDP flow), which is why it is not used.
- **Attribution.** `process.*` is added only on an exact match against the capemon-derived events of the
  same report: a `dns-query` whose name equals (case-insensitive, trailing dot ignored) a
  `getaddrinfo`/`DnsQuery` event's name, a flow whose destination ip and port equal a `connect` event's,
  an `http-request` whose `url.full` equals an `InternetOpenUrl` event's. If two different processes
  match, or none does, nothing is attributed. The capemon event is listed in `related.events`. Residual
  risk: capemon only sees monitored processes, so a flow by an unmonitored process to an endpoint the
  sample also contacted would be attributed to the sample.
- **Coupling.** The network normaliser runs `CapemonNormalizer` through its public `normalise` and
  reads the derived events it needs: no shared state and no required order between normalisers, at the
  price of deriving capemon events twice per ingest.

#### `cape-signatures`

One `event.kind: alert` event (`event.action: signature-matched`, `event.dataset: cape.signature`,
`event.category: malware`) per entry of `signatures`; an entry without a name is skipped.

- `rule.name`, `rule.description`, `rule.ruleset: cape`, `rule.reference` (when the signature has
  references); `event.severity` is the shared `severity_level` of CAPE's 1-3 scale.
- `threat.technique.id` is the list of ids from every `ttps` entry of the same signature name, in report
  order, deduplicated. One alert per signature, not per id, so a signature stays one row in the
  Detections view. A `ttps` entry naming no signature is dropped.
- `related.events`: each `data` entry `{"type": "call", "pid", "cid"}` becomes the id of the capemon
  `api-call` event of call `cid` of process `pid`, computed by `capemon.api_event_id`, the function
  that names that event. A reference naming no call, or a malformed one, is dropped.
- Time and lane follow the earliest referenced call (by its calibrated timestamp): the alert happens
  then, in the call's semantic lane (`filesystem` to `file`, `registry`, `network`, `process` and
  `threading` to `process`; `capemon.call_lane`). The raw `api` lane is not used. With no resolvable
  call the alert happens at `info.ended` and is in lane `process`.
- `tartarus.detection.match` is the non-call `data` entries as `key: value` pieces (structured values as
  compact JSON), identical pieces once, joined by `; `, cut to 300 characters with an ellipsis.

### Sigma field mapping
Sigma rules are converted with pySigma's **ECS Windows pipeline**, so `Image` →
`process.executable`, `CommandLine` → `process.command_line`, `TargetFilename` → `file.path`,
`TargetObject` → `registry.path`, `DestinationIp` → `destination.ip`, `QueryName` →
`dns.question.name`, and so on. Each event's Sigma `logsource` category comes from its
`event.action`:

| `event.action` | Sigma `logsource.category` |
|---|---|
| `process-created` | `process_creation` |
| `file-created` | `file_event` |
| `reg-*` | `registry_set` / `registry_add` / `registry_delete` |
| `network-connection` | `network_connection` |
| `dns-query` | `dns_query` |
| `image-loaded` | `image_load` |
| `create-remote-thread` / `inject-*` | `create_remote_thread` |
| `process-access` | `process_access` |

## Filesystem artefacts

| Artefact | Location | Exposed as |
|---|---|---|
| Sample | Tartarus sample store (`/data/samples/<sha256>.zip`) | Download |
| Dropped files, payloads, procdumps, memory dump, PCAP, screenshots, report.json | CAPE storage volume `analyses/<task>/…` | `artifact` entries computed from report.json, downloaded as password-protected zips |

Deleting an analysis removes: the CAPE task (apiv2 delete), the OpenSearch index, its
PostgreSQL rows (cascading to tags and notes), and the sample, but only if no other analysis
references it.
