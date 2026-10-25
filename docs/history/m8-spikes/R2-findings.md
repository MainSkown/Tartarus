# R2 findings: second real-run pass of M8 on the rebuilt images

Run 2026-10-19 on images rebuilt from c65db42 (backend, cape, frontend), started with `docker compose up -d` (no
`--build`). Nothing was copied into a container this time. Throwaway guest `m8-proof2` (clone of `lab5`, build
`b959d6fb3f04b`, job 90). Nothing staged or committed. Evidence is from output seen in this run.

Analyses (task ids in brackets): 361 [358] clone self-test, 362 [359] benign, 363 [360] EICAR, 364 [361] benign on `win`,
365 [362] memproof memory, 366 [363] memproof memory + keep, 367 [364] benign default, 368 [365] benign memory with the
dump removed by hand, 369 [366] memproof memory.

## Verdict

1. The rebuilt images carry all fixes and the D1 to D7 checks pass on a real guest; D4 (blocked-before-run) is fixed:
   the EICAR run now indexes 121 events instead of 1,185, with a real `removed_at`.
2. One new defect, D8 (found in the screenshot of the memory run): CAPE's injector, running from an unpack folder with an
   underscore (`C:\isxu_o0d\bin\SGpllakn.exe`), was not recognised as tooling and made three extra root nodes in the
   process tree. Fixed test first in the backend; needs a backend rebuild; proven by replaying the real analysis folder
   only (not live).
3. The two refusal paths I could not provoke before now are proven: the 409 disk gate and `findings: unavailable`.
4. Remaining UI nits (frontend, not touched): the Submit dialog still says "several minutes of processing";
   the EICAR run lists two `Virus:DOS/EICAR_Test_File` threats for the same file (real Defender behaviour).
5. Cleanup done, `df` 395G before and after, settings restored, stack stopped.

## Table of checks

| # | Check | Result | Evidence |
|---|---|---|---|
| 0 | Running containers are the new images and carry the fixes | PASS | After `docker compose up -d`: container image ids `7a34e8b6...` (backend), `72dcc0a9...` (cape), `435df78c...` (frontend) = `docker images` `:latest`. In the backend container `ETW_TIMED_EVENTS`, `ALERTING_SCOPES`, `created_children`; in the cape container the Sysmon config has the `conhost.exe` and `OpenConsole.exe` ProcessAccess exclusions, `memory_logic.py` has `_give_to_owner_of`, `volatility.py` has the offline-URL regex; the ISF is in place |
| 1a | Clone with the `symbols` step ends `ready`, self-test passed | PASS | Build `b959d6fb3f04b`: symbols step 1 s, log `symbols: ready windows/ntkrnlmp-24DE61DB3A27C5B383DFF181CB51F7E11.json.xz (already present)` (no fetch); guest `ready`, self-test "all checks passed" (analysis 361) |
| 1b | D1: Sysmon EID 3/22 times near capemon's | PASS | Analysis 362: sysmon DNS 15:17:10.466, capemon DNS 15:17:09.460 (1.0 s; was 2 minutes early) |
| 1c | D2: no monitor results folder leaking as file events | PASS | 0 file events whose path contains `\CAPE` or `CapeOutput` (1 sysmon file event: `tartarus-benign.txt`); `hidden_events.monitor-artefact` 6 (was 3) |
| 1d | D3: no extra conhost/OpenConsole roots | PASS | `GET /processes` of 362: root `benign.exe` 8904 > `cmd.exe` 3836, total 2 |
| 1e | Counts, `hidden_events`, run time | PASS | 653 events (api 470, network 147, process 21, registry 12, file 3), hidden `{cape-tooling 511, monitor-artefact 6, windows-background 2484}`, started 15:16:45 finished 15:17:42 (57 s, `duration` 54 s; 64 s with the module before, 52 s without) |
| 2a | D4: EICAR blocked on the Defender-on clone | PASS | Analysis 363 `done` in 40 s: `status removed`, `sample_removed true`, `blocked_before_run true` |
| 2b | Sysmon events ~0 | PASS | 0 sysmon events (was 1,185); `hidden_events {cape-tooling 386, windows-background 2751}`; `event_count 121`, `lane_counts {file 5, network 115, process 1}` (the 1 process event is CAPE's signature alert) |
| 2c | 1116 at the start on the snapshot clock, 1117 at a real time | PASS | First 1116: `@timestamp` 18:21:49Z = analysis start, raw SystemTime 13:14:51, `tartarus.defender.clock: snapshot`; its 1117 18:22:13.975 real; `threats[0]`: `detected_at 18:21:49.000`, `removed_at 18:22:13.975` (not equal) |
| 2d | Overview, Events, Timeline of the EICAR run look sane | PASS | Screenshots read: banner "Defender removed the sample before it ran", lanes process 1, file 5, network 115, "3,137 background events ... hidden"; events and timeline run 18:21:48.7 to 18:22:23.3 (34.7 s), detection markers on the timeline. Remark: header DURATION 41 s vs the stat tile 34 s |
| 3 | D5 on `win` | PASS | Analysis 364: `done`, score 6.0, 12 signatures identical to analysis 201, `hidden_events {}`, `summary.defender` clean. The `VirTool:Win32/DefenderTamperingRestore` 1116/1117 are `event.kind: event`; `/detections` has only sigma and cape groups (screenshot read). Nit: the 1116 event still has `severity: critical` |
| 4a | Memory run: dump, findings, dump deleted | PASS | 365: `summary.memory {dump_taken true, findings ok, dump_bytes 4294776995, dump_deleted true}`, 1 `memory-finding` (PING.EXE 8584, MZ header) + 1 `injection-detected` (volatility, T1055), entity id `365:8584@...` same as capemon's; `processing` +107 s (timeout 60 + dump) to `done` +117 s: 10 s of processing |
| 4b | D7: delete removes the whole task folder | PASS | Before: `analyses/362/memory/*` all `cape cape`, no file with another owner; `DELETE /analyses/365` 204; `ls analyses/362`: no such file; the folder list equals the start's; no `memory.dmp` |
| 4c | Keep run, then delete | PASS | 366: `dump_deleted null`, `/artifacts memory_dump` 4294776995 B, `df` 370G; `DELETE` 204, folder 363 and the dump gone, `df` 374G |
| 5 | D6: hide the ISF, `missing_symbols` equals the real id (no temporary copy) | PASS | `analyse` 200 in 0.37 s, all four plugins `no symbols for this Windows build`, `missing_symbols {"guid": "24DE61DB3A27C5B383DFF181CB51F7E1", "age": 1}`; file restored, `analyse` ok again (malfind 6 rows), `POST /symbols` `created: false` |
| 6a | Artifacts > MEMORY with findings and a kept dump | PASS | Screenshot of 366: tab `MEMORY (1)`, section MEMORY DUMP "taken, 4 GB / kept", row `memory.dmp` 4 GB with `[DOWNLOAD]`, VOLATILITY3 FINDINGS group `malfind` 1 finding, row HIGH `PING.EXE (8636)` `0x202228c0000` PAGE_EXECUTE_READWRITE `MZ header` |
| 6b | Memory tab after the dump was deleted | PASS | 369: "taken, 4 GB / deleted after the findings", "The dump is not on disk any more, so there is nothing to download.", finding row shown |
| 6c | Overview of the memory run | PASS | 366: MEMORY block `DUMP taken, 4 GB`, `FINDINGS findings read, 2 memory events`, `DUMP FILE kept`; lanes include MEMORY 2; "5,235 background events ... hidden". 368 (no dump): `DUMP not taken`, `FINDINGS no findings: there was no dump to read` + the error text in orange |
| 6d | Submit dialog with the memory option | PASS with remark | `FULL MEMORY DUMP + VOLATILITY` on, `KEEP THE DUMP AFTER THE FINDINGS ARE EXTRACTED` appears. The hint still says "Adds about 4.3 GB of disk and several minutes of processing": measured 1 to 2 s of dump and about 10 s of processing. Also `INTERACTIVE DESKTOP` is on by default (stored setting), which makes a memory run last the whole timeout. No console errors in any capture |
| 6e | Process graph of the memory run | FAIL, fixed (D8) | Screenshot of 369: five nodes, three of them `SGpllakn.exe` (2828, 6952, 7368) as roots beside `memproof.exe > PING.EXE`. See D8 |
| 7a | 409 disk gate | PASS | `PUT /settings` `disk_block_gb 500, disk_warn_gb 600`: `POST /analyses` with `memory_dump: true` -> `409 "A memory dump needs 504.0 GB free and 369.6 GB is available"`, nothing stored (next id used by my following request); a run without memory was accepted (201). Settings restored with `PUT` and `GET` equals the original (`disk_block_gb 20`, `disk_warn_gb 50`) |
| 7b | `summary.memory.findings: unavailable` | PASS | A one-shot loop in the cape container removed `analyses/365/memory.dmp` after it was complete (18:32:32) and before the backend's step: analysis 368 `done`, control route `POST /memory/365/analyse -> 404 (no memory dump for this task)`, `summary.memory {dump_taken false, findings unavailable, error "CAPE took no memory dump: it skips the dump when the storage has less than 50000 MB free", dump_bytes null, dump_deleted null}`. Note the error text assumes a cause (here I removed the file) |
| 8 | Cleanup | PASS | see below |

## Defects

| # | Defect | Status |
|---|---|---|
| D8 | `ANALYZER_PATH` in `backend/app/ingest/sysmon_noise.py` allowed letters and digits only, but the agent's unpack folder also has underscores (`C:\isxu_o0d`; other runs `kvy4dte1`, `yqh8h8gi`). The renamed injector `C:\isxu_o0d\bin\SGpllakn.exe` was therefore not tooling, and its EID 10 ProcessAccess onto the sample created three root nodes in `GET /processes` and the graph (analysis 369; happens in about one run in four) | **Fixed test first** (`test_the_injector_is_tooling_in_an_unpack_folder_with_an_underscore`: two params red, then green), backend 3978 passed, ruff and mypy clean. Replay of the real task folder 366 through the fixed normaliser: process actors are only `memproof.exe` and `PING.EXE`. **Needs a backend image rebuild; not proven live** |

Observations, not defects:

- Real Defender wrote two detections of the EICAR file this time (`{768979E7...}` at the start, `{9B4BFAF1...}` at 18:22:04, both
  quarantined, the second 1116 repeated at 18:22:13.996), so `summary.defender.threats` lists two entries with the same
  threat and path, and the Events tab has 3 `malware-detected` + 2 `malware-quarantined`. S4 saw one. Collapsing by
  path and threat is a possible later refinement.
- The `DefenderTamperingRestore` 1116 event keeps `severity: critical` although it is no longer an alert.
- A kept dump's `[DOWNLOAD]` (a 4 GB AES zip, 76 s to pack in the S3 spike) was not exercised.
- Volatility's identifier cache `/home/cape/.cache/volatility3/identifier.cache` was created by the runs (product behaviour; it
  could not be removed after `docker compose stop`; harmless). The `site-packages/.../symbols/windows/ntkrnlmp.pdb/` directory
  a failed lookup creates was removed.
- `df` read 383G for a moment right after `docker compose stop` and 395G 20 s later (space released by the stopped
  containers).

## Cleanup report

- Analyses 361 to 369 deleted through the API (204 each); `ls analyses` equals the start's list (35 folders and `latest`),
  `du` 101M before and after; no `memory.dmp`; nothing root-owned left by a delete.
- Guest `m8-proof2` deleted through the API; `find / -iname '*m8-proof2*'` in the cape container is empty (its libvirt and
  swtpm logs removed by hand); the libvirt `images`, `definitions`, `nvram`, `tartarus/guests` list only the original guests.
- `storage/binaries`: my `eicar.com` and `memproof.exe` removed (151 files, as at the start); the 9 `cuckoo-tmp/upload_*` folders removed.
- ISF kept: `/var/lib/libvirt/tartarus/symbols/windows/ntkrnlmp-24DE61DB3A27C5B383DFF181CB51F7E11.json.xz` (708,324 B).
- Settings changed and restored: `disk_block_gb` 500 -> 20, `disk_warn_gb` 600 -> 50 (verified equal to the original).
- No temporary file in any container; `docker diff` against the baseline taken after `up` differs only by run artefacts
  (logs, `__pycache__`, inetsim post data, `swtpm-localca`, the Volatility identifier cache). One-shot watcher for 7b was a
  `docker exec -d` shell loop that ended by itself.
- `docker compose stop` done. `df -h /`: before 395G (78%), after 395G (78%); lowest point 370G (clone + one dump).
  `docker system df`: images 107.9GB (70.91GB reclaimable) before and after, containers 135.3MB -> 135.6MB, volumes 142.8GB before and after.
  At most one memory dump existed at any time.

## Files changed in this pass

`backend/app/ingest/sysmon_noise.py`, `backend/tests/ingest/test_sysmon_noise.py` (D8), `docs/history/m8-spikes/R2-notes.md`, this file.
Screenshots and scripts: `/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-proof2/`
(`eicar-*`, `memory-kept-*`, `memory-deleted-*`, `unavailable-overview`, `win-*`, `benign-overview`, `submit-dialog-memory`; `benign-processes.png`
is a 404 page of an already deleted analysis, ignore).
