# Plan: M9, beyond one run

Three independent items from the [finish line](finish-line.md#m9-beyond-one-run): PCAP and memory-image import, a
cross-analysis Search page with IOC pivot, and parallel analyses. New screens (Import tab, Search page) go through the
screenshot Artifact loop (rule 4). Parallel analyses come last because they touch the queue, collector, desktop and
gates at once.

## Status

**Planned 2026-10-21. P1 and P2 ran: both go ([P1](m9-spikes/P1-findings.md), [P2](m9-spikes/P2-findings.md)). Waves 1 and 2 built and proven on the real stack, see [Proof](#proof); wave 3 not started.** Starting point, read from the code:

- Events live in one OpenSearch index per analysis (`tartarus-events-{id}`, `search/index.py`); `search_all` already
  queries `tartarus-events-*`, so Search needs no alias migration, only a query path that spans analyses.
- `Runner` (`analyses/runner.py`) claims one analysis at a time; `live/manager.py` holds one collector.
- The network normaliser (`ingest/cape_network.py`) reads CAPE's report; the Volatility step is a control-service call
  per CAPE task (`POST /memory/{task}/analyse`).

## Spikes first (Sonnet, notes file each under `m9-spikes/`)

| Spike | Question | Check that can fail | Go / no-go |
|---|---|---|---|
| **P1 PCAP** | Can CAPE's own network processing (Suricata, DNS/HTTP/TLS extraction) run on an uploaded PCAP with no task and no guest, or must Tartarus run a reduced pipeline itself? | A PCAP from a known run yields the same DNS and connection events as that run's analysis | Go on the cheapest route that matches the run's network events; record the gap otherwise |
| **P2 Memory image** | Can the control service's Volatility step take a standalone image (no CAPE task, `--pid` unknown)? Which images are accepted (raw, `.dmp`, LiME), and how are symbols found for an unknown build? | `malfind` finds the injection in the M8 dump re-uploaded as a file | Go if symbols resolve; otherwise import is limited to images whose build has a symbol file |
| **P3 Two tasks** | How does CAPE behave with two tasks at once: two guests, two ResultServer streams, one `br`/iptables set, the analysis folders, the scheduler (`max_machines_count`)? Does Tartarus' guest isolation hold for both? | Two benign samples on two clones, both finish with their own events and no cross-talk in the pcaps | Go if isolation holds; the failure modes decide wave 3's scope |

P1 and P2 run before wave 1; P3 before wave 3 (waves 1 and 2 do not depend on it).

## Waves (each ends with `make e2e` green)

1. **Import.** `kind: imported` on `Analysis` (no guest, no queue slot for a guest, no CAPE task unless P1 needs one);
   `POST /analyses/import` with size limit and type sniffing; the existing network and Volatility normalisers run on the
   file through the same `Ingester`; Submit dialog gets an Import tab. Backend first, test-first on a fixture PCAP.
2. **Search and IOC pivot.** `POST /search` over `tartarus-events-*` using the one field catalog and query compiler
   (rule 3); results carry the analysis id; `GET /iocs/{type}/{value}/analyses` lists every analysis holding the value;
   Search page reusing the query bar and event table; the IOC lists in the analysis views link to the pivot.
3. **Parallel analyses.** Runner starts one analysis per ready guest; collector, LIVE tab, desktop and header chip
   become per-analysis; build, clone and delete wait for every running analysis; the "analysis refused while a guest is
   built" gate is reviewed for several analyses. Scope fixed by P3.

## Tasks for agents (rule 5)

Models: **H** = Haiku, **S** = Sonnet, **S+** = Sonnet with a notes file (done/running/next) and a check the planner
re-runs. Every task is test-first and ends with `ruff`/`mypy` or `eslint`/`vue-tsc` clean. Tasks in one launch group
have no dependency on each other and start in one message. Each brief carries only the spec sections it names.

### Wave 1: import (P1 and P2 findings are the input)

| ID | Task | Tier | Depends on | Check that can fail |
|---|---|---|---|---|
| 1.1 | `Analysis.kind` (`run`, `imported`) and optional guest: model, Alembic migration, summary and API schemas, `ACTIVE_STATUSES` and listing unaffected for old rows | S | none | migration up/down on a populated DB; old analyses still read as `run` |
| 1.2 | `sniff_import(file) -> pcap, pcapng, memory_image or unsupported` as a pure function (magic bytes, not extension) | H | none | fixtures: the P1 pcap, a pcapng, an ELF core, a garbage file |
| 1.3 | Config and conf edits: `resolve_dns = off`, `max_sample_size` raised, nginx location for a 4 GB memory upload, shared import volume in compose | H | none | `docker compose config` valid; values asserted in a config test |
| 1.4 | Control service all-pids mode: `memory_logic` runs malfind and hollowprocesses in parallel without `--pid`; a garbage image reports "not a memory image", not "no symbols" | S | none | unit test on the P2 fixtures; garbage input answer |
| 1.5 | `POST /analyses/import`: streamed upload, size limits per kind, sniffing (1.2), store the file, create the `imported` analysis (needs 1.1, 1.2) | S | 1.1, 1.2 | 415 on garbage, 413 over the limit, 201 creates a queued analysis without a guest |
| 1.6 | Runner path for `imported` PCAP: submit CAPE `pcap=1` task, `started_at` from the first packet, ingest through the existing `ReportIngester`, no guest slot taken (needs 1.1) | S+ | 1.1, 1.3 | the P1 fixture pcap gives 196 network events; a queued run is not blocked behind it |
| 1.7 | Runner path for imported memory images: hand the file to the control service (1.4), reuse the Volatility normaliser and the symbols step, findings as detections | S+ | 1.1, 1.4, 1.5 | the P2 injecting image yields the PING.EXE malfind detection |
| 1.8 | Import tab on the Submit dialog (file picker, kind hint, size and symbols warnings), message keys, regenerated API client | H | 1.5 | component test; then the screenshot loop below |
| 1.9 | Real-stack proof through the public API: import a PCAP and a memory image, read events and findings; write the results into this plan | S | 1.6, 1.7 | `make e2e` green plus the two imports |

Launch groups: **A** = 1.1, 1.2, 1.3, 1.4 (together); **B** = 1.5, 1.6, 1.7 once A is done (1.6 and 1.7 touch the
runner, so the planner merges them one after the other); **C** = 1.8; **D** = 1.9. The planner reviews the screenshots
of 1.8 (rule 4: states default, file chosen, wrong type, too large, uploading, error).

### Wave 2: Search and IOC pivot (independent of wave 1)

| ID | Task | Tier | Depends on | Check that can fail |
|---|---|---|---|---|
| 2.1 | Cross-analysis search service: the existing query compiler over `tartarus-events-*`, each hit carrying its analysis id from `_index`, cursor paging across indices | S | none | two fixture indices, one query returns both analyses' events in order, paging stable |
| 2.2 | IOC pivot service: for a value of an IOC field (ip, domain, hash, url), the analyses containing it with a hit count | S | none | two indices share one domain; the pivot lists both and not a third |
| 2.3 | `POST /search` and `GET /iocs/{kind}/{value}/analyses` with schemas, following the events endpoints' pattern | H | 2.1, 2.2 | endpoint tests; OpenAPI regenerated |
| 2.4 | Search page: route, nav entry, query bar and event table reused with an analysis column and a link per row | H | 2.3 | component test; screenshot loop |
| 2.5 | IOC link component ("seen in N analyses") used wherever the IOC lists and the detail drawer show a value | H | 2.3 | component test; screenshot loop |
| 2.6 | Real-stack proof: two analyses sharing an IOC, found by Search and by the pivot | S | 2.4, 2.5 | the pivot lists both analyses |

Launch groups: **A** = 2.1, 2.2; **B** = 2.3; **C** = 2.4, 2.5; **D** = 2.6. Waves 1 and 2 can run in parallel (they
share no files except the Submit dialog's neighbours and the router), so group A of each starts together.

### Wave 3: parallel analyses (after spike P3)

| ID | Task | Tier | Depends on | Check that can fail |
|---|---|---|---|---|
| 3.0 | Spike P3 (table above), notes file `m9-spikes/P3-notes.md`; its findings rewrite 3.1 to 3.6 before they start | S+ | none | two analyses on two clones finish with no cross-talk in the pcaps |
| 3.1 | Runner: one analysis per ready guest at the same time; a guest never gets two | S+ | 3.0 | test with two ready guests and three queued analyses |
| 3.2 | Live manager and collector per analysis; the hub and websocket topics keyed by analysis id | S+ | 3.0 | two simulated live runs stream independently |
| 3.3 | Desktop and admission per analysis (resolver, tunnel, interactive options) | S | 3.2 | two desktops open at once, each on its own guest |
| 3.4 | Gates: build, clone and delete wait for every running analysis; "analysis refused while a guest is built" reviewed for several | S+ | 3.1 | build requested while two analyses run waits for both |
| 3.5 | Frontend: header live chip shows the count and a list, LIVE tab and desktop take the analysis id, no global "current live" state left | H, then reviewed | 3.2 | store and component tests; screenshot loop |
| 3.6 | Real-stack proof: two analyses running at once to `done`, then a build waiting for them | S+ | 3.1 to 3.5 | `make e2e` green plus the two-run proof |

3.1 and 3.2 are cut along different modules and start together; 3.3 and 3.4 follow; the planner re-runs every
`S+` check itself and reads the diff before each commit.

## Done when

Each wave proven on the real stack through the public API (import a PCAP and a memory image and see events/findings;
search an IOC across two analyses; two analyses running at once to `done`), screens approved from Artifacts, docs and
overview updated.

## Proof

Tasks 1.9 and 2.6, run 2026-10-21 on the real stack (images rebuilt from `7e4ccf3`, nginx on port 8080) through the public
API only; notes and timings in [PROOF-notes.md](m9-spikes/PROOF-notes.md). Two defects found and fixed on the way
(table below). Screens were not part of this proof: the screenshot loop for the Import tab and the Search page is
separate.

| Check | Result | Numbers |
|---|---|---|
| (i) `POST /analyses/import` of the P1 fixture PCAP | pass | `done` in 6 s, 196 network events (the run's count), `guest` null, CAPE task category `pcap` with no machine |
| (i) garbage files (3 KB random, a text line) | pass | 415 `unsupported_media_type`, nothing kept |
| (ii) memory image through nginx (`/api/analyses/import/memory-image`) | pass | 4,294,776,995 B (the P2 dump of `p9sample.exe` on lab3) uploaded in 14.7 s, 201; scan 67 s; 26 events; `PING.EXE` high Volatility detection (11 `MsMpEng.exe` and 1 `OneDrive.exe` medium); `max_severity` high, `score` null |
| (ii) delete of that analysis | pass | 204; upload and `storage/analyses/900000375/` both gone |
| (iii) benign run still works | pass | analysis 376 on lab3 done (about 85 s), 624 events, score 6.0, `max_severity` high, as the earlier benign runs |
| (iii) import during an active run | pass | PCAP import submitted while the `p9sample.exe` run was `running`: done in 6 s (the run ended 100 s later) |
| (iv) Search across analyses | pass | `POST /search` `dns.question.name:p9-spike-one.example`: 5 events from analyses 373 (run, 3), 372 and 374 (imports, 1 each); after deleting them, 0 |
| (iv) IOC pivot | pass | `GET /iocs/domain/p9-spike-one.example/analyses`: 373 (3), 374 (1), 372 (1); an unknown domain gives `[]` |
| `make e2e` | pass | 129 checks OK, 0 FAIL, exit 0, about 7 minutes (no drills, no desktop) |

| Finding | Fix |
|---|---|
| Imports answered 500 on a fresh stack: the `imports` volume was root's, the backend image never made `/imports` for its user | `backend/Dockerfile` makes and chowns `/imports`; test in `test_stack_config.py`. An existing root-owned volume must be removed once (`docker volume rm tartarus_imports`) |
| Task 1.7 gaps: an image's detections left `max_severity` null; deleting the analysis left `analyses/900000000+id/` behind | `IngestResult.max_alert_severity`, folded with the report's in the one `_finish_done` (runs and images alike, so a run's Sigma or memory detections can now raise its `max_severity`); control service route `DELETE /memory/{task}/findings` (only ids from 900,000,000) called by the delete route, tolerated when it fails |

Not covered: a real Windows-written `MEMORY.DMP`, an image of another build, the Import tab and Search page in a browser
(`make e2e` does not drive them), wave 3. An image's `score` stays null by design (CAPE's malscore has no counterpart).
