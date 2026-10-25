# C1 backend security review (backend/app, v1)

## Progress
- done: areas 1 to 7 (all read; the exploitable items below were confirmed with scripts under the session scratchpad)
- in progress: none
- next: none; findings are final. Fixes are not applied (read-only review).

Scope note: the deployment is "solo analyst, local only, no auth, bind 127.0.0.1" (docs/features/tartarus-v1.md:115).
Only the frontend container publishes a port (`127.0.0.1:8080`, docker-compose.yml:115); the
dev overlay also publishes backend 8000, Postgres 5432 and OpenSearch 9200 on 127.0.0.1.
No subprocess, no archive extraction and no outbound HTTP with a URL derived from data exist in
`backend/app` (grep for subprocess/zipfile/tarfile/urllib/requests: nothing; httpx is used only for
CAPE and the control service, with URLs from settings).

## Findings

### F1 (medium) No Origin / Host validation on the API and WebSockets (CSWSH, DNS rebinding, CSRF)
- Where: backend/app/main.py:150-159 (no CORS/TrustedHost/Origin middleware; `grep -i origin` over app/
  finds nothing relevant), backend/app/ws/desktop.py:100-115 and :124 (`websocket.accept()` with no
  Origin check), backend/app/ws/live.py:77, backend/app/ws/system.py:63, frontend/nginx.conf:11
  (`server_name _`, passes `Host $host` through).
- Exploit: the analyst opens any web page while Tartarus runs. The page opens
  `new WebSocket("ws://127.0.0.1:8080/ws/analyses/12/desktop")` (WebSockets are not blocked by the
  same-origin policy and the server never looks at Origin) and gets the guacd tunnel: it sees and
  drives the screen of the malware guest during an interactive run. `/ws/analyses/{id}/live` and
  `/ws/system` leak every event, process and job of the analysis. Cross-origin "simple" requests
  also work without a preflight: a `multipart/form-data` POST to `/api/analyses` queues an
  attacker-chosen binary on the analyst's guest, and body-less POSTs (`/api/analyses/{id}/cancel`,
  `/finish`, `/reingest`, `/api/rules/reload`, `/api/guests/{name}/check`, `/api/guests/builds/{id}/cancel`)
  run. With DNS rebinding (attacker domain re-pointed to 127.0.0.1, accepted because Host is not
  checked) the page becomes same-origin and can read everything, including `GET /api/guests`
  (F6) and artifact downloads. Chromium's Local Network Access prompts reduce this for fetch/WS in
  Chrome; Firefox/Safari and rebinding are not covered.
- Fix (smallest): a small ASGI middleware (HTTP and WebSocket scopes) that rejects when the `Host`
  header host is not in an allowlist (`localhost`, `127.0.0.1`, `[::1]`; Starlette's
  `TrustedHostMiddleware` does this for HTTP) and, for WebSocket handshakes and non-GET requests,
  when an `Origin` header is present and is not `http://<allowed host>:<TARTARUS_PORT>`. Nginx
  `if ($http_origin ...)` on `/ws/` is an equivalent one-liner.

### F2 (medium) Guest-controlled capemon log bytes permanently stop live collection of the whole analysis
- Where: backend/app/live/bson_document.py:81 (`datetime.fromtimestamp` raises plain `ValueError` /
  `OverflowError`, not `BsonError`), backend/app/live/log_values.py:51 (`filetime_to_datetime`:
  `OverflowError` past year 9999), backend/app/live/bson_log.py:268 (`timedelta(milliseconds=elapsed_ms)`
  `OverflowError`), backend/app/live/bson_log.py:210-211 (`len(values)` in the reason string raises
  `TypeError` when `args` is not a list), caught nowhere: backend/app/live/bson_log.py:176-180
  (`_decode` only catches `BsonError`), backend/app/live/collector.py:198-213 (`_scan` has no per-file
  guard), :135-140 (`_poll` swallows the exception and retries forever).
- Exploit (confirmed with scripts): malware running in the guest (it can write to its own capemon
  log stream, or just call APIs with a crafted value; admin in the guest can also connect to the
  ResultServer) emits one message such as a process record with TimeHigh/TimeLow = 0xFFFFFFFF, a
  call with `t` = 2**62, a BSON datetime element with 2**62 ms, or `args` = an int. `parser.feed`
  raises a non-`LogFormatError` exception, the bad message stays at the head of the buffer and is
  re-parsed on every poll (3 of 3 polls raised), `log.dead` is never set, and because `_scan`
  aborts as a whole the logs sorted after this one are never read while the earlier logs' results
  from the same scan are dropped after their offsets advanced. The live view and the live
  detections of that analysis go dark for the rest of the run, which is a cheap evasion of the
  live feature. The final report ingest is separate and is not affected.
- Fix: in `BsonLogParser._drain` / `_decode` convert `(ArithmeticError, ValueError, TypeError)` from
  decoding and record building into `LogFormatError` (so the file is marked dead like any other bad
  log), and wrap the per-file body of `LiveCollector._scan` in try/except so one log cannot hide the
  others. Also replace `len(values)` in the reason with `type(values).__name__`.

### F3 (low) `report.json` loaded without a size or type guard
- Where: backend/app/analyses/summary.py:77 (`json.loads(path.read_bytes())`), :168-169 (`_integer`:
  `int(inf)`), backend/app/ingest/volatility_output.py:53 (`read_text` of plugin files, no size cap,
  `ROW_CAP` is applied after the whole file is parsed), backend/app/analyses/missing_exports.py:39.
- Exploit (confirmed): Python's `json.loads` accepts `Infinity`/`NaN` and, past roughly 100000
  levels, raises `RecursionError`, neither is `ValueError`. `{"info":{"duration":Infinity}}` makes
  `read_report` raise `OverflowError`; the runner treats it as an unexpected error, retries until
  `MAX_CONSECUTIVE_ERRORS` and ends the analysis `failed` with a generic message instead of
  `report_failed` with the reason. The input is CAPE's own report, so reaching these needs a value CAPE
  copies verbatim from the guest; I did not find a concrete CAPE path that does, hence low. The
  whole report (and, for Volatility, the whole JSON) is held in memory with no cap.
- Fix: `json.loads(..., parse_constant=...)` raising `ValueError`, catch `RecursionError` and
  `OverflowError` next to `OSError, ValueError` in `load_report`, and refuse files over a size
  cap (stat before read) in `load_report` and `volatility_output._load`.

### F4 (low) Path parameters are put into control-service URLs without quoting
- Where: backend/app/guest/client.py:180-212 (`f"/guests/{name}..."`, `f"/builds/{build_id}..."`),
  routes backend/app/api/guests.py:104-244. The WebSocket resolver does validate the name
  (backend/app/desktop/guest_build.py:28), the REST routes do not.
- Exploit (confirmed with httpx): `GET /api/guests/..` becomes a request for `/` on the
  token-authenticated control service, `POST /api/guests/builds/../resume` becomes `/resume`,
  `name="x?tail=1"` or `"a#b"` smuggles a query or drops the rest of the path. Slashes cannot be
  injected (Starlette decodes `%2F` before routing and `{name}` does not match `/`), so only
  control-service routes that already exist at its root are reachable, and no dangerous one was
  found; the issue is the missing validation, not a demonstrated bypass.
- Fix: `quote(name, safe="")` at the three interpolation helpers in `HttpGuestControl`, or
  `Path(pattern=GUEST_NAME)` on the route parameters (and a similar pattern for `build_id`).

### F5 (low) Pcapng walk is unbounded CPU for a 512 MiB upload
- Where: backend/app/imports/packet_capture.py:60-70 (`_pcapng_first_packet`). The loop reads every
  block until it finds an enhanced packet; `_MAX_LEADING_BLOCK` bounds one block, not the count.
- Exploit (measured): 60 MB of 12-byte unknown blocks takes 1.2 s, so a 512 MiB upload takes about
  10 s of one thread (`asyncio.to_thread`) per upload, repeatable. No memory growth. Impact is
  minor in a one-user tool.
- Fix: stop after a block count or byte budget (for example 1 MiB or 1000 blocks) and raise
  `UnreadableCaptureError`.

### F6 (low) `GET /api/guests` returns the guest account password and host paths
- Where: backend/app/guest/schemas.py:50-53 and :84 (`GuestIdentity.password`), :90-92 (`work_dir`,
  `disk_path`), returned verbatim by backend/app/api/guests.py:38-45.
- Exploit: combined with F1 (DNS rebinding) or any reader of the unauthenticated API, the sandbox
  guest's auto-logon administrator password is readable. The guest is disposable and the password
  only protects a VM on an isolated network, so the direct impact is small.
- Fix: a response model without `identity.password` (the UI can show it only where the wizard needs
  it) and without host paths.

### F7 (low) No `X-Content-Type-Options` / framing headers
- Where: frontend/nginx.conf (no `add_header` for security), FastAPI `FileResponse`s in
  backend/app/api/views_findings.py:97-140 and api/jobs.py:38-52.
- Exploit: the unauthenticated UI can be framed by any page (clickjacking of delete, cancel and the
  desktop console); screenshots are served as `image/png|jpeg` by extension without `nosniff`. Downloads
  are all `attachment` with a fixed or sanitised filename (checked, F-none below), so no script
  execution path was found.
- Fix: in nginx `add_header X-Content-Type-Options nosniff always; add_header X-Frame-Options DENY always;
  add_header Content-Security-Policy "frame-ancestors 'none'" always;` (check the SPA still loads).

### F8 (low) Uploads are spooled whole by Starlette before the app's size limits run; artifact zip is uncapped
- Where: backend/app/api/analyses.py:121,158,175 (`UploadFile` parameters: Starlette writes the
  multipart body to a temp file before the handler runs), backend/app/samples/store.py:122-128,
  backend/app/imports/upload.py:124-139 (limits applied while copying), backend/app/views/artifacts.py:100-112
  (`pack_for_download` zips into `tempfile.mkstemp` in `/tmp`; `memory.dmp` is downloadable).
- Exploit: the real bound is nginx (`client_max_body_size 512m` / `5g`), so a 5 GB image is written
  to `/tmp` and then again to `/imports`, and a capture sent to the memory-image route is accepted
  up to 5 GB by nginx and rejected only after being spooled. Each download of a multi-GB
  `memory.dmp` builds another full temp zip; concurrent downloads multiply it. No disk-space check
  for imports. This is self-inflicted availability only (single local user).
- Fix: none required for v1; if wanted, stream-check `Content-Length` against the kind limit in a
  dependency, and cache or cap the artifact zip.

### F9 (info) `search_after` cursor decoding can 500 on a deeply nested payload
- Where: backend/app/events/cursor.py:41 (`json.loads` of client-supplied base64; `RecursionError` is not
  caught, only `binascii.Error, ValueError`). Result is the generic 500 envelope, no leak. Fix: add
  `RecursionError` to the except tuple.

### F10 (info) One oversized event can fail the whole ingest
- Where: backend/app/search/index.py:121-127 (1000-event bulk chunks, `tartarus.raw` keeps the full
  raw call/record, `truncate` applies to summaries only). A single multi-MB record could push a chunk past
  OpenSearch's `http.max_content_length` (100 MB), giving `report_failed`. CAPE and capemon truncate
  long arguments, so this is theoretical. Fix: cap the raw record size at normalisation, or chunk by bytes.

## Checked, nothing found

1. CAPE report ingest (app/ingest, app/analyses): `load_report` rejects non-dict reports; every
   section is read through `ingest/reading.py` (`mapping_list`, `section`, `text_or_none`, `to_int`) so
   type confusion degrades to "missing"; `to_int` uses `int(text, 16|10)` on short values; all regexes in
   app/ are linear (anchored, mutually exclusive alternatives; the biggest are `_REGISTRATION`,
   `ANALYZER_PATH`, `TOOLING_PATH`, `FILESYSTEM_PATH`, `_BEYOND_MICROSECONDS`); Sigma/user regexes go through RE2.
   Residual: F3 (size/Infinity), F10.
2. Sysmon EVTX/Defender: the guest exports XML, parsed by stdlib `ElementTree.iterparse` through
   `_BoundedUtf8Reader` (64 MiB cap, replacement decoding, `ParseError` swallowed); billion-laughs
   test file returned in 0.06 s (expat amplification guard + cap), no external entity fetch.
   Events are cleared as they stream. Defender/Sysmon paths are fixed (`analysis_dir/sysmon/sysmon.xml`,
   `aux/defender.xml`), no report string builds a path. Volatility JSON: row cap 5000, malformed rows
   dropped (F3 residual: no file-size cap). PCAP import: only the first 8 bytes and a bounded block walk are
   read (F5); magic-sniffed, size limit 512 MiB (pcap) / 5 GiB (image) enforced while streaming, the file is
   written `xb` into a `mkdtemp` directory then renamed into `<imports>/<analysis id>/upload`; the on-disk
   name is a constant, the user filename never reaches a path; `.incoming-*` dirs are removed in `finally`.
   Memory image: backend only sends `{analysis_id}/upload` (integer id) and `900000000+id` to the
   control service; no subprocess or argv is built in the backend.
3. Upload and samples: `safe_file_name` keeps only the basename (handles `\` and `/`), stored sample is
   named by SHA-256 (`_zip_path` validates the digest with `fullmatch`), saved as an AES zip
   (`infected`) with 0600 files and 0700 dir; `_decrypt` extracts exactly one member to a fixed name
   (`(member,) = infolist()`, no member name used as a path); httpx 0.28 percent-encodes control
   characters and quotes in multipart filenames. Size limit 512 MiB enforced chunkwise
   (samples/store.py:128-133) plus nginx. Content-type is never trusted (the `UploadFile.content_type`
   is not read anywhere). Downloads: artifact route resolves only ids that the report catalog maps to a file,
   `_disk_name` requires `[A-Za-z0-9][A-Za-z0-9._-]*` or a SHA-256, and `_inside` resolves symlinks and
   checks `is_relative_to` the analysis dir; the served file is always a fresh AES zip with a
   sanitised name (`download_name`); Starlette's `FileResponse` percent-encodes the filename and
   sets `attachment`; job downloads go through `resolve_export` (resolve + `is_relative_to`);
   export route filenames are built from the integer id. The sample itself has no download route.
4. Query compiler: grammar is LALR over a contextual lexer, lexer regexes have mutually exclusive
   alternatives; length 2000, depth 20, 100 terms and 25 wildcard terms enforced before building;
   user text only ever becomes a dict *value* (term/wildcard/match_phrase/range) with fields
   resolved against the catalog (`resolve_query_field`; flat-object sub-keys are dict keys only), numbers
   and dates are validated before use, `\` doubled in wildcards; value-autocomplete escapes every Lucene
   regex operator in `include`; histogram buckets capped at 2000; page sizes, chips, pids, columns and
   facets capped; OpenSearch errors become 502/504 envelopes without the raw error. Sigma rules: only
   read from the mounted rules directory (no upload endpoint), `yaml.safe_load_all`, one document,
   RE2 with pattern length 4096 / program 1 MiB / input 32 KiB, `rule_yaml` checks `is_relative_to` the
   root, and loading never raises. (A YAML alias bomb in a hand-placed rule file is host-trusted input.)
5. Export: Jinja `autoescape=True` + `StrictUndefined`; the only `Markup` values are the static CSS/tokens and
   an SVG built with `ElementTree` (escapes); no `|safe`, no user value in `href`/`style`/`src` (only
   `data:` URIs of screenshots with a media type from a fixed table). WeasyPrint is built with
   `URLFetcher(allowed_protocols={"data"})`; verified with a script that `<link>`, `@import`, `url()`,
   `@font-face file://`, `<img file://>`, `<embed>`, `<object>` and SVG `<image href>` all fail with "disallowed protocol"
   and a local HTTP listener received 0 requests. CSV: cells starting with `= + - @ \t \r` are prefixed with `'`.
   STIX pattern literals escape `\` and `'`, IPs are validated, all JSON is serialised with `json.dumps`;
   MISP values are JSON strings, tag names come from the validated annotation grammar or the bundled ATT&CK table.
6. Auth surface: there is no authentication by design (see scope note); issues arising from that are F1,
   F6, F7. CORS is not configured (browsers block cross-origin reads, which is fine). `/openapi.json` and `/docs` are
   not reachable through nginx (only `/api/` and `/ws/` are proxied). `/internal/cape/callback` is unauthenticated
   but only nudges the runner. Validation errors do not echo input (`handle_validation_error` omits `input`),
   unhandled exceptions return a fixed 500 body, guest-control and CAPE errors are reduced to a type or curated message
   (`GuestControlError` docstring, `http_errors.py`), health checks report only the exception class. Tokens are
   `SecretStr`, sent only in headers, never logged. The desktop tunnel decides guacd's target from the
   server side only, drops every browser opcode outside `{mouse,key,size,sync,ack,blob,end,nop}`, and sets
   `disable-copy`/`disable-paste`; instruction length is capped (262144) and length digits capped (7). Live hub queues are bounded (1000).
7. Outbound HTTP: only `CapeClient` (CAPE_API_URL) and `HttpGuestControl` (GUEST_CONTROL_URL), both fixed by
   settings; the only data in those URLs are integer task ids and the unquoted names of F4. The
   Volatility symbol fetch happens inside the control service (the backend sends a GUID and an age that
   come from `MissingSymbols`, validated by the response model). No fetch of a sample, report or
   rule URL exists. STIX/MISP `url` indicators and the ATT&CK link are output only.

## Table (by severity)

| ID | Severity | Area | Location | One line |
|----|----------|------|----------|----------|
| F1 | medium | auth/WS | main.py:150, ws/desktop.py:124, ws/live.py:77, frontend/nginx.conf:11 | No Origin/Host check: cross-site WebSocket to the guest desktop, DNS rebinding, CSRF by simple POST |
| F2 | medium | ingest (live) | live/bson_document.py:81, live/log_values.py:51, live/bson_log.py:211,268, live/collector.py:198 | Crafted guest log value raises an unhandled exception and stops live collection for the analysis |
| F3 | low | ingest | analyses/summary.py:77,169, ingest/volatility_output.py:53 | Unbounded report read, `Infinity`/`NaN`/deep nesting escape `ReportUnreadableError` |
| F4 | low | guests API | guest/client.py:180-212, api/guests.py | Unquoted path params reach the control service (`..`, `?`, `#`) |
| F5 | low | import | imports/packet_capture.py:60 | Pcapng walk costs about 10 s CPU per 512 MiB upload |
| F6 | low | guests API | guest/schemas.py:53, api/guests.py:38 | Guest account password and host paths in `GET /api/guests` |
| F7 | low | headers | frontend/nginx.conf | No nosniff / frame-ancestors headers |
| F8 | low | uploads | api/analyses.py:121, views/artifacts.py:104 | Uploads spooled whole before limit checks; uncapped temp zip of memory.dmp |
| F9 | info | events | events/cursor.py:41 | Deeply nested cursor gives a 500 |
| F10 | info | ingest | search/index.py:121 | One oversized raw record can fail a bulk chunk |

Counts: critical 0, high 0, medium 2, low 6, info 2.
