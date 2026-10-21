# PROOF notes (tasks 1.9 and 2.6, real-stack proof of M9 waves 1 and 2), resume file

Start 2026-10-21 16:13. df / at start: 395G free (1.4T used, 78%). Scratch: /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/c9689fac-df10-4bbf-b5b7-5153d091d85e/scratchpad/proof
Stack was DOWN at start.

## Big files that exist right now
(none)

## Done
- 16:13 read plan, T17-notes, R-notes, CLAUDE.md
- 16:50 Step 1 (a): IngestResult.max_alert_severity (ingester notes the severity of alert events), Runner._finish_done folds it with the report's max_severity for runs and images alike (one path). Tests red then green: tests/ingest/test_ingester_memory_image.py, tests/analyses/test_runner_ingest.py (parametrised), test_runner_memory_image_import.py. Score of an image stays null (CAPE's malscore has no image equivalent).
- 16:50 Step 1 (b): cape control service route DELETE /memory/{task}/findings (only task ids >= 900000000, so never a CAPE task), client.delete_image_findings, DELETE /analyses/{id} calls it for imported memory images (tolerates failure). cape tests: test_memory_logic.py, test_guest_control_memory.py; backend: test_analyses_import_api.py, guest/test_client.py. Needs the cape image rebuilt.
- ruff, mypy app/, pytest -m "not integration": 4144 passed; cape pytest 1906 passed.

## Running
(nothing)

## Next
- commit step 1; docker compose up -d --build (backend, cape, frontend); proofs (i) to (iv); make e2e; cleanup; Proof section in plan

## Temp things to clean up
(none yet)
- 16:23 stack up with rebuilt images (backend, cape, frontend); 12 pre-existing analyses left alone (ids <= 270)
- 16:24 FINDING F1: /imports volume root-owned, import -> 500 PermissionError (Dockerfile never made /imports for user tartarus). Fix: Dockerfile mkdir+chown /imports, test_stack_config.py test. Volume tartarus_imports (empty, from spike) removed and recreated.
- 16:26 (i) PCAP import: garbage bin/txt -> 415; fixture pcap -> analysis 372 done in 6 s, 196 network events, guest null, CAPE task 375 category pcap machine empty. Next: build p9sample.exe, run on lab3 with memory_dump+keep during which import pcap again (iii), take dump, upload via nginx (ii)
- 16:27 run p9sample on lab3 submitted: 373 (BIG FILE will appear: kept memory.dmp in cape-storage volume)
- 16:27 (iii-b) import 374 (pcap) submitted while run 373 was running: done in 6 s, 196 events, run still running at that time
- 16:29 run 373 (CAPE task 376) done, 4886 events, max_severity high. BIG FILE: kept dump storage/analyses/376/memory.dmp in cape-storage; copying to /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/c9689fac-df10-4bbf-b5b7-5153d091d85e/scratchpad/proof/image.raw (BIG, delete)
- 16:29 host image.raw deleted. memory image uploaded via nginx :8080 in 14.7 s -> analysis 375 (HTTP 201). Still big: dump in cape task 376, upload in imports volume 375/upload
- 16:30 (ii) image analysis 375: done in 67 s, 26 events, PING.EXE high volatility detection, max_severity high (step 1a live), score null. Next: delete 375 -> check 900000375 gone (step 1b live)
- 16:31 benign run submitted: benign run 376 queued
- 16:31 (iv) POST /api/search dns.question.name:p9-spike-one.example -> total 5 events: 373 x3, 372 x1, 374 x1; GET /api/iocs/domain/p9-spike-one.example/analyses -> 373 (3), 374 (1), 372 (1)
- 16:32 (iii-a) benign run 376 on lab3: done, 624 events, score 6.0 high (same as earlier benign runs). Now deleting 372,373,374,376 then make e2e
- 16:32 make e2e started, log /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/c9689fac-df10-4bbf-b5b7-5153d091d85e/scratchpad/proof/e2e.log (running)
- 16:39 make e2e finished: 129 OK, 0 FAIL, exit 0 (~7 min). Proof section written in the plan.
- 16:39 cleanup: analyses 372,373,374,375,376 deleted via API (imports folder empty, CAPE pcap task and pseudo task folder gone, 4 GB dumps gone); scratch dir removed; stack stopped. e2e removed its own analyses.

## Final state
All steps done. Nothing running, no big files. df / at end: see report.
