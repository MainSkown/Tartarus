# R2 notes: second real-run pass of M8 on rebuilt images (resume file)

Scratch: /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-proof2/ (df-start, analyses-start, docker-diff-base; api.py etc. reused from ../m8-proof/)
Start: df 395G, docker system df images 107.9GB, volumes 142.8GB. Settings stored changed? (see below)

## Done
- Images verified: running containers = tartarus-{backend,cape,frontend}:latest (ids 7a34e8b6..., 72dcc0a9..., 435df78c...); fixes present (ETW_TIMED_EVENTS, ALERTING_SCOPES, conhost exclusion, _give_to_owner_of, offline URL regex); ISF present.

- Clone m8-proof2 (build b959d6fb3f04b, job 90): succeeded, symbols step 1 s `symbols: ready ... (already present)`, guest ready, self-test passed (analysis 361). df 374G.
- Item 1 (analysis 362, task 359, benign on m8-proof2): done, 653 events, started 15:16:45 finished 15:17:42 (57 s; duration 54 s), hidden {cape-tooling 511, monitor-artefact 6, windows-background 2484}, lane_counts api 470 file 3 network 147 process 21 registry 12. D1 PASS: sysmon DNS 15:17:10.466 vs capemon 15:17:09.460 (1.0 s). D2 PASS: 0 file events with a `\CAPE` folder or CapeOutput (6 dropped as artefact vs 3 before). D3 PASS: roots = benign.exe 8904 > cmd.exe 3836 only.

- Item 2 (analysis 363, task 360, EICAR on m8-proof2): PASS. done in 40 s, 121 events (was 1,185): lane_counts file 5 network 115 process 1, 0 sysmon events, hidden {cape-tooling 386, windows-background 2751}; defender removed/sample_removed/blocked_before_run true; 1116 #1 clamped to start 18:21:49Z `clock: snapshot` (raw 13:14:51); removed_at 18:22:13.975 real (!= detected_at). Observation: Defender wrote TWO detections of the same file this time ({768979E7} and {9B4BFAF1} detected 18:22:04, both quarantined) so summary.defender.threats lists 2 entries with the same path/threat, 3 alert events + 2 quarantine events (real Defender behaviour, S4 saw 1).

- Item 3 (analysis 364, task 361, benign on win): PASS. done, 719 events, score 6.0, 12 signatures identical to analysis 201, hidden {}, summary.defender clean; the DefenderTamperingRestore 1116/1117 are `event.kind: event` (severity field still `critical` on the 1116 event), /detections has only sigma and cape groups: consistent with the verdict.

- Item 4a (analysis 365, task 362, memproof memory, no keep): PASS. started 18:24:21, `processing` at +107 s (timeout 60 + dump), done at +117 s (processing->done 10 s); summary.memory {dump_taken, ok, 4294776995, dump_deleted true}; 4,693 events, 1 memory-finding (MZ header, PING.EXE 8584) + 1 injection-detected, entity id 365:8584@..., roots = memproof.exe > PING.EXE only; sysmon: 5 process events, 0 file events (D2/D3 ok); memory/ files owned cape:cape. DELETE /analyses/365 -> 204 and `analyses/362` GONE entirely (D7 PASS), no root-owned leftovers, no memory.dmp, df 374G.

- Item 4b (analysis 366, task 363, memproof memory+keep): done, dump kept (4294776995, dump_deleted null), /artifacts memory_dump listed; df 370G. KEPT for items 5, 6 (UI), then delete.
- Item 5 PASS (no temp copy): ISF hidden outside the symbols tree -> analyse 200 in 0.37 s, `missing_symbols {guid 24DE61DB3A27C5B383DFF181CB51F7E1, age 1}`; restored, analyse ok again (malfind 6), POST /symbols created:false.

- Item 7a PASS: disk_block_gb 500/warn 600 via PUT /settings -> memory_dump submit 409 `A memory dump needs 504.0 GB free and 369.6 GB is available`, nothing stored (next id was consumed only by my following no-memory submit, 367, accepted 201). SETTINGS RESTORED and verified equal to the original (disk_block_gb 20, disk_warn_gb 50).

- 367 (benign, default) done. Item 6 UI shots taken to scratchpad m8-proof2/*.png (eicar-overview/events/timeline, memory-kept-overview, memory-kept-artifacts-memory, memory-kept-events, win-overview, win-detections, benign-overview, submit-dialog-memory; benign-processes.png is a 404 shot of deleted 362, ignore) and read: Memory sub-tab works (MEMORY (1): dump row 4 GB kept + download, `malfind` group 1 finding PING.EXE 0x202228c0000 RWX MZ header, HIGH); EICAR overview sane (2 threats listed, detected 18:21:49 / removed 18:22:13, 3,137 hidden, lanes process 1 file 5 network 115); events/timeline sane (18:21:49 to 18:22:23); win detections no Defender group; submit dialog text still says "several minutes of processing" (wrong, frontend), Interactive desktop default on (memory run then lasts full timeout). Remarks: header DURATION 41s vs stat tile 34s on EICAR run.

- 366 deleted (204): task folder 363 and its dump gone, df 374G.
- Item 7b PASS: a watcher in the cape container removed analyses/365/memory.dmp at 18:32:32 (after it was complete, before the backend step); analysis 368 (task 365, benign memory_dump) `done`, control route `POST /memory/365/analyse -> 404`, summary.memory {dump_taken false, findings unavailable, error "CAPE took no memory dump: it skips the dump when the storage has less than 50000 MB free" (wording assumes a cause; here I deleted it), dump_bytes null, dump_deleted null}. (Watcher was a one-shot `docker exec -d` shell loop; it exited itself; /tmp file removed.)

- Non-keep memory run 369 (task 366, memproof): done, dump_deleted true; shots memory-deleted-overview/-artifacts-memory/-processes, unavailable-overview (368) read: Memory tab shows "deleted after the findings ... nothing to download" + malfind row; 368 Overview shows `DUMP not taken`, `FINDINGS no findings: there was no dump to read` + error text in orange. 
- NEW DEFECT D8 (found in the 369 processes shot: 3 extra root nodes `SGpllakn.exe`): CAPE's injector runs from `C:\isxu_o0d\bin\...`; the unpack folder charset includes `_` but ANALYZER_PATH allowed only [A-Za-z0-9], so the injector was not tooling and its EID 10 ProcessAccess onto the sample made root nodes. FIXED test first (test_sysmon_noise.py new param test, 2 red then green; backend 3978 passed, ruff/mypy clean) in backend/app/ingest/sysmon_noise.py. Replay of task 366 dir with the fix: only memproof.exe and PING.EXE actors. Backend image rebuild needed for D8 (not proven live).

## Running
- (done) non-keep memory run for the UI (deleted state) + shots of 368 and it; then cleanup (item 8): analyses 361,362?,363..., 364,367,368 + new; guest m8-proof2; samples in storage/binaries (eicar 275a021b, memproof b2aaec0a); no *m8-proof2*; docker diff; compose stop

## Next
- items 1..8 of the brief

## Things to clean / restore
- guest m8-proof2, analyses I create, setting disk_block_gb (only if changed)

## Final state
- Items 1..8 done, findings in R2-findings.md. Cleanup done, stack stopped, df 395G. D8 fixed in backend (rebuild needed). Nothing running.
