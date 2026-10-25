# F9 (task 10.11): a failed event-log export is a warning on the analysis

## What was already there
- The module `cape/auxiliary/event_logs.py` already writes `aux/event_logs.json` (`{"missing": [{channel, reason}]}`)
  for every channel it could not baseline or export, including the raw error. A real one (task 450, read-only
  `docker exec`): Sysmon `the export failed: HTTPConnectionPool(host=..., port=8000): Read timed out. (read timeout=120)`,
  Defender the same with `read timeout=30`. The reason IS carried, so the module needed no change (no cape edit).
- The backend already read it into `summary.missing_exports` (`app/analyses/missing_exports.py`), served by the API,
  but nothing in the frontend showed it and the text is raw.

## Design chosen
- Extend the existing summary JSON: `ReportSummary.warnings: list[str]`. No new column, no Alembic migration: the
  summary is already a JSON blob rebuilt wholesale by every ingest (the runner replaces `analysis.summary`), so a
  re-ingest recomputes the warnings and cannot add to them; a summary stored before has no key and validates to `[]`.
- `export_warnings(missing)` in `missing_exports.py` turns each entry into one sentence (`Sysmon events were not
  exported: the guest did not answer within 120 s`). `Read timed out ... (read timeout=N)` and `the guest agent did
  not answer within N s (...)` are reworded; any other reason is kept as the module wrote it. Channel names map to
  Sysmon and Windows Defender; an unknown channel keeps its own name.
- Deviation from the brief: not a "normaliser step". The normalisers run inside the event stream and know nothing of
  `aux/event_logs.json`; `summary._summarise` is the existing step that already reads that marker on every ingest
  (including the re-ingest job), so the warnings are derived there from the same read as `missing_exports`. A
  parse of the raw reason also means analyses 436 and 438 get their warnings on a re-ingest, which a module change
  would not give them.
- "Partial" exports: the module records none today (a settle wait that gives up is only logged), so none is warned.
- Frontend: `AnalysisWarnings.vue` (a list of `LiveNotice level="warning"`, message key
  `analysis.warnings.label` for the list's aria-label; the sentences come from the backend) is used on the Summary
  tab (above the tiles, inside the done branch) and the Events tab (above the table, inside a new column wrapper so
  the table keeps filling the viewport height).

## Failing first
- `backend/tests/analyses/test_export_warnings.py`: collection error `cannot import name 'export_warnings'`.
- `backend/tests/test_analyses_api.py`: 3 failed (`warnings` missing from the summary default, the read/list test,
  the OpenAPI properties test).
- `frontend/tests/unit/analysis-summary-sources.test.ts` and `events-tab.test.ts`: 2 failed (no `.analysis-warnings`).

## Generated client
`make api-sync` needs the running backend, which I may not start. Instead the app's OpenAPI was dumped offline
(`create_app().openapi()` to a scratch file) and `openapi-ts -i <file> -c @hey-api/client-fetch` run into a scratch
folder; the only differences from `frontend/src/api` were `warnings` (copied into `types.gen.ts`, 4 lines) and the
`baseUrl` the dev server adds to `client.gen.ts` (not copied). So `types.gen.ts` is the generator's own output.
