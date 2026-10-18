# Plan: M8, more event sources and Defender's verdict

M8 adds four things to what an analysis can show: Sysmon events, ETW events (DNS, WMI, AMSI, network), a memory dump
with Volatility3 findings, and what Defender did to the sample. Each source is a `Normalizer` behind the one shared
interface; none writes its own copy of the ECS helpers. The only new screen is the Memory view (plus the
"full memory dump" checkbox on the Submit dialog), so it goes through the screenshot Artifact loop (rule 4).

## Status

Planned 2026-10-18 from the [finish line](finish-line.md#m8-more-event-sources-and-defenders-verdict) and a read of
CAPE's own modules in the `tartarus-cape` image. Nothing built yet.

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

## Waves after the spikes

Tasks are cut along module boundaries; a task that needs more than one spec section is cut wrong. Tiers follow rule 5.

- **Wave A, Sysmon (after S1).** `SysmonNormalizer` (Haiku, a fixture of a real `sysmon.xml` and the mapping table
  already in [data-model](../specs/data-model.md#normalisers)); the auxiliary or config change and the guest option
  default (Sonnet, touches `cape/` and the guest profile); registering it in `default_normalizers()` and a check that
  the Sigma rules for `process_creation`, `network_connection`, `file_event` and `registry_*` now match Sysmon
  events too without double-firing against the capemon-derived ones (Sonnet: a cross-cutting judgment).
- **Wave B, ETW (after S2, if it survives).** `EtwNormalizer` over the four JSON files (Haiku, fixtures), the config
  and guest change (Sonnet).
- **Wave C, Defender (after S4).** `DefenderNormalizer` (Haiku) emitting `malware`-category events and a detection;
  a `defender` verdict on the analysis summary (`detected`, `removed`, the threat name, the file) in the backend
  schema and the Overview tab (Sonnet for the summary field and its definition of "removed", Haiku for the Vue chip,
  which follows the existing badges).
- **Wave D, memory (after S3).** Submit dialog checkbox with the 4 GB and minutes warning and a disk check against
  the existing thresholds, `memory_dump` in `options` (the field already exists), the Volatility install and
  `memory.conf` (Sonnet), `VolatilityNormalizer` with `malfind` and hollowing findings as `memory-finding` events and
  detections (Sonnet: it defines what a finding is), the `memory` lane in the timeline and a Memory view or lane
  filter (Haiku after the first screen is approved; the view itself is Sonnet).
- **Wave E, proof.** An e2e check per source on a real run through the public API, as M6 and M7 did, then
  `make e2e`, `ruff`, `mypy`, `eslint`, `vue-tsc` clean.

## Frontend work and the review loop

The Memory view and the Submit dialog checkbox are the visual parts. Per rule 4 each gets its own screenshot
Artifact covering default, empty (no dump), loading, error, and the long-path and narrow-window cases, reviewed by
the user before the next screen. Every string goes through the i18n catalogue from the start (M7b's lint rule fails
the build on raw text).

## Open for the user

1. **Sysmon binaries.** They cannot be committed. The proposal is to fetch them at guest build time from the ISO
   media folder, as the guest already does for its own copy, so nothing is redistributed. Confirm, or name another
   source.
2. **Symbols for Volatility3.** If offline symbols are the only blocker, the spike may need one online fetch on the
   host to build a symbol cache for Windows 11 25H2; the cache would be a data directory, not a repo file. Allowed?
3. **Order.** The proposal is S1, then S4 (same mechanism), then S3 (largest unknown), then S2 (most likely to be
   dropped), so the sources most likely to ship land first.
