# R notes: real-run proof of M8 (resume file)

Scratch dir: /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/ce3dfae3-2a04-4e47-b56f-490d4379808e/scratchpad/m8-proof/
Start: df 395G free, docker system df images 107.9GB / volumes 142.7GB (files `df-start.txt`, `dsdf-start.txt`).

## Done
- R0: stack up (docker compose up -d), health ok x4, guests win/lab1/lab3/lab5 ready.

- R1: clone lab5 -> m8-proof, build b25f95ebe487c succeeded (symbols step 21 s, log `symbols: ready windows/ntkrnlmp-24DE61DB3A27C5B383DFF181CB51F7E11.json.xz (created)`), guest ready, self-test passed (analysis 352). ISF 708,324 B mode 644. POST /symbols afterwards: 200 created:false in 0.09 s.
  The step made the file (the first fetch), so the route's `created: true` was NOT separately exercised yet.

- R2: analysis 353 (task 350) benign on m8-proof: done. Checks mostly pass (see R-findings). Candidate defects:
  - D1 Sysmon EID 3/22 `UtcTime` is ETW-derived and does not follow CAPE's clock step: DNS event of benign.exe indexed at 14:28:58.7 vs capemon 14:30:58.4 (2 min early; log write time `TimeCreated` is right). Fix candidate: use TimeCreated for EID 3 and 22 in app/ingest/sysmon_processes.guest_time (backend image rebuild needed).
  - D2 `ANALYZER_PATH` in sysmon_noise.py requires exactly 8 random chars, but the analyzer ROOT (`Storing results at: C:\ShgRuKILV`) is 6 to 10 (constants.py random_string(6, 10)): the monitor's `C:\ShgRuKILV\CAPE` and `CapeOutput.bin` leaked as 3 sample file events (not counted as monitor-artefact).
  - D3 conhost.exe / OpenConsole.exe EID 10 (ProcessAccess onto the sample) kept: they appear as 2 extra root nodes (3444, 8456) in GET /processes. Fix candidate: add them to the ProcessAccess exclude list of guest/profiles/windows/sysmon-config.xml (cape image) or backend.
  - Module cost: started_at->finished_at 64 s for 353 vs 52 s for earlier lab5 run 228 (no module); stop() exports 1.2 s Sysmon + 3.7 s Defender (cuckoo.log).

- R3: 354 EICAR on m8-proof (done; status removed, blocked_before_run, aux/defender.xml present, detection event ok). 355 EICAR on lab3 (clean, badge DEFENDER OFF). Defects: D4 (blocked-before-run: guest_clock_offset=0 -> all 1094 sysmon bg events 2 h early; Defender 1116/1117 both clamped to start, removed_at==detected_at; capemon-blind policy keeps all non-tooling Windows background), D2 also seen on lab3 (`C:\TlHGKUQB\CAPE` dir w/o trailing slash).
- R4: 356 benign on win: done, no sysmon.xml, log `Microsoft-Windows-Sysmon/Operational is not on this guest; nothing to export`, hidden_events {}, same 12 signatures/score 6.0 as analysis 201. D5: win Defender export has a 1116/1117 `VirTool:Win32/DefenderTamperingRestore` (regkeyvalue DisableBehaviorMonitoring policy, scope other) emitted as kind alert, shows as a critical Defender detection in /detections while summary.defender is clean.
- R5: 357 (benign, memory_dump via "yes" coerced to true: ok; ran fully) and 358 (memproof, memory_dump, timeout 60): done, dump 4294776995 deleted, run.json volatility 2.28.2, symbols ntkrnlmp-24DE...json.xz, pids [5984, 8796]; malfind 6 rows -> 1 finding + 1 detection T1055 (5 rows hand-checked as self-pointer monitor pages); entity ids shared; memory step ~4-5 s. D2 seen again with a 6-char root.

- R5b: 359 keep run (benign, memory_dump+keep): dump kept, /artifacts memory_dump size 4294776995, summary.memory.dump_deleted null. R6: hidden ISF (outside symbols tree; my first try left it under symbols/ where Volatility finds it by content) -> analyse 200 in 0.38 s, all four plugins `no symbols for this Windows build`, NO `missing_symbols` key (D6: offline mode logs `Not accessing http://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/<GUID><age>/ntkrnlmp.pdb in offline mode`, not the 'can be downloaded later' line). ISF restored (POST /symbols created:false, 0.085 s). analyse on task 355 (no dump) -> 404. Reingest of 359: no new analyse call (guest-control log count 4 -> 4), summary.memory unchanged. Deleting 359 via API: 204, dump gone, df back (370G -> 374G), but task folder analyses/356 left partly behind (D7: memory/ and its files are root-owned, CAPE's rmtree as cape cannot remove them).
- R7: screenshots in scratchpad m8-proof/*.png (eicar-overview, memory-overview, memory-events, memory-kept-overview, memory-kept-artifacts, memory-artifacts, win-overview, lab3-eicar-overview, submit-dialog-memory). The served frontend has no Memory sub-tab / memory_dump row in the Artifacts tab (not merged); Submit dialog text says "several minutes of processing" (measured ~5 s).

- DEFECTS FIXED (regression test first, watched red, then green; backend 3955 passed; cape tests run on touched files): 
  - D1 backend/app/ingest/sysmon_processes.py (ETW_TIMED_EVENTS 3, 22 take TimeCreated); tests test_sysmon.py (new parametrized test + the two fixture timestamps updated), docs data-model.md
  - D2 backend/app/ingest/sysmon_noise.py ANALYZER_PATH {6,10} and dir without trailing sep; test test_sysmon_noise.py
  - D3 guest/profiles/windows/sysmon-config.xml (ProcessAccess exclude conhost.exe, OpenConsole.exe); test cape/tests/test_windows_profile.py
  - D5 backend/app/ingest/defender.py (ALERTING_SCOPES); test test_defender.py; docs data-model.md
  - D6 cape/bin/volatility.py MISSING_SYMBOLS_LINE (offline URL line); fixture tests/fixtures/volatility_output.py updated to the real line; docs cape-integration.md
  - D7 cape/bin/memory_logic.py (_give_to_owner_of); test test_memory_logic.py
  - Replay of real analysis dirs 350/353 through the fixed normalisers: dns event 14:30:58.67 (capemon 14:30:58.45), monitor-artefact 3 -> 6, `DefenderTamperingRestore` is kind event.
- D4 NOT fixed (design, see findings).

## Running (finished)
- live re-verification of the cape-side fixes with TEMPORARY copies into tartarus-cape (must revert: /usr/local/lib/tartarus/{volatility.py,memory_logic.py} and the sysmon-config.xml under /usr/local/lib/tartarus/profiles/windows/; originals saved in scratchpad m8-proof/orig-cape/)

## Next
- R1..R8

## Big files that exist now
- none
## Created things to clean up
- guest m8-proof; analysis 352 (self-test of the clone); ISF file KEPT (/var/lib/libvirt/tartarus/symbols/windows/)
- scratch samples in scratchpad m8-proof/ (benign.exe, eicar.com, memproof.exe); nothing left in the cape container /tmp


## Final state
- R0..R8 done; findings in R-findings.md. Cleanup done, stack stopped, df 395G. Nothing running. No big files exist (no dump, no guest).
- The temporary copies into tartarus-cape were reverted (sha256 equal to orig-cape/*).
