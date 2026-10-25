# Plan: M9, beyond one run

Three independent items from the [finish line](finish-line.md#m9-beyond-one-run): PCAP and memory-image import, a
cross-analysis Search page with IOC pivot, and parallel analyses. New screens (Import tab, Search page) go through the
screenshot Artifact loop (rule 4). Parallel analyses come last because they touch the queue, collector, desktop and
gates at once.

## Status

**Planned 2026-10-21. P1 and P2 ran: both go ([P1](m9-spikes/P1-findings.md), [P2](m9-spikes/P2-findings.md)). Waves 1 and 2 built and proven on the real stack, see [Proof](#proof); wave 3 rewritten from spike P3 ([findings](m9-spikes/P3-findings.md): go with two prerequisites), not started.** Starting point, read from the code:

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
| **P3 Two tasks** | How does CAPE behave with two tasks at once: two guests, two ResultServer streams, one `br`/iptables set, the analysis folders, the scheduler (`max_machines_count`)? Does Tartarus' guest isolation hold for both? | Two benign samples on two clones, both finish with their own events and no cross-talk in the pcaps | **Ran 2026-10-21: go, isolation does not hold between guests** (fixed by 3.0); see [P3](m9-spikes/P3-findings.md) |

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

### Wave 3: parallel analyses (rewritten from spike P3)

[P3](m9-spikes/P3-findings.md) ran on 2026-10-21: **go, with two prerequisites** (3.0 and 3.1b) and a smaller wave than first
planned. CAPE runs two and three tasks at once unchanged; the live manager, hub, WebSocket routes, desktop resolver and
tunnel, finish route and gates are already keyed per analysis. What is single-slot is the runner, four repository
queries and a few messages; the file:line list is in the findings. A new fact the old table did not have: guests can
reach each other (3.0).

| ID | Task | Tier | Depends on | Check that can fail |
|---|---|---|---|---|
| 3.0 | **Guest-to-guest isolation.** `<port isolated='yes'/>` on the interface in `guest/domain/domain.xml.tpl` (libvirt 10.0 accepts it, measured); the control service adds it to every already-defined guest domain that lacks it (the four existing guests), tried first on a throwaway clone for the snapshot metadata; `scripts/verify-isolation.sh` probes through the guest agents | S+ | none | cape unit tests (template, migration on a fake host); on the real stack the script exits 0 with two guests started by snapshot revert (A to B on 8000, 445 and ping all fail, both reach `.1:2042` and `.1:80`) and exits 1 after `bridge link set dev vnetN isolated off` |
| 3.1a | **Runner and repository.** `get_active_analyses` (all), a claim that takes the oldest queued analysis whose guest has no active one (skips a queued row whose guest is busy), `queue_positions` among the analyses waiting for the same guest, `_collecting` becomes a set, every active analysis followed in its own task so one analysis' ingest and memory step never delays another's deadline, `begin_reingest` keeps its gate with a message that no longer says "another" | S+ | none | test with two ready guests and three queued analyses (two on one guest): two start, the third starts when its guest frees, a queued row behind a busy guest does not hold up an idle guest's; a slow ingest of one does not move the other's interactive deadline |
| 3.1b | **`event_logs` waits for the agent.** `start()` polls the agent's `/status` (inside its 90 s budget) before reading the code page and baselines; when a channel still cannot be baselined the module writes `aux/event_logs.json` naming the channel and the reason, and the ingest turns it into a `summary` note so a missing Sysmon export is visible, never silent | S | none | unit test: a fake agent that refuses the first connections still exports; one that never answers leaves the marker and the note; on the real stack the lab3 back-to-back case (task 397 of P3) is repeated three times and each has `sysmon.xml` |
| 3.1c | **Idle-first default guest and cumulative dump room.** `choose_guest` prefers a ready guest with no queued or active analysis when none is requested and the stored default is busy; `check_room_for_dump` counts the RAM of dumps already asked for by queued and active analyses | S | 3.1a | `test_guest_choice.py` and `test_memory_disk.py` cases: default busy and another idle picks the idle one; two dump analyses that fit alone but not together: the second is refused with both numbers |
| 3.2 | **Live manager and collector, two at once.** No code expected (`LiveCollectionManager`, `LiveHub` and `/ws/analyses/{id}/live` are keyed by analysis id): the test that proves it, plus the runner's use of the set from 3.1a | H | none | two collectors on two fixture log directories written incrementally stream independently, counts and process trees apart, stopping one leaves the other; the test fails when `_collectors` is made a single slot |
| 3.3 | **Desktop and admission, two at once.** Resolver and tunnel are per analysis already; add the check that the CAPE task's `machine` is the analysis' guest before a tunnel opens (a reused VNC port can never show another guest), and tests for two resolvers with two ports | H, then reviewed | none | tests: two analyses on two guests resolve to their own ports; a task whose machine differs from the recorded guest is refused (4409); real two-tunnel proof is in 3.6 |
| 3.4 | **Gates for several analyses.** The 409 of `require_no_analysis_needing_a_guest` names the analyses (ids and guests) that hold it; tests with two running and one queued across build, resume, restart, continue, cancel, clone, delete and check; "a guest is being built" refusal re-read for two guests | H | none | tests: every guest-mutating route answers 409 naming both running analyses and 2xx once both ended |
| 3.5a | **Running-analyses data.** `GET /system/queue` (running analyses with guest, filename, elapsed; queued count) and the `queue` push on `/ws/system`, as the backend spec already describes | H | none | endpoint and WebSocket tests; OpenAPI and client regenerated |
| 3.5b | **Frontend.** Header chip `LIVE n` with a list linking to each analysis, queue count, a busy marker per guest in the Submit dialog's picker, Dashboard queue position as "N for lab3"; no global "current live" state | H, then reviewed | 3.5a, 3.1a | store and component tests; screenshot loop (rule 4): none running, one, three, long file names, narrow window |
| 3.7 | **Docs.** `cape-integration.md` ("One analysis at a time stays the rule" and the exclusion section), `backend.md` (reingest, queue, positions, `/system/queue`), `guest-profiles.md` (hardware and isolation), `finish-line.md` | H | 3.1a, 3.0 | the grep gate for the stale sentences finds none |
| 3.8 | **Interactive runs lose the event-log exports** (P3 side finding, not parallel-specific): find why the guest agent's `/execute` hangs after an interactive analyzer ends (even `cmd /c echo hi`; `/status` still answers), fix it or make the module skip fast with the 3.1b marker | S+ | 3.1b | an interactive run ended by `/finish` reports in under 60 s after the analyzer ends and has `sysmon.xml`, solo and in parallel |
| 3.6 | **Real-stack proof** through the public API: two analyses on two guests at once to `done`, a third on a busy guest waits and then runs, header endpoint lists both, a build request while two run is refused naming both, `verify-isolation.sh` green | S+ | 3.0 to 3.5b, 3.8 | solo vs parallel: `process`, `file` and `registry` lane counts equal, `api` and `network` within 10 %, `sysmon.xml` present, PCAPs hold only their guest's IP; `make e2e` green; two desktops open at once each on its own guest |

Launch groups (modules are disjoint inside a group; the planner merges one after the other where two touch `runner.py`
or `event_logs.py`): **A** = 3.0, 3.1a, 3.1b, 3.2, 3.4; **B** = 3.1c, 3.3, 3.5a (after 3.1a); **C** = 3.5b, 3.8, 3.7;
**D** = 3.6. The planner re-runs every `S+` check itself, reads the diff before each commit, and does not ship wave 3
without 3.0 and 3.1b green: with two guests up, a sample can drive the other guest's agent until 3.0 is in.

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

## Wave 3 stack checks

Tasks 3.0, 3.1b and 3.8 run on the real stack on 2026-10-21 (images rebuilt from `32da431`, the cape image once more with the
3.8 fix), through the public API on nginx port 8080; notes and timings in
[T30-31b-38-notes.md](m9-spikes/T30-31b-38-notes.md).

| Check | Result | Numbers |
|---|---|---|
| 3.0 migration | pass, not on a throwaway clone first | the engine ran it by itself when the rebuilt `cape` started, so all four guests (`win`, `lab1`, `lab3`, `lab5`) were migrated before a clone could be tried: log `isolated the network port of <guest>` four times; every persistent domain and the `tartarus-clean` snapshot XML carry `isolated='yes'`, `tartarus-clean` is still the current snapshot, libvirt accepted the redefinition (the `--redefine --current` path is therefore proven on four real guests, not separately on a clone) |
| 3.0 `make verify-isolation GUESTS="lab3 lab5"` | pass | both guests started by snapshot revert; 17 `[ OK ]`, 0 `[FAIL]`, exit 0: A to B on 8000, 445 and ping fail both ways, both reach `.1:2042` and `.1:80` |
| 3.0 revert keeps the isolation | pass | the run above started both guests by `snapshot-revert`; `bridge -d link show` then listed `vnet2` and `vnet3` with `isolated on` |
| 3.0 the check can fail | pass | `bridge link set dev vnet2/vnet3 isolated off` on both running taps: 6 `[FAIL]` (8000, 445, ping, both ways: "-> yes, expected no"), the gateway lines stayed `[ OK ]`, the script exited 1 (`make` printed `Błąd 1`, its own status 2) |
| 3.0 restore | pass | both guests destroyed, script run again: exit 0, 17 `[ OK ]`; no guest left running |
| 3.1b three back-to-back runs on lab3 | pass | three unique copies of the self-test `benign.exe`, `guest=lab3`, `timeout=60`, submitted in the same second (analyses 386 to 388, CAPE tasks 402 to 404): `done` after 79, 69 and 67 s (the next started 2 s after the previous ended); each has `sysmon/sysmon.xml` (7.3, 6.8 and 6.1 MB) and no `aux/event_logs.json`; `summary.missing_exports == []` in all three; 647, 638 and 616 events |
| 3.8 reproduced | yes | interactive run on lab3 ended by `POST /finish` 30 to 40 s in, no other traffic: `done` 161 s after `/finish` (analysis 393), `sysmon.xml` missing, `missing_exports` naming both channels with the 120 s and 30 s read timeouts; four of the five runs made this way hung (159 to 161 s), the fifth was ended before the monitor reached the launcher and exported fine |
| 3.8 cause | found | `analysis.log` of every hung run holds `Monitor config for process 940` and `svchost.exe -k DcomLaunch -p`: the analyzer's `_handle_interop` injects the DCOM launcher service when the monitor in Explorer reports COM activity (the interactive desktop starts Windows Terminal and Edge). After the analyzer exits the monitor stays in that service and every new process the agent starts hangs: from a probe loop during the hang `/execute` of `cmd /c echo hi` timed out at 8 s every time, `/status` timed out at 5 s, `/environ` and `/mktemp` took 5 to 7 s; a Python helper stored and run through `/execpy` started, but its `tasklist`, `wevtutil` and `cmd` children, even with `CREATE_NO_WINDOW`, did not return within 25 s (so it is not console or Windows Terminal delegation). A run without the DCOM injection, the same steps: no hang. The exact mechanism inside the monitor was not traced |
| 3.8 fix | pass | `cape/patches/leave-dcom-launch-alone.py` (image patch, test-first in `cape/tests/test_analyzer_patches.py`, fails the build if CAPE's anchor moved) sets `MONITORED_DCOM` in an interactive analysis, the analyzer's own "already injected" switch. Five runs solo, ended by `/finish` 30 to 60 s in (two with a hot-patched analyzer, three with the rebuilt image): `done` 20 s after `/finish` each, `sysmon.xml` present, no `event_logs.json`, `missing_exports == []`, no `DcomLaunch` line in any `analysis.log`. cape unit suite 1941 passed |
| 3.8 in parallel | not run | needs two interactive runs at once: task 3.6 |

| Finding | State |
|---|---|
| Interactive runs lost the event-log exports and reported 2.5 min late (P3 F7) | fixed by the DCOM patch above; documented in `cape-integration.md` ("The DCOM launcher is not monitored in an interactive analysis"); the cost is that processes COM activation starts in an interactive run are not followed through the launcher |
| One Defender export failed with `Invalid base64-encoded string: number of data characters (13)` in an interactive run (CAPE task 408, run ended 4 s earlier by `/finish`, with my diagnostic helper active in the guest) | not reproduced in the five later runs; recorded, not fixed (an answer cut short is skipped and named in `missing_exports`, so it is visible) |
| The migration cannot be tried on a throwaway clone before the engine touches the real guests: it runs at every `cape` start | recorded; the order the task asked for needs the migration disabled for one start, which no switch offers; it worked on all four |

## Wave 3 proof

Task 3.6, run 2026-10-21 on the real stack (images rebuilt from `eb19828`, nginx on port 8080) through the public API; the
files on the cape side (`sysmon.xml`, PCAPs, `ss` on the QEMU VNC ports) were read with `docker compose exec cape`. The
sample is the self-test `benign.exe` (a unique copy per analysis), route `inetsim`, `timeout=60`, guests pinned. Notes and
timings in [T36-notes.md](m9-spikes/T36-notes.md). Analyses 399 to 414, 430, 431.

| Check | Result | Numbers |
|---|---|---|
| (1) two at once to `done` | pass | pair 1 (401 lab5, 402 lab3) submitted in the same second, both `running` at 18:00:46, done after 83 s and 64 s; pair 2 (405, 406) after 78 s and 68 s; pair 3 (430, 431) after 79 s and 69 s. Solo: lab3 62, 69, 69 s; lab5 80, 76 s |
| (1) `process`, `file`, `registry` equal | pass in 5 of 6 runs | lab3 and lab5 are 24, 3, 12 in every solo and in five of six parallel runs. **One lab5 parallel run (401) had 27, 3, 28**: all the extra events are `MicrosoftEdgeUpdate.exe` (its registry writes, a process-access and a terminate), the guest's own updater, not the sample or the other guest; it did not recur in the 4 later lab5 runs (404 solo; 405, 410, 430 parallel). Recorded as guest background noise, not a parallelism defect |
| (1) `api` within 10 % | pass | lab3 solo 469, 467, 471, parallel 474, 468, 467; lab5 solo 466, 466, parallel 467, 469, 468 (all within 2 %) |
| (1) `network` within 10 % | pass with one outlier | lab5 solo 185, 196, parallel 192, 197, 184 (within 6 %). lab3 solo 108, 106, 120, parallel 107, 129, 105: 129 is 7.5 % over the highest solo but 19 % over the lowest, and three solos alone already span 13 %. The difference is the guest's own flows to the gateway (`.13:port` to `.1:80/443`), nothing foreign |
| (1) `sysmon/sysmon.xml` in both | pass | all 11 runs above, read on disk (tasks 415 to 418, 420 to 424, 444, 445), 5.8 to 9.3 MB. Analysis 431 (lab3) lacks `defender.xml`, named in `missing_exports` and in `aux/event_logs.json` ("Invalid base64-encoded string", the same failure recorded in the 3.8 notes); it ran while `verify-isolation` drove its agent, which is the likely cause, not proven |
| (1) PCAPs hold only their guest | pass | tasks 417, 421, 444 (lab5): IPs `.12` and `.1`, MAC of lab5 and the bridge; tasks 418, 422, 445 (lab3): `.13` and `.1`, MAC of lab3 and the bridge |
| (2) third analysis on a busy guest | pass | 409 (lab3) and 410 (lab5) running, 411 (lab3) submitted: `queued`, position 1 (the API's `queue_position` and `GET /api/system/queue` `position`, which the frontend shows as "1 for lab3"). 412 on idle lab1, submitted after 411, started 4 s later (18:09:09) and was `done` before 411 had started. 411 started 18:10:12, 3 s after 409 ended (18:10:09) |
| (3) `GET /api/system/queue` and the `queue` push | pass | during pair 1: `running` lists 401 (lab5, `par5.exe`, elapsed 10 s) and 402 (lab3, `par3.exe`, 10 s). `/ws/system` client: 13 `queue` messages in pair 1 (connect snapshot empty, then both `starting`, both `running`, 402 `processing`, 401 `ingesting`, empty), none for the `elapsed_s` tick alone; during the Q run 409, 410 and 412 running with 411 in `queued` (position 1) |
| (4) guest build/clone/delete/continue/check while two run | pass | `POST /guests/build`, `/guests/lab1/clone`, `DELETE /guests/zz-nonexistent`, `POST /guests/builds/zz-build/continue`, `POST /guests/lab1/check`: all 409 with "analysis 401 on lab5, analysis 402 on lab3". After both ended the same delete answered 404 (past the gate) and the check 200 |
| (5) `make verify-isolation GUESTS="lab3 lab5"` while both run | pass | with the interactive pair 413/414: exit 0, 17 `[ OK ]`, 0 `[FAIL]`; again with the non-interactive pair 430/431: exit 0, 17 OK. One earlier attempt, 12 s after pair Q started (lab5 still uploading the analyzer), failed for lab5's probe only ("did not finish", banner only; lab3's six lines OK) and did not recur; the script's own header says to stop analyses first. The lab3 to lab5 probes are the isolation proof and passed every time they ran |
| (6) live feed carries only its own events | pass | `/ws/analyses/{id}/live` of 401 and 402, one socket each: every event's `entity_id` starts with its own analysis id, the other run's sample name is in 0 of 9 events on each, process messages name only the own `par3.exe`/`par5.exe` tree; same for interactive 413 and 414 (own `ia.exe`/`ib.exe`); both sockets closed 1000 |
| (7) two interactive runs, two desktops | pass | 413 (lab3, CAPE task 429, `vnc_port=5900`) and 414 (lab5, task 430, `vnc_port=5901`) both `running` with the monitor up; both tunnels (`scripts/lib/live_client.py desktop`) got their first frame in 0.03 s; `ss` in the cape container showed one established guacd connection to each of 5900 and 5901 for the whole time (`virsh vncdisplay`: lab3 `:0`, lab5 `:1`); 17 isolation OKs while both open |
| (7) `/finish` of both | pass | 413 finished at 18:18:15, `done` at 18:18:29 (14 s); 414 at 18:18:23, `done` at 18:18:40 (17 s); both `sysmon.xml` (8.0 and 10.1 MB), `missing_exports == []`; the tunnels closed 1000 at the end of their own runs (guacd 515), 413's 8 s before 414's, so one closing did not touch the other |
| (8) import PCAP while both run | pass | analysis 403 (`p9-run-370-dump.pcap`) submitted while 401 and 402 were `running`: `done` within 14 s, 196 events, the runs were still going |
| (9) `make e2e` | pass on the second run | first run 120 OK, **10 FAIL**; second run 129 OK, 0 FAIL, exit 0 |

| Finding | State |
|---|---|
| `make e2e` steps (b), (c), (d) and (j) submitted two or three analyses with the default guest and expected the later ones to stay `queued`; with wave 3 (and the idle-first default) they run on other guests at once, so the cancel and the "finish a queued analysis" checks answered 409 "no longer queued" | fixed test-first: `options_on_the_guest_of` in `scripts/lib/e2e-api.sh` (test in `scripts/tests/test_e2e_cleanup.sh`), the steps now pin the later analyses to the first one's guest; the second `make e2e` is green |
| `verify-isolation.sh` run while an analysis can start or end on its guests disturbs them: a second run overlapping a queued analysis on lab3 reverted and then destroyed lab3 under CAPE task 428 (agent dead after 4 min, the analysis still ended `done`) and left lab5 running | operator error, not fixed in the script; its header already says to stop analyses first. For "while both run" it is safe only when no analysis can start or end on those guests (both held by interactive runs) |
| Analysis 401 (lab5) had 3 more processes and 16 more registry events from `MicrosoftEdgeUpdate.exe` than any other lab5 run | recorded; the lane-equality check is exact only for the sample's own tree, the guest's background can add to `process` and `registry` |
| 431: one Defender export lost (`Invalid base64-encoded string`) | already recorded in the 3.8 notes; visible in `missing_exports`; seen only while the isolation probe used the same guest agent |

Not covered: more than three analyses at once, two simultaneous memory dumps through Tartarus, the frontend's rendering of
"N for lab3" and the header chip in a browser (the screenshot loop of 3.5b), the desktop shown in a browser for two runs.
