# Plan: M8, more event sources and Defender's verdict

M8 adds four things to what an analysis can show: Sysmon events, ETW events (DNS, WMI, AMSI, network), a memory dump
with Volatility3 findings, and what Defender did to the sample. Each source is a `Normalizer` behind the one shared
interface; none writes its own copy of the ECS helpers. The only new screen is the Memory view (plus the
"full memory dump" checkbox on the Submit dialog), so it goes through the screenshot Artifact loop (rule 4).

## Status

**Built and proven on the real stack, 2026-10-19.** Planned 2026-10-18 from the [finish line](finish-line.md#m8-more-event-sources-and-defenders-verdict)
and a read of CAPE's own modules. Four spikes ran first (findings and fixtures in [m8-spikes/](m8-spikes/)); the build
followed in waves; two real-run passes on the rebuilt images ([R](m8-spikes/R-findings.md),
[R2](m8-spikes/R2-findings.md)) found eight defects (D1 to D8), all fixed test-first. The three new screens were reviewed from
screenshot Artifacts and **approved by the user** on 2026-10-19: the Overview additions, the Submit dialog's memory
option, and the Artifacts > Memory sub-tab.

What shipped: Sysmon events, Defender's verdict, the full memory dump with Volatility3 findings, and the per-build symbol
file. ETW was dropped from v1 (S2).

| Piece | Where |
|---|---|
| Host-side `event_logs` auxiliary (Sysmon and Defender, one channel table, record-id baseline) | `cape/auxiliary/event_logs.py`, the tighter Sysmon config in `guest/profiles/windows/sysmon-config.xml` |
| Normalisers: Sysmon (noise rule, entity ids shared with capemon), Defender (one classification for events and verdict), Volatility (structural monitor-page rule, one finding per hollowed process) | `backend/app/ingest/{sysmon*,defender*,volatility*}.py`, `windows_events.py` (shared XML reader), `IngestContext.analysis_dir` |
| Summary: `defender` verdict, `hidden_events`, `memory`; normalisers built per ingest | `backend/app/analyses/{defender,memory,memory_step,memory_disk}.py`, `ingester.py` |
| Memory option: `memory_dump`, `keep_memory_dump`, the 409 disk check, `warnings`, the dump deleted after the findings unless kept | `backend/app/analyses/`, `POST /analyses` |
| Volatility3 in the control service (`POST /memory/{task}/analyse`, `DELETE .../dump`), offline, `--pid` from the report | `cape/bin/{volatility,memory_logic}.py`, `cape/build/volatility3.requirements` |
| Symbols: `POST /symbols`, the non-fatal `symbols` step before the snapshot, `missing_symbols` in the analyse answer | `cape/bin/{symbols_logic.py,guest-symbols}`, `guest/profiles/windows/steps/symbols` |
| Screens | Overview (Defender verdict, hidden events, memory status), Submit dialog (memory option), Artifacts > Memory |

Measured on the real stack: the dump is 4.0 GiB and costs 1 to 2 s of the run, the findings about 5 to 10 s; the dump is
deleted afterwards unless kept; a blocked EICAR run now indexes 121 events (it was 1,185) and 0 Sysmon events.

### Still open

- **Submit dialog wording.** It says the dump adds "several minutes of processing"; measured is 5 to 10 s (the minutes
  figure was the S3 spike's CAPE-module cost). Waiting for the user's word before changing approved copy.
- **Two Defender detections of one file** are listed as two threats (real Defender logged the EICAR file twice); collapse by
  threat and path. The `DefenderTamperingRestore` event keeps `severity: critical` although it is no longer an alert.
- **Sysmon score impact** on long interactive runs (S1: 2 of 4 runs differed, n too small); run about ten of each.
- **Not exercised:** the HTTP download of a kept 4 GB dump, an interactive run and a 1200 s run with the new modules, the
  `created: true` answer of `POST /symbols` (the build step made the file first), and any non-INetSim route.
- **For M10:** a clone's first reconfigure once failed with "guest did not start its reboot within 90s" and resumed fine;
  Windows 10 22H2 needs its own symbol file (the `symbols` step makes one per build).
- **For M11:** the cape container is not offline (`tartarus-internal` is not `internal: true`); the symbol fetch is the one
  deliberate outbound connection of the memory pipeline, to a fixed Microsoft host; Volatility writes a cache under
  `/home/cape/.cache` and creates a directory beside its symbols on a failed lookup.

## What the CAPE source already tells us

These came from reading `/opt/CAPEv2` in the image, not from a run, so each is a claim the matching spike must confirm.

| Source | What CAPE does | What is missing here |
|---|---|---|
| Sysmon | The `sysmon` auxiliary (guest side) runs `SMaster64.exe -accepteula -n -i sysmonconfig-export.xml` from the analyzer `bin/` at the start of the run, and at the end runs `wevtutil query-events microsoft-windows-sysmon/operational /format:xml`, uploading `sysmon/sysmon.xml`. With `evtx = no` it also uploads the log as `evtx/evtx.zip`. The `sysmon` processing module turns the XML into `report.json["sysmon"]` with `xmltodict`. | `sysmon_windows = no` and `[sysmon] enabled = no`; `SMaster64.exe` and `sysmonconfig-export.xml` are not in `analyzer/windows/bin/` (Sysmon cannot be redistributed). The guest wizard can already install Sysmon at build time (`sysmon` option, off in `adoption`), so the auxiliary's own install may clash with it. |
| ETW | `dns_etw`, `wmi_etw`, `amsi_etw` and `network_etw` auxiliaries write JSON the matching processing modules read into the report. | All four are `no`. They need `pywintrace` **in the guest**, and the guest has no internet and a 32-bit Python 3.11. |
| Memory | Task option `memory=1` makes CAPE dump the guest's RAM to `memory.dmp`; the `memory` processing module runs Volatility plugins listed in `memory.conf`. | `[memory] enabled = no`, no plugin enabled, **Volatility3 is not installed**, and Volatility3 needs Windows symbol tables (PDB files from Microsoft) which an offline host cannot fetch. |
| Defender | Nothing. CAPE does not read Defender's log. | The whole item. |

The finish line's first guess ("which EVTX library") may not be needed at all: CAPE ships the Sysmon log as XML
and parses it itself. The Sysmon spike decides between reading `report.json["sysmon"]` and parsing the XML or EVTX
in the backend.

## Spikes first (Sonnet, one at a time on the real stack)

CAPE runs one analysis at a time and a build or clone blocks it, so the spikes run in sequence, each with a notes
file under `docs/plans/m8-spikes/` (done, running, next) and a findings file. The planner re-runs every check and
reads the diff before anything is committed (CLAUDE.md rule 5).

| Spike | Question | Check that can fail | Go / no-go |
|---|---|---|---|
| **S1 Sysmon** | Which route gives usable Sysmon events: CAPE's auxiliary (needs the binaries in `analyzer/windows/bin/`, fetched at image build like the guest's media) or the Sysmon the guest already has installed, collected by a Tartarus auxiliary module in CAPE's `custom/` directory? How big is the log for a normal 180 s run and for a noisy one? Does CAPE's own noise (agent, `wevtutil`) need filtering? | A run on a guest built with Sysmon whose `report.json` or `sysmon/sysmon.xml` holds process-create (EID 1), network (3), file (11) and registry (13) events for the sample's process | Go if the events arrive for a default run; the route and the size numbers are the output |
| **S2 ETW** | Can `pywintrace` be installed in an offline guest (wheel on the build media), does it run under the guest's 32-bit Python, and do the four auxiliaries produce events for the benign sample? | A run with the four enabled yields non-empty DNS and network JSON | Drop ETW from v1 if it cannot run without changing the guest's Python or leaving a giveaway; record it |
| **S3 Memory** | How long and how large is a dump for the guest's RAM? Can Volatility3 be installed in the image **with the Windows symbols for the guest's build (10.0.26200) shipped offline**? Do `malfind` and `hollowprocesses` find the injection in the S0b-style injecting sample? | A dump of a run with injection, and a `malfind` hit naming the target process | Go only if symbols work offline; otherwise the memory dump ships as a downloadable artifact without findings and the gap is recorded |
| **S4 Defender** | Which events say Defender detected and removed a file (`Microsoft-Windows-Windows Defender/Operational`: 1116, 1117, 1119, 5007…), and how does a run collect them before the snapshot revert: a Tartarus auxiliary in `custom/`, or the guest agent after the run? | EICAR dropped on a Defender-on guest gives a detection event with the file path; the same on a Defender-off guest gives none | Go if the collection lands in the analysis folder like `sysmon.xml` |

S1 and S4 share one mechanism (a Tartarus auxiliary module that exports an event log at the end of the run), so S4
starts from S1's findings, and the module is written once (rule 3).
