# S4 findings: what Defender did to the sample (M8)

Spike on the real stack, 2026-10-18/19. Guest `m8-s4`, a throwaway clone of `lab5` (Defender on, Sysmon on, engine
4.18.25080.5, signatures 1.437.1.0 from 2025-09-17, the guest has no internet); Defender-off reference `lab3`
(untouched, only used to run an analysis). CAPE at the pinned `CAPE_REF`, agent 0.23. No product code was committed
and nothing was staged. All 19 analyses (ids 317 to 335, task ids 305 to 323) and the guest `m8-s4` were deleted, every change inside the
`cape` container was reverted (list at the end), and the stack was stopped as found. Only this file and `S4-notes.md`
are new in the repo.

Samples: the EICAR test file (`eicar.com`, 68 bytes, standard string), the self-test `benign.exe`, and `dropper.exe`
(a small mingw program that joins the two halves of the EICAR string at run time, writes them to
`C:\Users\Public\tt-dropped-eicar.txt` and sleeps 25 s). No real malware; route `inetsim`.

## Verdict

**GO, with a different mechanism than S1.** The Defender channel `Microsoft-Windows-Windows Defender/Operational` is
the source of truth, and **a guest-side auxiliary module cannot collect it**: on a Defender-on guest the analyzer dies
on its first read of the EICAR file, before it starts any auxiliary module (measured, packages `auto`, `exe` and a
failing one). A **host-side CAPE auxiliary module** that asks the guest agent to run `wevtutil` / `Get-WinEvent` in
its `stop()` works in every case tried (analyzer crash, analyzer exception, normal run) and lands the export in the
analysis folder as `aux/defender.xml`. It also replaces S1's Sysmon module, and a record-id baseline replaces the
clear-at-start, which is wrong for Defender (it erases the sample's own detection).

What an analyst sees today for an EICAR run on a Defender-on guest: **status `done`, no error text, 0 processes,
score 0.0, 10 s, 53 events that are all background network (51 TCP)**. Defender blocked the file when CAPE copied it
into the guest, the analyzer crashed on its first read of it (the traceback is only in `analysis.log`; CAPE's own
`debug.errors` is empty), CAPE called the task "completed successfully", and Defender quarantined the file about 13 s
later, after the analysis had already ended.

Two things the verdict logic must handle: (1) **every** Defender-on run has a detection of CAPE's own tool
(`HackTool:Win32/PDump.A` on `C:\<8 chars>\bin\PPLinject.exe`, quarantined), so "any 1116" is wrong and the tooling
must be excluded; (2) the sample's detection is **stamped with the snapshot's clock**, not the run's (below).

## Method

`run.py` (public API only: multipart `POST /api/analyses`, polling, collect from the cape container; copied from S1 and
extended to copy `aux/` and `sysmon/`) submitted each run. The guest was cloned through `POST /api/guests/lab5/clone`
(`{"name":"m8-s4"}`); the first clone failed in `reconfigure` ("the guest did not start its reboot within 90s") and
`POST /api/guests/builds/<id>/resume` finished it, self-test passed (a Defender-on `benign.exe` run, analysis 317).
Temporary modules were copied into the running container (`docker cp`) with `supervisorctl restart cape cape-processor`.
Defender events were read with `evsum.py` (ElementTree over `EventData/Data[@Name]`). Timings come from
`/opt/CAPEv2/log/cuckoo.log` (container clock = real UTC) and the module's own log lines.

## Evidence

### 1. The EICAR run today (no module)

| Run | Guest | Package | Result in Tartarus | What the guest did |
|---|---|---|---|---|
| E1 (analysis 318, task 306) | m8-s4 | auto | `done`, error `null`, 53 events (lane `network` only), score 0.0, 0 processes, duration 10 s, 0 signatures | `analysis.log`: `choose_package` -> `open(...\Temp\306\eicar.com)` -> `OSError: [Errno 22] Invalid argument` |
| E3 (analysis 320, task 308) | m8-s4 | exe | `done`, 46 events (network), score 0.0, 0 processes, 10 s | `move_curdir` -> `shutil.move` -> `OSError: [WinError 225] ... plik zawiera wirusa lub potencjalnie niechciane oprogramowanie` (the file contains a virus), then Errno 22 on the fallback copy |
| L1/L2 (analysis 328/335, task 316/323) | **lab3** (Defender off) | auto | `done`, 376-398 events, score 2.3, 1 process, 47-52 s | analyzer picks package `generic`, runs the file |

CAPE side (task 306, `cuckoo.log`): guest started 23:11:36, "Analysis completed successfully" 23:11:45, "Completed
analysis successfully" 23:11:46. CAPE does not fail or time out: the crash is reported by the agent as completion.
Nothing in Tartarus's summary, `report.json["debug"]["errors"]` (empty) or the events says Defender was involved.

When it happens: **Defender acts when CAPE's agent writes the file** (real-time protection: 1116 `Process Name`
`C:\Python311\pythonw.exe` = the agent, `Path` `...\Temp\<task>\eicar.com`), which is before the analyzer even
starts; the file stays on disk but every open fails with 225 or 22 until the quarantine action (1117, below) about
10 to 13 s after the detection. It does not wait for the sample to be run.

### 2. Which events are written

Channels with "defender" in the guest (`wevtutil el`): `Microsoft-Windows-Windows Defender/Operational` and
`.../WHC`. **WHC is empty** (0 records, checked at run start of one run and exported at the end of three). Only
the Operational channel matters.

Event IDs seen across all runs: **1116** (malware detected), **1117** (action taken), **5007** (configuration
changed: here mostly `SpyNet\LastMAPSFailureTimeString`, the cloud lookup failing offline; 3 to 4 new per detection),
**2001** (signature update failed, `0x80072f8f`, offline, only in the guest's build history). Not seen, because
nothing triggered them: 1118, 1119, 1120, 1015, 1006 to 1008, 5001, 1001, 1002, 1005.

1116 and 1117 carry the same 42 `Data` names, in this order: `Product Name`, `Product Version`, `Detection ID`,
`Detection Time`, `Unused`, `Unused2`, `Threat ID`, `Threat Name`, `Severity ID`, `Severity Name`, `Category ID`,
`Category Name`, `FWLink`, `Status Code`, `Status Description`, `State`, `Source ID`, `Source Name`, `Process Name`,
`Detection User`, `Unused3`, `Path`, `Origin ID`, `Origin Name`, `Execution ID`, `Execution Name`, `Type ID`,
`Type Name`, `Pre Execution Status`, `Action ID`, `Action Name`, `Unused4`, `Error Code`, `Error Description`,
`Unused5`, `Post Clean Status`, `Additional Actions ID`, `Additional Actions String`, `Remediation User`, `Unused6`,
`Security intelligence Version`, `Engine Version`. The names are English; the `*Name` and description **values are
localised** (here Polish: `Severity Name` "Powazny", `Action Name` "Kwarantanna", `Category Name` "Wirus"), so the
normaliser must key on the numeric IDs.

EICAR on the sample (fixture `defender-eicar-sample.xml`), per Detection ID:

| | 1116 (detected) | 1117 (action taken) |
|---|---|---|
| Threat Name / Threat ID | `Virus:DOS/EICAR_Test_File` / 2147519003 | same |
| Severity ID / Category ID | 5 (Severe) / 42 (Virus) | same |
| State / Status Code | 1 / 1 | **2 / 3** |
| Action ID | 9 ("not applicable") | **2 (Quarantine)** |
| Execution ID | 1 (Suspended) | 1 |
| Source ID | 3 ("real-time protection") | 3 |
| Process Name | `C:\Python311\pythonw.exe` (the agent) | same |
| Path | `file:_C:\Users\Alice\AppData\Local\Temp\321\eicar.com` | same |
| Remediation User | `None` | `ZARZADZANIE NT\SYSTEM` |
| Error Code | `0x00000000` | `0x00000000` |

`Detection ID` is the join key between a 1116 and its 1117 (`{GUID}`, the same value). **There is no hash and no
SHA in either event** (1120, which carries hashes, never appeared). **The sample is identified by the path**:
`...\Temp\<CAPE task id>\<sanitised name>`; CAPE's `sanitize_filename` replaces every non-ASCII character with `_`
(a sample uploaded as `zażółć-тест-测试.com` is `za____-____-__.com` in the event), so join on the task id folder,
not on the name. The task id is `cape_task_id` of the Tartarus analysis.

Order and timing (run E11, task 321; all UTC from `cuckoo.log` and the guest log):

| Time | Source | What |
|---|---|---|
| 23:33:45.99 | cuckoo.log | guest started (`Starting analysis on guest`) |
| guest 21:09:42.1 | 1116 | CAPE's `PPLinject.exe` (analyzer zip extracted) |
| guest 21:09:44.9 | 1116 | `Temp\321\eicar.com` (sample copied by the agent) |
| 23:33:45 | analysis.log | `Date set to` (the guest clock jumps here) |
| 23:33:46.1 | analysis.log | analyzer traceback (Errno 22 / 225) |
| 23:33:53.98 | cuckoo.log | `Analysis completed successfully` |
| guest 21:33:59.12 | 1117 x2 | both quarantined (13 s after the clock was set, 5 s after CAPE considered the task done) |
| 23:34:11 | module log | export written (the module waited 16.5 s for the 1117s) |

The guest's `SystemTime` is **2 h behind real UTC** (CAPE writes UTC wall-clock into a UTC+2 guest; the same offset as
S1 found for Sysmon). And the two 1116 are stamped **24 min before the run** (`21:09:4x`, the clock of the
snapshot, resumed a few seconds earlier): the sample is copied before the analyzer sets the clock. In general they are
as old as the snapshot (days or weeks). Only the 1117 (and a dropped-file 1116/1117) carry the run's clock. So the
normaliser cannot order or filter Defender events by time; use record ids (below) and place pre-run events at the
analysis start.

Settle time (1116 to 1117): **10.5 s** in the dropper run (both stamped on the run clock, D1: 21:26:21.43 to
21:26:31.92); the module had to wait 9.8, 14.8, 15.1, 16.5 and **17.5 s** after the end of the run in the five
EICAR runs where the analysis ended in about 8 s. A fixed delay is not enough; the module polls (below).

### 3. Collection

| Question | Result |
|---|---|
| Guest-side module (S1's, in `analyzer/windows/modules/auxiliary/`), EICAR on Defender-on | **No export at all.** E2 (auto) and E3 (exe): `analysis.log` has no "Imported auxiliary module" line; `AUX_ENABLED` is empty because `choose_package` / `move_curdir` run before the auxiliary modules are initialised (`analyzer.py` lines 513 to 520 against 600 to 626) |
| Host-side module (`stop()` of a CAPE host auxiliary, agent `/execute`), EICAR, packages auto and exe (E4 to E11) | **Export arrives**: `aux/defender.xml` with the 1116 and 1117 of the sample |
| Analysis fails inside the analyzer (F1: package `doc`, `CuckooPackageError: Unable to find any WINWORD.EXE`) | Export arrives (13,303 bytes); Tartarus shows `done`, error `null`, 93 events |
| Defender removed the sample early and CAPE ended the run early (E7 to E11) | Export arrives, as long as the module waits for the 1117 (see below) |
| Cleared at start? | **No, must not be.** B2 ran both modules: the guest module's clear (at analyzer start) deleted the `PPLinject.exe` 1116 (record 271) because it was written before the analyzer started; both exports then lacked it. For the EICAR sample the same would delete its 1116. Use a **record-id baseline** read before the sample is uploaded, then export `EventRecordID > baseline` (tested, contiguous: first record = baseline + 1) |
| Records at run start | `m8-s4` snapshot: **33 records** (ids 238 to 270): 21 x 5007 and 12 x 2001, **no detection event** (the clone's `reconfigure` empties the logs). `numberOfLogRecords` 39 at the analyzer's start (33 + the 6 of the upload). Fixture `defender-clean-guest-baseline.xml`. `lab3` (Defender off) baseline last record 166, not inspected. Channel size 1 MB cap (`fileSize` 69,632 at that point) |
| Defender quarantine state | `C:\ProgramData\Microsoft\Windows Defender\Quarantine\{Entries,ResourceData,Resources}` holds the quarantined file's data (141,000 bytes for `PPLinject.exe`) and could be retrieved with the agent's `/retrieve`; not pursued |
| `Get-MpThreatDetection` / `Get-MpThreat` | Not needed. `Get-MpThreatDetection` is **cumulative across runs and across clones** (it listed the build-time `sample-check.bin` detections of 15 and 17 October on a clone whose event log was empty), has the same `DetectionID` (join key), `Resources`, `ThreatStatusID` (3 = quarantined), local-time strings, and nothing the 1116/1117 do not have. `Get-MpThreat` only has threat id, name, `DidThreatExecute`. **The event log is the better source of truth**: bounded per run by a baseline, locale-independent IDs, the process and user. |

Cost of the host module (v4, `fixture/host_event_logs.py.proposed`): `start()` 2.2 s (three agent calls: the newest
record id of each channel, and the guest's ANSI code page); `stop()` on a clean run 5.7 s (Defender poll 2.1 to 4.2 s,
Sysmon 1.4 s for 10 MB); with a detection 16 to 18 s (poll until every 1116 has a 1117/1118/1119 of the same
Detection ID, cap 30 s).

Implementation facts that cost time (so nobody rediscovers them):
- The agent splits `/execute` commands POSIX-style: forward slashes in paths, a literal backslash doubled.
- `wevtutil` writes the guest's **ANSI code page (cp1250 here)** when its output is piped, not UTF-8 and not the OEM
  page (`0xB3` is `ł` in cp1250, `│` in cp852). Decode with the guest's ACP (read from
  `HKLM\SYSTEM\CurrentControlSet\Control\Nls\CodePage` value `ACP`); characters outside the ACP are already `?`.
  S1's module wrote that stream to a file and had the same problem. `Get-WinEvent ... | % ToXml()` with
  `[Console]::OutputEncoding = UTF8` is lossless, but **8 ms per event**: 7,631 Sysmon events took 59 s against 1.4 s for
  `wevtutil` on 9,507. So: PowerShell for Defender (tens of events), `wevtutil` + ACP for Sysmon.
- With a baseline failure (a wrong flag, `/count` instead of `/c`) the module silently exported the whole channel
  (86 MB of Sysmon, 78,725 events, in one run): a missing baseline should skip the export, not widen it.
- The export file should be written even with no events (`<Events>\n</Events>`): that is "export ran, Defender
  had nothing to say" (a Defender-off guest, `defender-off-guest.xml`), as opposed to "no export".
- The unfiltered `Get-WinEvent -FilterXPath '*[System[EventRecordID > N]]' -Oldest` returns oldest first.
- Calling `/execute` from a host auxiliary's `start()` (before the analyzer upload) did not disturb CAPE (14 runs).

### 4. Second cases

| Case | Guest | What the Defender export held |
|---|---|---|
| Benign `benign.exe` (B1, analysis 326, 620 events, score 6.0, 2 processes) | m8-s4 | **Not empty**: 1116 + 1117 for CAPE's own `C:\l62ktxn6\bin\PPLinject.exe` (`HackTool:Win32/PDump.A`, severity 4, category 34, quarantined), plus 12 x 5007. No event about the sample. (`defender-benign-tooling-only.xml`) |
| EICAR on the Defender-off guest (L2) | lab3 | `<Events>\n</Events>`, 0 events; the file runs (1 process, score 2.3) (`defender-off-guest.xml`) |
| EICAR dropped by a sample (D1, `dropper.exe`, analysis 327, 255 events, score 3.0, 1 process) | m8-s4 | the tooling 1116/1117 **plus** a 1116 for `file:_C:\Users\Public\tt-dropped-eicar.txt` with `Process Name` = `C:\Users\Alice\AppData\Local\Temp\dropper.exe` (the sample itself, moved by the analyzer to `%TEMP%`), `Action ID` 9, then a 1117 with `Action ID` 2 10.5 s later; the sample was **not** blocked, kept running and exited normally (`defender-dropped-file.xml`) |

So "verdict" has three subjects: the **sample file** (path under `Temp\<task id>\`, process = the agent), a **dropped
file** (any other path, `Process Name` = the sample's image or one of its tree), and **CAPE's own tooling** (path
under `C:\<8 chars>\bin\` or `\dll\`, process = the agent). Only the first two belong in the analysis verdict; the
third must be recognised and dropped. Every one of the 11 readable Defender-on exports had the tooling detection; it
is also why `lab5`-type guests could never give an export with no detection event. (Removing `PPLinject.exe` from the
analyzer in the image would stop it, if protected-process injection can do without it; not tried.)

## Verdict definition (for the analysis summary)

Inputs: `aux/defender.xml` (all events after the baseline), `cape_task_id`, the guest's `defender` option, the process
count from capemon.

Per event, in `Microsoft-Windows-Windows Defender/Operational`, grouped by `Detection ID`:

- **detection** = an event 1116 (alias 1006 in older engines, unverified). `scope`:
  - `tooling`: `Path` (after stripping `file:_`) matches `^[A-Za-z]:\\[^\\]{8}\\(bin|dll|lib|data)\\` or lies under the
    analyzer root (`Starting analyzer from: C:\xxxxxxxx` in `analysis.log`, exact);
  - `sample`: `Path` contains `\Temp\<cape_task_id>\` (the upload), or equals `%TEMP%\<sanitised sample name>` (the
    moved copy); the process is the agent for the first form;
  - `dropped`: anything else whose `Process Name` is the sample's image, or a process of its tree (from the capemon
    or Sysmon process events);
  - `other`: anything else (Windows background), kept as an event, not in the verdict.
- **action taken** = a 1117 with the same `Detection ID`: `Action ID` 2 = quarantined, 3 = removed (observed only 2;
  3 is from Microsoft's documentation, unverified). **action failed** = 1118 or 1119 with that `Detection ID`
  (1008 in old engines), never seen. A detection with none of these at export time is `pending` (the module waits up to
  30 s, so `pending` means Defender was still working or stuck).
- **Defender detected** = at least one detection of scope `sample` or `dropped`.
- **Defender removed the sample** = a `sample` detection with a 1117 whose `Action ID` is 2 or 3 and no 1118/1119 for
  the same `Detection ID`. "Removed a dropped file" is the same with scope `dropped`.
- **Blocked before it ran** = `sample` detection and `process_count == 0` (the empty run).

Summary object (`analysis.summary.defender`), absent when the guest's Defender is off:

```
defender: {
  status: "clean" | "detected" | "removed" | "failed" | "no_export",
  sample_removed: bool,          // headline: "Defender removed the sample"
  blocked_before_run: bool,      // sample_removed and process_count == 0
  threats: [{
    detection_id, threat_id, name, severity (0..4), category_id, scope: "sample" | "dropped",
    path, process, user, detected_at,
    action: "quarantine" | "remove" | "none", outcome: "removed" | "failed" | "pending",
    removed_at
  }]                             // scope tooling and other are not listed; their count is not needed
}
```
`no_export` = the guest has Defender on but `aux/defender.xml` is missing (agent unreachable, module not enabled, older
analysis). `clean` = the export ran and has no `sample`/`dropped` detection.

## Normaliser mapping (`DefenderNormalizer`, final-phase source, reads `aux/defender.xml`)

One event per 1116/1117/1118/1119 (and per 1006 to 1008 alias); 5007 and 2001 are dropped (24 of the 33 baseline
records; they are noise), except a 5007 whose `New Value` names `DisableRealtimeMonitoring`, `DisableAntiSpyware`
or `Exclusions` and 5001 ("real-time protection disabled"), which a sample may cause: emit those as `defender-config-
changed` (not seen, unverified). Tooling detections are emitted with `tartarus.defender.scope: tooling` and
filtered by the default view, like S1's CAPE-noise.

| ECS field | 1116 | 1117 / 1118 / 1119 |
|---|---|---|
| `event.module`, `event.dataset` | `defender`, `defender.operational` | same |
| `event.kind` | `alert` | `event` |
| `event.category` | `[malware, file]` | `[malware, file]` |
| `event.type` | `[info, indicator]` | `[deletion]` for Action ID 2/3 (success); `[info]` for a failure |
| `event.action` | `malware-detected` | `malware-quarantined` (Action ID 2), `malware-removed` (3), `malware-action-failed` (1118/1119) |
| `event.outcome` | omitted | `success` (1117) / `failure` (1118/1119) |
| `event.severity` | from `Severity ID`: 5 -> 4, 4 -> 3, 2 -> 2, 1 -> 1, else 2 | 0 for success, 3 for failure |
| `event.id` | `sha1(analysis, "defender", file, EventRecordID)` | same |
| `@timestamp` | `SystemTime` + `guest_clock_offset`; **if earlier than the analysis start, the analysis start** (keep the original in `tartarus.raw` and set `tartarus.defender.clock: snapshot`) | same rule (only the pre-run ones need it) |
| `tartarus.lane` | `file` | `file` |
| `rule.id`, `rule.name` | `Threat ID`, `Threat Name` | same |
| `rule.ruleset` | `defender` (add to the data model's list: `sigma`, `cape`, `yara`, `suricata`) | same |
| `rule.reference` | `FWLink` | omitted |
| `rule.description` | `Category Name` (localised; display only) | omitted |
| `file.path`, `file.name`, `file.extension` | `Path` without the `file:_` prefix (other prefixes, `containerfile:_...`, `process:_pid:...`, `webfile:_...`, seen in Defender docs, unverified: keep the raw string in `tartarus.raw`) | same |
| `process.executable`, `process.name` | `Process Name` only when `scope` is `dropped` (when it is the agent, it is not the sample's process: leave `process.*` unset) | same |
| `user.name`, `user.domain` | `Detection User` split on `\` | `Remediation User` |
| `error.code`, `error.message` | omitted | `Error Code`, `Error Description` (1118/1119) |
| `related.events` | omitted | the event id of the 1116 with the same `Detection ID` |
| `tartarus.detection.match` | `path: <Path>; process: <Process Name>` | omitted |
| `tartarus.defender.{detection_id, scope, action_id, severity_id, category_id, state, status_code}` | custom, keyword/long | same |
| `tartarus.summary` | `Defender detected <Threat Name> in <file.name>` | `Defender quarantined <Threat Name> (<file.name>)` |

Security: the XML comes from the guest, where the sample runs as an admin: parse with a safe parser (no DTD or
entities; ElementTree on an `iterparse` with a size cap), treat every value as untrusted text, and never build a path
from it. A sample can disable Defender, clear its log or write confusing file names; the verdict reflects what the log
says, not what happened.

## Recommendation

Changes (all described, none made):

1. **`cape/Dockerfile`:** `COPY` one new host auxiliary module to
   `/opt/CAPEv2/modules/auxiliary/event_logs.py` (owner `cape`), next to the `skip-packaged-apps` patch. Source in the
   repo: `cape/auxiliary/event_logs.py`, from `fixture/host_event_logs.py.proposed` (rename: the config section name
   must equal the file name). It replaces S1's guest-side `event_logs.py`, which is dropped (the guest analyzer is not
   touched at all, no `custom/analyzer` overlay needed).
2. **`cape/conf/auxiliary.conf`:** add `[event_logs]` with `enabled = yes`. Do **not** add anything under
   `[auxiliary_modules]` (that list is the guest-side one), and keep `sysmon_windows = no`.
3. **Module changes before it ships:** a channel table with one line per channel (done in the proposal); skip the
   export when the baseline could not be read; write the file even when it has no events; short per-request timeouts
   (connect 5 s, read 30 s, 120 s only for the Sysmon read) and a total cap on `stop()` so a dead agent cannot hold
   the machine; fix the spike's `S4_POLL_LOG` leftover (not in the proposal); a unit test with a fake agent
   (`requests` mocked) in `cape/tests`.
4. **Guest:** no change. Defender stays an option of the guest; a Defender-on guest needs the CAPE agent on `:8000`
   (always there) and `wevtutil`/PowerShell (Windows built-ins). Sysmon S1 changes still apply to the config; its
   collection moves to this module (`sysmon/sysmon.xml`, same path as S1, so S1's normaliser plan is unchanged).
5. **Backend:** `DefenderNormalizer` as above, registered in `default_normalizers()`; `summary.defender` computed
   after ingest (the process count and tree are needed); the Overview chip "Defender removed the sample before it
   ran" for `blocked_before_run`; the guest's `DEFENDER ON` badge is already in the analysis JSON.
   Fixtures: `defender-eicar-sample.xml`, `defender-dropped-file.xml`, `defender-benign-tooling-only.xml`,
   `defender-off-guest.xml`, `defender-clean-guest-baseline.xml` (the last is the clean-guest events, converted from
   cp1250 to UTF-8).
6. **Docs:** [cape-integration](../../specs/cape-integration.md#defender) "Not run: report what Defender did" becomes
   done; [data-model](../../specs/data-model.md) gains the `defender` ruleset, the lane use and the rows above; the
   open question 5 in tartarus-v1 closes with this verdict definition.

Fixtures (real, trimmed to what the export holds; nothing removed; the generated account `Alice` and machine
`DESKTOP-2YK5XLK` are throwaway) in
`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s4/fixture/`:

| File | Bytes | Events |
|---|---|---|
| `defender-eicar-sample.xml` | 14,639 | 8 (2 x 1116, 2 x 1117, 4 x 5007): sample + tooling, from the module (UTF-8) |
| `defender-dropped-file.xml` | 22,651 | 16: tooling + a dropped EICAR file with `Process Name` = the sample |
| `defender-benign-tooling-only.xml` | 17,299 | 14: only the tooling detection |
| `defender-off-guest.xml` | 21 | 0 (`<Events>\n</Events>`) |
| `defender-clean-guest-baseline.xml` | 44,036 | 33 (21 x 5007, 12 x 2001), records 238 to 270 |
| `host_event_logs.py.proposed` | 4,934 | the module as last tested |

## Not verified

- Anything with real malware: 1118, 1119, 1120 (hashes), 1015 (suspicious behaviour), 1006 to 1008, 5001, 1001, 1002,
  1005, `Action ID` other than 2 and 9, `Source ID` other than 3, `Severity ID` other than 4 and 5, `Path` prefixes
  other than `file:_`. A detection that happens when the sample **runs** (behaviour monitoring) rather than when it is
  written was not triggered; EICAR is caught on write.
- Signatures are from 2025-09-17 and cannot update offline (event 2001 in the baseline); detection of real samples on
  these guests will be weaker than on a connected machine. The cloud lookup fails (5007 `LastMAPSFailureTimeString`).
- The module with an unreachable agent or a hung guest (timeouts as in the spike are 120 s per request), with an
  interactive run, with an END RUN, with a 1200 s run, and with a CAPE-level task failure (`failed_analysis`) rather
  than an analyzer failure; the code path is a `finally`, but I did not force one.
- Whether the quarantined `PPLinject.exe` changes capemon's behaviour on protected processes (no difference seen in
  `benign.exe`: score 6.0, same as S1's baseline on `lab3`); whether removing it from the image is safe.
- Other guests (`win`, `lab1`), another UI language (values would be localised in another language; the numeric IDs
  and `Data` names should not be), non-ASCII paths in dropped files (the UTF-8 PowerShell path was exercised with Polish
  account names in Sysmon-sized data via `wevtutil` only, not with a CJK file name in a Defender event; the upload name
  is already ASCII-sanitised by CAPE).
- That `SystemTime` of the 1117 is exactly 2 h behind real UTC on every guest (checked once, by hand, against
  `cuckoo.log`); the normaliser should use the calibrated `guest_clock_offset`.
- A tampering sample (disables Defender, clears the log, deletes the quarantine).
- The clone of `lab5` failed once at `reconfigure` (no agent after the IP change within 90 s) and `resume` fixed it;
  not investigated.
- Size growth: Sysmon export 10 MB for a 20 s run and 86 MB for a whole channel; unchanged from S1's concerns.

## Commands to re-run the checks

```
docker compose up -d                                        # no --build
S=/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-s4
curl -s -X POST localhost:8080/api/guests/lab5/clone -H 'content-type: application/json' -d '{"name":"m8-s4"}'
# if it fails in reconfigure: curl -s -X POST localhost:8080/api/guests/builds/<build_id>/resume
# wait for state ready:  curl -s localhost:8080/api/guests/m8-s4 | python3 -c "import sys,json;print(json.load(sys.stdin)['state'])"

# 1. the empty run, as it is today (no module installed)
cd $S && python3 run.py E1 eicar.com m8-s4 --package auto --timeout 120   # done, 53 events, score 0.0, 0 processes
grep -a "Errno 22\|WinError 225" runs/E1/analysis.log

# 2./3. install the proposed module in the running container (reverted below)
docker cp $S/fixture/host_event_logs.py.proposed tartarus-cape:/opt/CAPEv2/modules/auxiliary/host_event_logs.py
docker exec tartarus-cape sh -c 'chown cape:cape /opt/CAPEv2/modules/auxiliary/host_event_logs.py; mkdir -p /opt/CAPEv2/custom/conf/auxiliary.conf.d; printf "[host_event_logs]\nenabled = yes\n" > /opt/CAPEv2/custom/conf/auxiliary.conf.d/m8-s4.conf; supervisorctl restart cape cape-processor'
sleep 8
python3 run.py E11 eicar.com m8-s4 --package exe --timeout 120
python3 -I evsum.py runs/E11/aux/defender.xml --full 1116,1117           # 2 x 1116, 2 x 1117, 4 x 5007
docker exec tartarus-cape grep host_event_logs /opt/CAPEv2/log/cuckoo.log | tail -6   # baselines, "defender settle", export sizes
# the guest-side module cannot do it: copy the S1 module (m8-s1/overlay/event_logs.py) to analyzer/windows/modules/auxiliary/
#   and add "event_logs = yes" under [auxiliary_modules]: with eicar.com no aux/defender.xml and no "Imported auxiliary module" in analysis.log

# 4. second cases
python3 run.py B1 benign.exe m8-s4 --package exe --timeout 120   # export: only the PPLinject.exe detection
python3 run.py D1 dropper.exe m8-s4 --package exe --timeout 120  # + a 1116 for C:\Users\Public\tt-dropped-eicar.txt
python3 run.py L2 eicar.com lab3 --package auto --timeout 120    # aux/defender.xml is "<Events>\n</Events>"

# fixtures: event counts and ids
for f in $S/fixture/defender-*.xml; do echo $f; python3 -I $S/evsum.py $f | head -1; done

# cleanup (what I did)
for i in $(seq FIRST LAST); do curl -s -o /dev/null -w "%{http_code} " -X DELETE localhost:8080/api/analyses/$i; done
curl -s -X DELETE localhost:8080/api/guests/m8-s4
docker exec tartarus-cape sh -c 'rm -rf /opt/CAPEv2/custom/conf/auxiliary.conf.d /opt/CAPEv2/modules/auxiliary/host_event_logs.py /opt/CAPEv2/modules/auxiliary/__pycache__/host_event_logs.*; supervisorctl restart cape cape-processor'
docker compose stop
```

`run.py` and `evsum.py` are in `$S`; `$S/runs/<label>/` keeps `analysis.json`, `analysis.log`, `timeline.txt`,
`cape-ls.txt`, `facets.json` and the small `aux/` files (the Sysmon exports, 10 to 19 MB each, and `report.json` were
pruned).

## Temporary changes made and how each was reverted

Inside the running `tartarus-cape` container only (the repo was not touched): `custom/conf/auxiliary.conf.d/m8-s4.conf`
(directory created by me; the directory did not exist before), `modules/auxiliary/host_event_logs.py` (plus its
`.pyc`), `analyzer/windows/modules/auxiliary/event_logs.py` (guest-side comparison module), `/tmp/tt-hold`,
`/tmp/aux-original.sha256`. All removed; `sha256sum` of every `analyzer/windows/modules/auxiliary/*.py` identical to the
list taken before; `docker diff tartarus-cape` before and after differs only by run artefacts (`log/process-3xx.log`,
`/tmp/cuckoo-tmp/upload_*`, `__pycache__`). Also removed: the `m8-s4` libvirt and swtpm logs, the `lab3` logs the runs
created, and my two samples from CAPE's `storage/binaries` (`eicar.com`, `dropper.exe`; the `benign.exe` copy is shared
with older analyses and stays). `cape` and `cape-processor` were restarted after the revert, then the stack was
stopped. The libvirt images folder holds `lab1, lab3, lab5, win, win2` only (`win2` was there before and is not a
registered guest); `/var/lib/libvirt/{definitions,nvram,qemu/snapshot,tartarus/guests}/m8-s4*` and the `m8-s4.qcow2`,
`m8-s4-clean.mem` and overlay files are gone.

Disk: `df -h /`: 398G free (78% used) at start and at the end; `docker system df`: images 104.8 GB, volumes 142.8 GB
at start and 142.7 GB at the end, containers 141.9 MB then 145.5 MB (container layer logs, not reverted). Scratchpad
1.4 MB.
