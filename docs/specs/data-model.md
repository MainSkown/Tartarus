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
| `@timestamp` | date (ms) | Guest event time, converted to UTC |
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
| `process.entity_id` | keyword (`<analysis>:<pid>@<start_ts>`) |
| `process.start` | date |
| `process.integrity_level` | keyword (custom) |

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
