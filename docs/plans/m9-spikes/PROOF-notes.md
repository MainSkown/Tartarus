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
