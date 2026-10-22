# G4 backend robustness notes

## Done
- F2: bson_document datetime -> BsonError; bson_log `_record` wraps record building in LogFormatError; args-not-a-list is an UnknownRecord; `LiveCollector._scan_file` isolated per file (a failing file is marked dead, others keep going).

- F3: `app/ingest/json_file.py` (`load_json_file`: size cap, Infinity/NaN rejected, RecursionError -> ValueError) used by `load_report` (1 GiB cap, report_failed "too large"), volatility plugin files (512 MiB), missing-exports marker (1 MiB).
- F5: `MAX_LEADING_BLOCKS = 1000` bounds the pcapng walk.
- F4: `app/guest/identifiers.py` holds GUEST_NAME / BUILD_ID (copied from cape/bin/guest-control, single source in the backend; desktop/guest_build.py now imports it); the REST routes use `GuestNamePath` / `BuildIdPath` (anchored pattern -> 422 before any control-service call).
- F6 (partly): `Guest.disk_path` (host path) is `exclude=True`: gone from responses and from the OpenAPI schema. Skipped: the password. `GuestCard.vue` (frontend/src/components/guest/GuestCard.vue:132-146) shows it masked with reveal and copy from the list/read model, so removing it needs a new endpoint plus a frontend change; risk is small (disposable guest on an isolated network) and G3 closes the cross-origin / rebinding reader. `work_dir` is the in-guest path (C:\tartarus), not a host path: kept. frontend/src/api/types.gen.ts still lists `disk_path`; harmless (optional, unused), `make api-sync` drops it.
- F8 (partly): `app/api/upload_limit.py`, a route class registered by hand (FastAPI parses the multipart body before any dependency runs) that answers 413 on a `Content-Length` over limit + 1 MiB, for POST /analyses (sample store limit), /import (pcap) and /import/memory-image (image). `SampleStore.max_bytes` is public now. `pack_for_download` refuses (507, `TemporarySpaceError`) a file larger than the free temp space. Skipped: capping streamed bytes of a chunked body (needs an ASGI wrapper in main.py, which is G3's, and nginx already enforces client_max_body_size), caching/streaming the zip (pyzipper cannot write an AES zip to a non-seekable stream; a cache is more than the single-user risk justifies), serialising concurrent packs. The 507 route mapping has no test (the download tests are integration and need the stack).

- F9: `decode_cursor` catches RecursionError -> 422 invalid_cursor.
- F10: `app/search/oversize.py` (`with_capped_raw`, 1 MiB cap on `tartarus.raw`, replaced by `{truncated, original_bytes}`), applied in `EventIndex._index_chunk` with a warning count; bulk requests also bounded by `max_chunk_bytes` 50 MiB.

## In progress
- none

## Next
- none. Checks: ruff check, ruff format --check, mypy app, pytest -m "not integration" all green; integration tests/integration/test_event_index.py and views/findings/test_artifact_downloads.py green.
