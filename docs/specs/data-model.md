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
| `options` | jsonb | `{route, timeout, package, memory_dump, interactive, guest}`. `guest` is the name of the guest the analysis runs on, written resolved when the analysis is queued (no migration: analyses from before guests have no `guest`, and the runner fails one that records none). The name is kept even after the guest is deleted |
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
| `tag` | `id`, `name` (unique, lowercase, `[a-z0-9._-]{1,40}` with at most one `:` between two parts (`tlp:amber`)), `created_at` |
| `tag_link` | `id`, `tag_id` FK, `analysis_id` FK (cascade), `target_type` enum(`analysis`,`process`,`event`), `target_ref` text (`""` for analysis, `pid` for process, `event.id` for event); unique(`tag_id`,`analysis_id`,`target_type`,`target_ref`) |
| `note` | `id`, `analysis_id` FK (cascade), `target_type`, `target_ref`, `body` text (plain text, ≤ 20 000 chars), `created_at`, `updated_at` |

Processes are identified by `pid` within an analysis. Windows reuses PIDs only rarely within one
short run; if reuse is detected, the process key becomes `pid@start_ts`.

### Rules, guest, jobs, settings
| Table | Columns |
|---|---|
| `sigma_rule` | `id` (the Sigma rule UUID), `title`, `level`, `status` (Sigma status), `path`, `content_sha256`, `enabled` bool (default true; the analyst's, kept across reloads), `validity` (`valid`, `invalid` or `unsupported`, a check-constrained text, so the GUI can tell a wrong rule from valid Sigma this engine cannot run), `error` text, `loaded_at`. The file owns every column but `enabled`; a rule whose file is gone is deleted |
| `job` | `id`, `type` enum(`guest_build`,`ingest`,`reingest`,`export_report`,`delete_analysis`), `analysis_id` nullable, `status` enum(`pending`,`running`,`paused`,`done`,`failed`,`interrupted`), `step` text, `progress` 0–100, `log` text (tail), `result` jsonb (a `paused` job holds `{"pause": {"instructions": ...}}`), `created_at`, `updated_at` |
| `setting` | `key` text PK, `value` jsonb: default route, default timeout, default interactive, default guest (a guest name, or null for the first ready guest), disk warn/block thresholds, timeline aggregation threshold |

**There is no guest table.** Guests live in the guest registry on the `guest-images` volume, one
`guest.json` per guest, owned by the guest control service and read through its API (see the
[backend spec](backend.md#guests) and [CAPE integration](cape-integration.md#several-guests)); the libvirt
domain and the CAPE registration are derived from it. Postgres holds only the guest's name, in an analysis's
`options` and in the `default_guest` setting, and the `guest_build` job that follows a build.

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
| `event.module` | keyword | `capemon`, `sysmon`, `etw`, `suricata`, `volatility`, `cape`, `defender`, `sigma`, `yara`, `tartarus` |
| `event.dataset` | keyword | e.g. `capemon.api`, `sysmon.evtx`, `etw.dns`, `suricata.alert`, `cape.signature`, `defender.operational` |
| `event.severity` | integer | 0 info, 1 low, 2 medium, 3 high, 4 critical (alerts only) |
| `event.outcome` | keyword | `success` or `failure`, on action events (Defender); omitted otherwise |
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
| `rule.id`, `rule.name`, `rule.description`, `rule.ruleset` | ruleset ∈ `sigma`, `cape`, `yara`, `suricata`, `defender` |
| `rule.reference` | URLs |
| `threat.technique.id` / `.name`, `threat.tactic.name` | ATT&CK mapping (Sigma tags `attack.t1055` → `T1055`) |
| `related.events` | `event.id`s that triggered it |
| `related.hash`, `related.ip`, `related.hosts` | Pivots |
| `tartarus.detection.match` | What matched, as `field: value` pieces, for the detail view (CAPE: the signature's data; Sigma: the triggering event's matching values, see [Sigma field mapping](#sigma-field-mapping)) |
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
| Sysmon EID 12 / 13 / 14 | n/a | `reg-key-created`, `reg-key-deleted` or `reg-value-deleted` (by `EventType`) / `reg-value-set` / `reg-rename` | registry |
| Sysmon EID 19 / 20 / 21 (WMI filter, consumer, binding) | n/a | `wmi-filter` / `wmi-consumer` / `wmi-binding` | process |
| Sysmon EID 4 / 16 (the service's own state and configuration) | n/a | dropped | |
| ETW DNS / network / WMI / AMSI | n/a | `dns-query` / `network-*` / `wmi-*` / `amsi-scan` | network / network / process / process |
| Suricata flow, http, dns, tls | n/a | `flow` / `http-request` / `dns-query` / `tls-handshake` | network |
| Suricata alert | n/a | detection, `rule.ruleset: suricata` | network |
| CAPE signature | n/a | detection, `rule.ruleset: cape` | lane of the referenced call, or `process` |
| Defender 1116 (malware detected), 1117/1118/1119 (action taken, failed), from the host export `aux/defender.xml` | n/a | detection `malware-detected`, `rule.ruleset: defender`; actions `malware-quarantined`, `malware-removed`, `malware-action-failed` | file |
| YARA hit (file, memory or payload) | n/a | detection, `rule.ruleset: yara` | file or memory |
| Volatility3 findings (malfind, hollowprocesses, …) | n/a | `memory-finding` | memory |

The Sysmon rows are final-phase sources: the guest's Sysmon log is exported at the end of the run to
`sysmon/sysmon.xml`, and there is no live forwarder, so these events arrive with the final report, never in the
live stream (decided 2026-10-17). Which Sysmon events are kept, and how, is [`sysmon`](#sysmon-sysmonsysmonxml).

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

#### `sysmon` (`sysmon/sysmon.xml`)

Reads the log the guest exports (`backend/app/ingest/sysmon*.py`), not `report.json["sysmon"]`: one
streaming parse per pass, never the whole log in memory. `event.module: sysmon`, `event.dataset: sysmon.evtx`,
`phase: final`. `EventData` is read by `Data/@Name` (case-insensitively: EID 8 writes `SourceProcessGuid`, EID 10
`SourceProcessGUID`), never by position. A missing `analysis_dir`, file or unreadable file is no events, no error.

- **Mapping.** The Sysmon rows of the [table above](#mapping-from-sources). EID 12 maps by `EventType`:
  `CreateKey` is `reg-key-created`, `DeleteKey` `reg-key-deleted`, `DeleteValue` `reg-value-deleted`: the names
  the Sigma registry categories already use. EID 7 puts the loaded image in `file.*` (`file.path`, `file.hash.sha256`;
  the catalog has no `dll.*`). EID 8 and 10 name the target in `tartarus.inject.target_pid/_name/_executable`, so a
  Sigma `create_remote_thread` rule reads EID 8 like a capemon `inject-thread`. EID 3 keeps Sysmon's source and
  destination as logged: for an inbound connection (`Initiated` false) the source is the remote end. EID 13's
  `Details` is `registry.data.strings` verbatim (`DWORD (0x00000001)`, what Sigma rules match), with the type
  read from its prefix. `User` is `user.name`/`user.domain`. The WMI events name no process.
- **Time.** `UtcTime` (not `TimeCreated`, the log write time) on the guest clock, plus `guest_clock_offset(report,
  host_registrations)`, the offset capemon's times get. Output is oldest first whatever the file's order (the
  kept events are buffered and sorted); the event id follows the record's position in the file, so a noise rule
  changing does not renumber the survivors.
- **Process identity.** `process.*` comes from the event; `process.entity_id` is built by the same
  `process_fields` as capemon's, from the same `first_seen` start when the pid and image name are one capemon
  monitored, so a Sysmon and a capemon event of one process share an entity id (and `process.start` is then
  capemon's). An unmonitored process takes its EID 1 time as start.
- **Noise.** Windows background is 85 to 99% of a log, so only the sample's events are kept
  (`app/ingest/sysmon_noise.py`, rule in its docstring; reasons are counted on `SysmonNormalizer.dropped`):
  1. the acting process is in the sample's tree: a capemon-monitored process (pid + image name) or any
     descendant by `ParentProcessGuid`; or it names such a process as the **target** (EID 8, 10) and the actor
     is not CAPE's tooling; or it names no (identifiable) process, as the WMI events;
  2. dropped `cape-tooling`: the agent (`pythonw.exe`), `inject-*.exe` and the executables under
     `C:\<8 chars>\bin|dll|data|lib|modules|CAPE\` the injector is renamed to, `PPLinject*`, `wevtutil.exe`, Sysmon's
     binaries, and a process started by one of those. The injector acting on the sample is CAPE injecting its
     monitor, not an injection by the sample;
  3. dropped `monitor-artefact`: inside a sample process, the monitor's own files (anything under the analyzer
     directory, `C:\<pid>.ini`);
  4. dropped `windows-background`: everything else; `sysmon-service` (EID 4, 16) and `unmapped-event` (any other id)
     are counted apart.
  A process the log never saw start is matched by pid alone (a reused pid is kept), and a report with no monitored
  process drops only the tooling, so that a blind capemon still shows the sample.
- **Duplicates with capemon** are not removed here. Both sources emit `process-created`, `network-connection`,
  `dns-query`, `file-created`, `file-deleted` and registry events for one action; tell them apart by
  `event.module` (`sysmon` or `capemon`), and pair them by `process.entity_id`.

#### `defender` (host-collected export)

Reads `aux/defender.xml`: the Defender Operational events that the host-side auxiliary module exports
after the run (S4 spike, `docs/plans/m8-spikes/S4-findings.md`). Final phase, `event.module: defender`,
`event.dataset: defender.operational`, `event.category: [malware, file]`, lane `file`.

- Only 1116 (malware detected) and 1117, 1118, 1119 (action taken, failed) are events. Every other id
  (5007 configuration changes, 2001 update failures, ...) is dropped.
- 1116 is an alert, `event.action: malware-detected`, severity from Severity ID (5 to 4, 4 to 3, 2 to 2,
  1 to 1, else 2). 1117 is an event with `malware-quarantined` (Action ID 2), `malware-removed` (3) or
  `malware-action-taken` (any other id), `event.outcome: success`. 1118 and 1119 are
  `malware-action-failed` with `event.outcome: failure`, severity 3, and `error.code` and `error.message`.
- Records are read by their numeric ids and Detection ID, never by the localised `*Name` values. A closing
  event links to the 1116 with the same Detection ID through `related.events`; one with no such 1116 links
  nothing.
- `tartarus.defender.scope` follows the path. `tooling` (CAPE's own helpers under
  `C:\<8 characters>\bin|dll|lib|data\`) is not an event: it is counted on the normaliser. `sample` (under
  `\Temp\<task id>\`, or the moved copy in `%TEMP%`). `dropped` (written by a process the sample started;
  `process.*` is set). `other` (Windows background, kept as an event).
- `@timestamp` is SystemTime plus the calibrated guest clock offset. A record that predates the run (the
  snapshot's clock) is placed at the analysis start with `tartarus.defender.clock: snapshot`.
- `rule.reference` (the FWLink) and `rule.description` (the category) are set on 1116 only.
- The same classification (`app/ingest/defender_export.py`) gives the analysis `defender` verdict
  (`app/ingest/defender_verdict.py`), so the summary and the events cannot disagree.

Fields this source adds to the catalog: `event.outcome`, `user.name`, `user.domain`, `error.code`,
`error.message`, `tartarus.defender.{detection_id, scope, action_id, category_id, state,
status_code, clock}`.

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
| `create-remote-thread` / `inject-thread` | `create_remote_thread` |
| `process-access` | `process_access` |

A Sigma alert's `event.id` is derived from the analysis, the rule and the triggering event
(`related.events[0]`), so the live collector and the final ingest give the same alert the same
id; the final one replaces the live one in the index. `tartarus.phase` says which wrote it.

A Sigma alert's `tartarus.detection.match` names what matched in the triggering event: for every leaf
of the rule's condition that held, positively, a piece `<catalog field>: <the event's value>`, in
condition order. For a field holding a list (`registry.data.strings`) it is the element or elements
that matched; an `or` lists only the branches that held and a `1 of selection*` the selections that
held; a leaf under a `not` is never listed (it held because something was absent or different), nor
a `null` leaf, while an `exists: true` leaf shows its value. Each value is cut to 120 characters
with an ellipsis; identical pieces appear once, joined by `; `, cut to 300 characters like a CAPE
signature's. A rule that matched but yields no piece shows its condition text instead. The pieces
are computed only for an event that matched, by an explainer compiled beside the rule's predicate
(`app/rules/explain.py`) from the same value tests.

## Filesystem artefacts

| Artefact | Location | Exposed as |
|---|---|---|
| Sample | Tartarus sample store (`/data/samples/<sha256>.zip`) | Download |
| Dropped files, payloads, procdumps, memory dump, PCAP, screenshots, report.json | CAPE storage volume `analyses/<task>/…` | `artifact` entries computed from report.json, downloaded as password-protected zips |

Deleting an analysis removes: the CAPE task (apiv2 delete), the OpenSearch index, its
PostgreSQL rows (cascading to tags and notes), and the sample, but only if no other analysis
references it.
