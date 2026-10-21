# Plan: M9, beyond one run

Three independent items from the [finish line](finish-line.md#m9-beyond-one-run): PCAP and memory-image import, a
cross-analysis Search page with IOC pivot, and parallel analyses. New screens (Import tab, Search page) go through the
screenshot Artifact loop (rule 4). Parallel analyses come last because they touch the queue, collector, desktop and
gates at once.

## Status

**Planned 2026-10-21. Nothing built.** Starting point, read from the code:

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

## Delegation (rule 5)

| Piece | Tier |
|---|---|
| Import endpoint, schemas, upload limits, kind column migration | Sonnet (touches runner, ingester, API) |
| Import tab, Search page components following existing patterns | Haiku, then reviewed |
| Search endpoint and IOC pivot on the existing compiler | Sonnet |
| Per-analysis collector/manager/desktop/chip, runner concurrency | Sonnet with notes file (extreme) |
| Tests for already specified behavior, i18n keys, docs | Haiku |

## Done when

Each wave proven on the real stack through the public API (import a PCAP and a memory image and see events/findings;
search an IOC across two analyses; two analyses running at once to `done`), screens approved from Artifacts, docs and
overview updated.
