# T17 notes (task 1.7, memory-image import runner path), resume file

## Design
- Control service takes the image as `{"image": "<analysis id>/upload"}` (under /imports), writes
  `storage/analyses/<pseudo task>/memory/`; pseudo task id = 900_000_000 + analysis id (CAPE ids are small).
- Runs as a background asyncio task of the Runner (a 66 s scan must not block the run queue's tick); the DB row
  is `running` meanwhile, a restarted runner starts it again (idempotent: ingest drops the index first).
- Ingester gets `ingest_memory_image(analysis_id, analysis_dir, started_at)`: no report, an empty `{"info": {}}`.
- `missing_symbols` in the answer -> `POST /symbols` once -> analyse again once.
- The upload is never deleted by the step (delete route does it).

## Done
- client: `analyse_memory(task, image)`, `make_symbols`, `MemoryAnalysis.missing_symbols` (tests/guest/test_client.py)
- `ReportIngester.ingest_memory_image` (tests/ingest/test_ingester_memory_image.py, P2 fixtures: PING.EXE 3888 alert, 26 events)
- `app/analyses/memory_import.py` + tests/analyses/test_memory_import.py (done, symbols once, not-a-memory-image, down, missing upload)
- runner: background scan per image, `wait_for_memory_imports`, stop cancels, restart resumes (test_runner_memory_image_import.py)
- ruff, mypy app/, pytest -m "not integration": 4132 passed

## Running
(nothing)

## Next
(nothing; committed)

## Known gaps
- `max_severity` of the analysis stays null for an image (IngestResult carries no severity)
- `storage/analyses/<900000000+id>/memory/` is left behind by the delete route (small JSON, owned by cape)
- finding time = import time (guest SystemTime not used)
