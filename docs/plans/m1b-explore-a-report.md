# Plan: M1b, explore a finished report

M1a ends with a score and a list of signatures. M1b lets the analyst look *inside* the analysis:
what ran, what it wrote, who it talked to, what was detected. It builds the event index that
M2 (live feed) and M3 (query language, Events and Timeline tabs) sit on, so the index and its field
catalog are designed for those, even though only the views below ship now.

## Status

Planned 2026-10-13, after M1a was verified on the real stack. Nothing built yet.

## Outcome

After a `done` analysis, in the UI:
- **Overview** also shows event counts per lane and the screenshots strip.
- **Processes**: the process tree as a graph (and an indented tree), with a detail panel per process.
- **Network**: DNS, HTTP, TLS, flows, each row attributed to a process where CAPE says which.
- **Artifacts**: dropped files, payloads and configs, process dumps, registry changes, IOCs, with
  downloads (password-protected zip, password `infected`).
- **Detections**: signatures grouped by ruleset with their triggering events, and the ATT&CK matrix.
- Timeline, Events and Notes stay disabled ("arrives with M3 / M4").
- A `report_failed` analysis can be re-ingested from its page.

Out of scope: the query language and Events/Timeline (M3), Sysmon/ETW/Suricata/Volatility
normalisers (M2 and later; CAPE's own `report.json` is the only source here), Sigma and YARA rules
(M4), tags and notes.

## Decisions (made now so no agent has to guess)

1. **Source is `report.json` only.** One normaliser per source, all behind one `Normalizer`
   protocol. M1b implements three over the same report: `capemon` (calls), `cape-network`
   (`network.*`) and `cape-signatures` (signatures and `ttps`). Later sources add classes, not
   changes to these.
2. **Protocol.** `Normalizer.normalise(report: Mapping[str, Any], context: IngestContext) ->
   Iterator[dict[str, Any]]`. `IngestContext` holds `analysis_id` and the analysis's start time.
   Events are plain dicts shaped by the field catalog (decision 3), built through the shared helpers
   in `app/ingest/ecs.py` (event id, process entity id, severity mapping, summary text) which every
   normaliser calls, never copies.
3. **One field catalog** (`app/search/fields.py`): a table of `FieldDefinition(name, type, aliases,
   description, example, lane)`. The OpenSearch index template is *generated* from it; M3's query
   compiler and the autocomplete endpoint will read the same table. The mapping is
   `dynamic: false`, keywords have the `lowercase` normaliser, as in the
   [data model](../specs/data-model.md#opensearch).
4. **Event ids are deterministic** (`sha1(analysis_id, source, source_file, record_index)`), and
   re-ingesting drops the analysis's index first, so ingesting twice gives the same index.
5. **Every raw call is indexed** in the `api` lane; the higher-level event (process, file,
   registry, network, inject) is *derived* alongside it and links back through `related.events`.
   Noisy calls with no derived meaning (`NtClose`, `EventUnregister`, `LdrGetDllHandle`, ...) stay
   `api-call` only. The rules for which call derives what are written down by the capemon task,
   from the real report, in the spec's mapping table.
6. **Time.** capemon call timestamps are **UTC**; `info.started`/`ended` and the machine times are
   the CAPE host's **local** time (verified on analysis 6: calls at 10:12:41, `info.started`
   12:12:18, host UTC+2). Network records carry epoch floats. A test must prove every event of the
   fixture falls inside the analysis window after conversion, because mixing these shifts a whole
   timeline by hours without any error.
7. **Index lifecycle.** Template `tartarus-events` created idempotently at startup; index
   `tartarus-events-<analysis_id>` created at ingest, `refresh_interval` 30 s after ingest, dropped
   when the analysis is deleted or re-ingested.
8. **Ingest is part of `ingesting`.** The runner reads the summary as today, then indexes. If
   indexing fails the analysis ends `report_failed` with the reason (never `done` with a half-empty
   index). `POST /analyses/{id}/reingest` moves a `report_failed` or `done` analysis back to
   `ingesting`; the runner already follows an `ingesting` analysis to CAPE's `reported` status and
   ingests again, so no new runner path is needed.
9. **Artifacts are read from `report.json` on demand** (as the data-model spec says), not indexed.
   IOCs are deduplicated from events plus artifacts.
10. **Detections are events** (`event.kind: alert`, `rule.ruleset: cape`). Each CAPE signature's
    `data` entries of the form `{"type": "call", "pid", "cid"}` become `related.events`, resolved
    through the call's `id` within its process.
11. **Large reports.** The report is parsed once and events are bulk-indexed in chunks of 1000 off
    the event loop (`asyncio.to_thread`); memory is bounded by the parsed report, not by the event
    count. A report of hundreds of MB is a known limit, recorded as a risk, not solved now.
12. **Frontend.** The tab key for Overview stays `summary`. Process graph uses Cytoscape with dagre
    (as the GUI spec says). Each tab loads its own endpoint through one small composable, with the
    same loading / error / empty states as the Dashboard.

## Test fixture

`backend/tests/fixtures/cape/report_full_trimmed.json` is a real report (analysis 6, `benign.exe`,
2 processes, 471 calls, 5 DNS, 2 HTTP, 15 signatures) with the bulky PE strings and imports
removed. Normaliser tests run on it; `report_trimmed.json` stays for the M1a summary tests.

## Waves

Each task is test-first. Tasks marked **care** follow rule 5's extreme-task process: small steps each
ending in a check that can fail, a notes file (done / running / next) in the scratchpad, and the
planner re-runs the checks and reads the diff before committing.

### Wave 1 (parallel, disjoint files)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **B1** | Field catalog and index | Sonnet, **care** | `app/search/fields.py` (catalog for every field in the data model's event document), `app/search/template.py` (template generated from it), `app/search/index.py` (create template, create/drop index, set refresh interval, bulk index in chunks) | Catalog is unique and typed; template built from it has `dynamic: false` and the lowercase normaliser on keywords; testcontainers: create, bulk, search by field, drop |
| **B2** | Normaliser protocol and capemon | Sonnet, **care** | `app/ingest/{protocol,ecs}.py`, `app/ingest/capemon.py` (calls to `api` events plus derived process, file, registry, network and inject events), the written derivation rules | Pure tests on the real fixture: event counts per lane, deterministic ids, process-created derived once per child, timestamps inside the analysis window (decision 6), unknown calls never raise |
| **B6** | Queue position | Sonnet | `queue_position` on `AnalysisRead` (null unless queued; 1 = next) | Repository and API tests |
| **F0** | Review leftovers | Sonnet | Analysis page: a 404 shows "analysis not found" (the store keeps the error code); a tab named in the URL that is not built does not mark itself active; one date formatter for the Dashboard and the analysis page; the delete confirmation says how much disk it frees (`formatFileSize`) | Component and store tests; Playwright cases for 404 and the tab |

### Wave 2

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **B3** | CAPE report normalisers | Sonnet, **care** | `app/ingest/cape_network.py` (DNS, TCP/UDP flows, HTTP with attribution where the report has it), `app/ingest/cape_signatures.py` (alert events, ATT&CK from `ttps`, `related.events` from call refs) | Pure tests on the fixture: signature call refs resolve to real event ids; every `ttps` id appears; DNS/HTTP counts match `network.*` |

### Wave 3

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **B4** | Ingest into the runner | Sonnet, **care** | `app/ingest/ingester.py` (report to normalisers to bulk index, returns lane counts), the runner's `ingesting` step calls it, `event_count` and lane counts in the summary, index dropped on delete, `POST /analyses/{id}/reingest`, template created at startup | Runner tests with a fake ingester (failure to `report_failed`); testcontainers: real fixture to a real index; delete and re-ingest leave one clean index |

Planner then runs a real analysis on the stack and checks the index holds sensible events.

### Wave 4 (parallel)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **B5a** | Event-backed views | Sonnet | `GET /analyses/{id}/processes`, `/processes/{pid}`, `/network`, `/registry` as in the [backend spec](../specs/backend.md#analysis-views), with typed response schemas | API tests over an index loaded from the fixture |
| **B5b** | Detections and artifacts | Sonnet | `/detections`, `/attack`, `/iocs`, `/artifacts`, `/artifacts/{id}/download` (zip, password `infected`), `/artifacts/screenshots/{n}` | Same; the download opens with the password and not without |

Planner then regenerates the API client (`make api-sync`) and shows the queue position on the analysis page (the client has it once B6 is in; a small frontend change with its own test).

### Wave 5 (parallel, then review per screen)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F1** | Processes tab | Sonnet | Cytoscape/dagre graph, indented-tree switch, detail panel, toolbar (fit, hosts, injection, PNG) |
| **F2** | Network tab | Haiku to Sonnet | Sub-tabs DNS, HTTP, TLS, Flows, Alerts, process column, PCAP link |
| **F3** | Artifacts tab | Sonnet | Sub-tabs dropped files, payloads and configs, dumps, registry, IOCs; downloads; copy buttons |
| **F4** | Detections tab and Overview additions | Sonnet | Grouped list, detail, ATT&CK matrix toggle; lane bars and screenshots strip on Overview |

Each tab gets screenshot scenarios (default, loading, empty, error, long values, 600 px) and goes
through the rule 4 review loop, one Artifact per screen.

### Wave 6

`make e2e` gains a check that a finished analysis has a populated index and that each view answers;
the `report_failed` then re-ingest path is exercised against the real stack.

## Risks

| Risk | Handling |
|---|---|
| Derived-event rules are guesses until tested on real reports | Written from the real report; the fixture is real; a second real report (a noisier sample) is run through before M1b is called done |
| Timestamps are in two timezones | Decision 6 and its test |
| A mapping change after data exists | Index is per analysis and re-ingest rebuilds it; no migration |
| Large reports | Decision 11; recorded limit |
| Cytoscape and dagre are new dependencies | Pinned versions, one wrapper component, loaded only on the Processes tab |
| Agents report results optimistically | Planner re-runs every gate and `make e2e` before committing |
