# R findings: M8 real-run proof (Sysmon, Defender, memory) on the real stack

Run 2026-10-19 on the images built from the committed code (no `--build`, no `make up`). Guest `m8-proof` was a
throwaway clone of `lab5` (build `b25f95ebe487c`, job 89); `win` and `lab3` were used only to run analyses. All
checks go through the public API (`http://127.0.0.1:8080/api`) except where a row says "control service". Nothing was
staged or committed. All evidence below is from output seen in this run; "NOT RUN" means not done.

Ids: analysis 352 (clone self-test, CAPE task 349), 353 (task 350, benign on `m8-proof`), 354 (task 351, EICAR on
`m8-proof`), 355 (task 352, EICAR on `lab3`), 356 (task 353, benign on `win`), 357 (task 354, benign, memory), 358
(task 355, `memproof.exe`, memory), 359 (task 356, benign, memory + keep), 360 (task 357, `memproof.exe`, memory + keep,
only to prove the fixes of D3, D6 and D7). Samples: the benign self-test `benign.exe` (copied from the cape image cache,
sha256 `7633a1a2...`), an EICAR file (68 bytes, sha256 `275a021b...`) and `memproof.exe` (own C program, mingw: starts
`PING.EXE -n 1000`, `VirtualAllocEx` RWX, writes an `MZ` buffer with `xor eax,eax; ret`, `CreateRemoteThread`, sleeps).

## Verdict

1. The M8 pipeline works end to end on a real guest: Sysmon export, Defender verdict, memory dump, Volatility findings,
   symbol file made by the clone's `symbols` step. Every headline check passes (EICAR blocked-before-run verdict, the
   injected `PING.EXE` found by `malfind` with ONE T1055 detection, 4.0 GiB dump deleted, adopted guest unaffected).
2. Seven defects found, six fixed test-first (D1, D2, D3, D5, D6, D7), D4 (a blocked-before-run analysis) is NOT fixed:
   it needs a design decision. D1, D2, D5 are in the **backend** image, D3, D6, D7 in the **cape** image: both need a rebuild.
3. The worst remaining defect is D4: an EICAR run that Defender blocks indexes 1,185 events, 1,094 of them Windows
   background stamped two hours before the analysis, and the Defender 1116/1117 times are both clamped to the start.
4. The cost of the new pieces is small: Sysmon + Defender export about 5 s after the run (+ ~2 s at start), the memory
   step about 4 to 5 s, the dump 1 to 2 s.
5. Cleanup done: guest, analyses, dumps, samples gone; ISF kept; `df` 395G before and after; stack stopped.

## Table of checks

| # | Check | Result | Evidence |
|---|---|---|---|
| R0 | Stack up, health ok, guests listed | PASS | `docker compose up -d`; `GET /api/system/health`: postgres, opensearch, cape, guest all `ok`; guests `win`, `lab1`, `lab3`, `lab5` `ready`. `df -h /` 395G free; `docker system df`: images 107.9GB, containers 147MB, volumes 142.7GB |
| R1a | Clone (`POST /guests/lab5/clone`) runs the new `symbols` step and ends `ready` with the self-test passed | PASS | Build `b25f95ebe487c` succeeded (steps preflight, copy, define, reconfigure 2:44, defender-on, **symbols 21 s**, snapshot, register); the first clone did NOT fail at reconfigure. Step log line: `symbols: ready windows/ntkrnlmp-24DE61DB3A27C5B383DFF181CB51F7E11.json.xz (created)`. Guest `ready`, `selftest` "all checks passed" (analysis 352, 5 signals ok, Defender proof ok) |
| R1b | The ISF is the right id | PASS | GUID `24DE61DB3A27C5B383DFF181CB51F7E1` age 1 (file name has the age appended: `...E1` + `1`) = the id the step read from the guest's own `ntoskrnl.exe` = the id Volatility later read from the dump (`missing_symbols` in D6) |
| R1c | File mode and size | PASS | `-rw-r--r-- root root 708324` (0.7 MB) in `/var/lib/libvirt/tartarus/symbols/windows/`, directory 755 |
| R1d | `POST /symbols` second call: `created: false`, no network | PASS | control service, bearer token: `200 {"file": "windows/ntkrnlmp-24DE...E11.json.xz", "created": false}` in 0.09 s (twice, also after the hide/restore test) |
| R1e | `POST /symbols` first call gives `created: true` | NOT RUN | The clone's step made the file first (same `ensure_symbols`); a second Microsoft fetch just to see `created: true` was not made |
| R2a | Benign on the clone: done, `sysmon/sysmon.xml` valid UTF-8 XML `<Events>` | PASS | Analysis 353: `done`, 3,297 events, 3,785,852 B, parsed with ElementTree as UTF-8; Polish text (`ZARZĄDZANIE NT\SYSTEM`) decoded correctly (the ACP decode works). EID 16/4 (Sysmon config change) not in the export. `aux/defender.xml` 15,301 B, 12 events (tooling 1116/1117 + 5007) |
| R2b | Sysmon events indexed, process fields correct, entity ids shared with capemon | PASS | 23 `event.module: sysmon` events (9 process, 9 registry, 4 file, 1 network); pids 5936 `benign.exe`, 3968 `cmd.exe`; `process.entity_id` identical for sysmon and capemon events of both pids |
| R2c | The sample's own events are not lost | PASS (with D2) | Hand count of the XML for pids 5936 and 3968: EID 1 x2, 5 x2, 12 x8, 13 x1, 22 x1, 11 x5, 7 x3, 10 x7. Indexed: all except 3 EID 10 by the injector, 1 EID 7 of the monitor DLL, 1 EID 11 `capemon.yac` (tooling or monitor artefact, correct). 3 monitor files leaked in before the D2 fix (below) |
| R2d | `summary.hidden_events` populated | PASS | `{"cape-tooling": 521, "monitor-artefact": 3, "windows-background": 2750}` (before D2: the replay with the fix gives 6 artefacts) |
| R2e | Times UTC-correct | PASS for EID 1/11/12/13, FAIL for EID 3/22 (D1) | File create `tartarus-benign.txt`: sysmon 14:30:58.337 vs capemon 14:30:58.336; registry set 14:30:58.345 vs .336. DNS (EID 22): indexed 14:28:58.727 vs capemon 14:30:58.445: two minutes early (the clock step). After the fix: 14:30:58.67 |
| R2f | `process-created` of the child appears once in the process tree | PASS | `GET /processes`: `cmd.exe` 3968 one node under `benign.exe` (entity `353:3968@...14:30:58.057Z`). The event list has two `process-created` events for it (capemon and sysmon), by design. Two extra roots `conhost.exe`, `OpenConsole.exe` were a defect (D3) |
| R2g | No rule fires twice for the same action | PASS (weak) | One Sigma alert (`Tartarus Self-Test Registry Marker Written`, capemon's event only) and 12 distinct CAPE signatures. No other Sigma rule matched, so the Sysmon/capemon double-firing guard was not exercised by a real match |
| R2h | Module cost in run time is small | PASS | 353: started 14:30:32, finished 14:31:36 (64 s) against 52 s for an earlier `lab5` benign run (228, no module) and 56 s `duration`. cuckoo.log: Sysmon export 1.2 s, Defender export 3.7 s after "Analysis completed" |
| R2i | `summary.defender` is `clean`, PPLinject not in the events | PASS | `{"status": "clean", "sample_removed": false, "blocked_before_run": false, "threats": []}`; 0 `defender` events; no `PPLinject` text in any event |
| R3a | EICAR on the clone: analysis `done`, `aux/defender.xml` present | PASS | Analysis 354: `done` in 32 s, error null, `analysis.log` has the `OSError: [Errno 22]` traceback, `aux/defender.xml` 14,639 B |
| R3b | `summary.defender` | PASS | `status: removed, sample_removed: true, blocked_before_run: true`, threat `Virus:DOS/EICAR_Test_File`, scope `sample`, action `quarantine`, outcome `removed`, process 0 |
| R3c | Detection event, link, clamp | PASS (see D4 for the times) | 1116 event: `rule.ruleset: defender`, `event.kind: alert`, `rule.name` the threat, `file.path` `C:\Users\Alice\AppData\Local\Temp\351\eicar.com`; the 1117 event's `related.events` = the 1116's id; time 14:34:42Z = analysis start (the raw 1116 is 12:28:35 on the snapshot clock), `tartarus.defender.clock: snapshot` |
| R3d | Lab3 (Defender off): no removal claimed, Overview hides it | PASS | Analysis 355: `guest_badges: ["DEFENDER OFF"]`, `defender` `clean`, `aux/defender.xml` `<Events>\n</Events>` (21 B), sample ran (1 process, score 2.3); the screenshot has no Defender section |
| R4 | Adopted `win` without Sysmon | PASS | Analysis 356: `done`, no `sysmon/sysmon.xml` (empty `sysmon/` dir), no error, 0 sysmon events, `hidden_events {}`; cuckoo.log: `Microsoft-Windows-Sysmon/Operational is not on this guest; nothing to export`; score 6.0 and the same 12 signatures as analysis 201 (earlier `win` run). Side finding D5 on this guest |
| R5a | `memory_dump` accepted with 395 GB free, `warnings []`, options stored; `keep_memory_dump` alone is 422 | PASS | `POST` with `memory_dump: true` (and `timeout 60`): 201, `warnings: []`, options show `memory_dump: true, keep_memory_dump: false`; `keep_memory_dump: true` only: `422` at `["body","options","keep_memory_dump"]` ("can only be set together with memory_dump"). Note: `"memory_dump": "yes"` was coerced to `true` and accepted |
| R5b | CAPE task got `memory=1` as a form field | PASS | CAPE `apiv2/tasks/view/354/`: `"memory": true`, `options: "vnc_port=5900"` (no `memory=1` in the options string) |
| R5c | Run reaches `reported` then `done`; timing | PASS | Analysis 358: guest completed 14:42:21.2, CAPE "Completed analysis" 14:42:28.4, backend `processing` 14:42:30, `ingesting` 14:42:35, `done` 14:42:39: ~18 s from `completed` to `done`, against ~13 s with no dump (353: 14:31:23 -> 14:31:36) |
| R5d | `memory.dmp` appears (4294776995 B), then is deleted; space returned; nothing holds it | PASS | `summary.memory.dump_bytes 4294776995`; `df` 374G during, 374G after (395G at start, 374G with the clone); no `*.dmp` in storage; `ls -l /proc/*/fd | grep -c memory.dmp` = 0; no `still open by` line in the guest-control log (`DELETE /memory/354/dump -> 204`) |
| R5e | `memory/run.json` and `windows.*.json`; Volatility version, symbols, pids | PASS | 358: `volatility: 2.28.2`, `symbols: ntkrnlmp-24DE...E11.json.xz`, `pids [5984, 8796]`, pslist 154 rows, cmdline 154, malfind 6, hollowprocesses 0; per-plugin 0.57 to 0.76 s |
| R5f | `summary.memory` | PASS | `{dump_taken: true, findings: "ok", error: null, dump_bytes: 4294776995, dump_deleted: true}` |
| R5g | malfind finding for the child with `MZ header` + ONE volatility detection T1055 | PASS | Events `memory-finding` (`malfind found an executable private region in PING.EXE (pid 8796) at 0x2116a090000, RWX, MZ header`) and one `injection-detected` alert, `rule.ruleset: volatility`, severity high; `/detections`: `Executable private memory region`, technique T1055 |
| R5h | capemon's own pages are not reported | PASS | `windows.malware.malfind.json` has 6 rows; 5 are RWX pages whose first 8 bytes are a little-endian pointer to the page itself (checked by hand: `00002667fc7f0000` at `0x7ffc67260000`, etc.), at the same addresses in both processes; 1 kept (the `MZ` row). 5 dropped as monitor pages. (The index shows 2 `volatility` events for 1 kept row: the finding and its detection) |
| R5i | Findings carry the same `process.entity_id` as capemon's | PASS | pid 8796: `358:8796@2026-10-19T14:41:18.418Z` in sysmon, capemon and volatility events; `injected_into [8796]` on the sample node |
| R5j | The memory step is cheap | PASS | `analyse` 3.0 to 3.3 s of plugins; `processing` to `done` 9 s (vs 6 s without a dump) |
| R5k | Keep run: dump stays, `/artifacts` lists `memory_dump`, `dump_deleted` null; delete removes the dump | PASS | 359: `dump_deleted: null`; `GET /artifacts` `memory_dump: {name: memory.dmp, size: 4294776995, downloadable: true}`; `DELETE /analyses/359` 204, dump gone, `df` 370G -> 374G. (The task folder was only partly removed: D7) |
| R5l | The 409 disk refusal | NOT RUN | Cannot be reached with 395 GB free without filling the disk; unit-tested only |
| R6a | Hidden ISF: `analyse` answers 200 `no symbols for this Windows build` with `missing_symbols {guid, age}`, fast, no network | PASS after D6 | 200 in 0.38 s, all four plugins `no symbols for this Windows build`, the log says `Not accessing http://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/<GUID>1/ntkrnlmp.pdb in offline mode` (no connection attempted). Before the fix **no `missing_symbols` key (D6)**; with the fix `{"guid": "24DE61DB3A27C5B383DFF181CB51F7E1", "age": 1}` (equal to the real id). My first hide attempt moved the file inside `symbols/`, where Volatility finds an ISF by content, not name: hide it outside the tree |
| R6b | ISF restored | PASS | `mv` back; `POST /symbols` `created: false` 0.085 s; `analyse` again 200, plugins ok |
| R6c | `analyse` on a task with no dump | PASS (control route) | `404 {"error": "no memory dump for this task"}`. The backend mapping to `summary.memory.findings: unavailable` was not provoked live (needs CAPE to take no dump): NOT RUN |
| R6d | Re-ingest keeps `summary.memory`, repeats no analyse | PASS | 359: `POST /reingest` -> `done`, 666 events, `summary.memory` unchanged, `POST /memory/356/analyse` lines in the guest-control log 4 -> 4, `run.json` mtime unchanged |
| R7 | UI with real data (1280 px) | PASS with remarks | Screenshots in `.../scratchpad/m8-proof/`: `eicar-overview.png`, `memory-overview.png`, `memory-events.png`, `memory-kept-overview.png`, `memory-kept-artifacts.png`, `memory-artifacts.png`, `win-overview.png`, `lab3-eicar-overview.png`, `submit-dialog-memory.png`. No console errors. See "UI remarks" |
| R8 | Cleanup | PASS | see the cleanup report |

## Defects

| # | Defect | Where | Status |
|---|---|---|---|
| D1 | Sysmon EID 3 and 22 carry an ETW timestamp in `UtcTime` that does not follow CAPE's clock step: the benign DNS query was indexed at 14:28:58.7, 2 minutes before the sample started (14:30:58.4 in capemon). MsMpEng's EID 3 in the same file: `UtcTime` 12:28:50.6 vs `TimeCreated` 12:30:51.3. The step is the age of the snapshot, so on an older snapshot the error is days | backend | **Fixed**, test first |
| D2 | The monitor's results folder (`Storing results at: C:\ShgRuKILV`) is 6 to 10 random characters (CAPE `analyzer/windows/lib/common/constants.py`: `random_string(6, 10)`), the artefact rule required exactly 8 and a trailing `\`: `C:\ShgRuKILV\CAPE`, `...\CapeOutput.bin` (and `C:\VTroer\...`, `C:\TlHGKUQB\CAPE`) were indexed as the sample's file events (3 per run) | backend | **Fixed**, test first |
| D3 | `conhost.exe` and `OpenConsole.exe` EID 10 (ProcessAccess onto the sample, kept as "target in the sample tree") made two extra root nodes in `GET /processes` beside the sample (pids 3444/8456 etc.) | guest Sysmon config (cape image) | **Fixed** (ProcessAccess exclude), proven live with a temporary copy: tree is `memproof.exe` > `PING.EXE` only |
| D4 | A blocked-before-run analysis (EICAR, 0 monitored processes) keeps the whole Windows background: 1,185 events (866 registry, 139 process, 55 network...), `hidden_events` has only `cape-tooling` 379. Two causes: (a) `NoiseFilter` with `has_sample` false "drops only the tooling" by design; (b) `guest_clock_offset` returns 0 without a monitored process, so all of those events are stamped 12:28 to 12:34, two hours before the analysis (14:34:42), and Defender's 1116 and 1117 are both clamped to the start (`removed_at == detected_at`, although the raw 1117 is 12:34:59.7, i.e. 14:34:59.7 real, inside the run) | backend | **NOT fixed**: needs a design decision (below) |
| D5 | On the adopted `win`, Defender flags `HKLM\SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection\DisableBehaviorMonitoring` (`VirTool:Win32/DefenderTamperingRestore`, scope `other`) on a run: it was emitted as `event.kind: alert`, so `/detections` listed a critical Defender detection of a harmless sample while `summary.defender` said `clean` | backend | **Fixed**: scope `other` is a plain event, only `sample` and `dropped` are alerts |
| D6 | `analyse` with missing symbols never returned `missing_symbols` (the documented path to fixing a guest): the code looked for pdbutil's "symbols can be downloaded later" line, but `vol --offline` logs `Not accessing http://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/<GUID><age>/ntkrnlmp.pdb in offline mode` | cape (`bin/volatility.py`) | **Fixed**, proven live (temporary copy) |
| D7 | `memory/` and its files are written by the root service, so CAPE (user `cape`) could not remove them when the analysis was deleted: the API delete answered 204 but left `analyses/<task>/` (`binary`, `logs/*.bson`, `files/`, `memory/`) behind | cape (`bin/memory_logic.py`) | **Fixed**, proven live (folder fully removed) |

Regression tests (each watched red first):
`cape/tests/test_windows_profile.py::TestSysmon::test_the_console_host_every_sample_gets_is_not_logged_as_accessing_it` (D3),
`cape/tests/test_volatility.py` (the four `missing_symbols` tests, driven by the real log line now in
`cape/tests/fixtures/volatility_output.py`; D6),
`cape/tests/test_memory_logic.py::test_the_results_belong_to_whoever_owns_the_analysis_folder_so_cape_can_delete_it` (D7),
`backend/tests/ingest/test_sysmon.py::test_events_whose_utc_time_does_not_follow_the_clock_step_take_the_log_time` (D1; two
fixture timestamps of EID 3 and 22 moved to the write time, 1.6 s and 1 s later),
`backend/tests/ingest/test_sysmon_noise.py::test_the_monitors_results_folder_is_an_artefact_whatever_its_random_length` (D2),
`backend/tests/ingest/test_defender.py::test_a_detection_of_neither_the_sample_nor_its_files_is_an_event_not_an_alert` (D5).
Suites: backend `uv run pytest tests -q --ignore=tests/integration` 3955 passed; `make test-cape` 1869 passed, 1 skipped;
backend `ruff check`, `ruff format --check`, `mypy app` clean; cape `ruff check` and `ruff format --check` of the Makefile
lists clean. Fix check against real data: the saved analysis dirs of task 350 and 353 replayed through the fixed
normalisers (`scratchpad/m8-proof/replay.py`): DNS 14:30:58.67 (capemon 14:30:58.45), monitor artefacts 3 -> 6,
`DefenderTamperingRestore` is `kind: event`. D1, D2 and D5 were NOT proven in the running backend (its image is the old
one).

### D4, what I would do (not done)

- (b) the offset. Without a monitored process there is no anchor, but the hour-level offset can come from the export:
  the last record of the Sysmon or Defender export is seconds before `info.ended` (here 12:34:49.4 against ended
  14:35:11: 2:00:21 rounds to 2:00 at the existing quarter-hour granularity). A fallback in `guest_clock_offset` for a
  report with no process, fed the latest guest time of the export, would give correct hours (skew of a few seconds
  unknown). That touches both normalisers and `clock.py`.
- (a) the noise policy. When capemon saw nothing, seed the sample tree from Sysmon's own EID 1 whose image name is the
  sample's name (`report.target.file.name`, CAPE runs it as `%TEMP%\<name>`), and drop the rest as
  `windows-background`. A sample that never ran then yields no Sysmon events (a blocked EICAR run would index only the
  Defender events and the network), and a sample that ran with capemon blind is still seen. The current comment in
  `sysmon_noise.py` ("errs towards keeping") records that dropping a real event was judged worse; that judgement needs
  the user.

## Other observations (not defects of the milestone's logic)

- **UI remarks** (served frontend = committed code): the Artifacts tab has no Memory sub-tab and does not list the kept
  `memory_dump` (not merged yet), so a kept dump is only visible in the Overview ("DUMP FILE kept"). The Submit dialog
  says the memory option "Adds about 4.3 GB of disk and several minutes of processing"; measured: the dump costs 1 to 2 s
  of the run and the findings about 5 s, so "several minutes" is wrong (it is the CAPE-module figure of the S3 spike).
  The EICAR Overview banner looks right (blocked-before-run text, threat, scope badge, path) but shows the D4 numbers
  underneath: 1,185 events, 866 registry; "detected 14:34:42, removed 14:34:42". `win`'s Overview says "Defender detected
  nothing" while its Detections tab listed D5's critical alert (before the fix).
- **Event counts**: a 55 s benign run exports 3,297 Sysmon events (3.7 MB): 23 are the sample's, 521 CAPE's tooling and
  2,750 (83%) Windows background (S1 estimated 85 to 99%).
- **Volatility side effects**: a failed lookup makes Volatility create `site-packages/volatility3/symbols/windows/ntkrnlmp.pdb/`
  (the ISF directory is root-owned and not writable for `cape`) and `/home/cape/.cache/volatility3/identifier.cache`; both
  removed after the proof, harmless.
- **CAPE `analyses/latest`** is a symlink to the newest task; after the cleanup it points at a deleted task (357) until the
  next analysis rewrites it.
- **Docs to update**: `docs/specs/cape-integration.md` still says the symbols step and `POST /symbols` are "Not tested
  against a real guest yet"; they now were (not the route's `created: true`). `docs/plans/m8-spikes/Y-notes.md` and
  `V-notes.md` "not done" lists are now done except as listed here.
- **Not run**: R1e, R5l, R6c's backend half, an interactive run, a 1200 s run, the HTTP download of a kept dump, the Memory
  sub-tab, Sigma double-fire against a rule that really matches both Sysmon and capemon events.

## Cleanup report

- Analyses created: 352 to 360, all deleted through the API (204). The 3 task folders left behind by D7 (CAPE tasks 354,
  355, 356: `binary` link, `logs`, `files`, root-owned `memory/`) were removed by hand as root; no `memory.dmp` anywhere in
  `storage` (`find`), no folder with a task id >= 349 in `storage/analyses` (remaining: the 35 older folders and `latest`, 101 MB), my
  two samples (`eicar.com`, `memproof.exe`) removed from `storage/binaries` (the shared `benign.exe` stays), the 9
  `/tmp/cuckoo-tmp/upload_*` folders removed, OpenSearch indices `tartarus-events-35x/36x` gone with the analyses.
- Guest `m8-proof` deleted through the API (204): `find / -iname '*m8-proof*'` in the cape container is empty (its libvirt
  and swtpm logs removed by hand), `images`, `definitions`, `nvram`, `tartarus/guests`, snapshots hold only
  `lab1 lab3 lab5 win (win2)`.
- ISF kept: `/var/lib/libvirt/tartarus/symbols/windows/ntkrnlmp-24DE61DB3A27C5B383DFF181CB51F7E11.json.xz` (708,324 B, in
  the `guest-images` volume).
- Temporary changes inside the cape container: `/usr/local/lib/tartarus/volatility.py`, `memory_logic.py` and
  `profiles/windows/sysmon-config.xml` replaced with the fixed copies for D3, D6, D7, then restored from the saved
  originals (sha256 equal to the saved copies), `guest-control` restarted twice. No other change; `docker diff` against the
  one taken after `up` differs only by run artefacts (logs, `__pycache__`, inetsim post data, `swtpm-localca`, mtime of
  `volatility.py`). The cape and backend images were NOT rebuilt.
- `docker compose stop` done (the stack was down at the start).
- `df -h /`: before 395G free (78%), after 395G free (78%); lowest point during the run 370G (clone + one dump). `docker
  system df`: before images 107.9GB (73.12GB reclaimable), containers 147MB, volumes 142.7GB (29.65GB reclaimable); after
  images 107.9GB (70.9GB), containers 135.3MB, volumes 142.8GB (29.65GB; +0.7 MB: the ISF). At most one memory dump existed
  at any time.

## Files changed

`backend/app/ingest/{defender,sysmon_noise,sysmon_processes}.py`, `backend/tests/ingest/{test_defender,test_sysmon,test_sysmon_noise}.py`,
`cape/bin/{memory_logic,volatility}.py`, `cape/tests/{test_memory_logic,test_volatility,test_windows_profile}.py`,
`cape/tests/fixtures/volatility_output.py`, `guest/profiles/windows/sysmon-config.xml`,
`docs/specs/{cape-integration,data-model}.md`, `docs/plans/m8-spikes/R-notes.md`, this file. Scratch (not in the repo):
`.../scratchpad/m8-proof/` (api.py, shots.mjs, replay.py, screenshots, event dumps).
