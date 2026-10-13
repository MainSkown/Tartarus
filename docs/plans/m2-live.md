# Plan: M2, watch an analysis while it runs

M1 shows a finished analysis. M2 lets the analyst watch one as it happens: the events and the
process tree filling in live, and, if the sample was submitted interactive, the guest's screen with
the keyboard and mouse. It builds the live collector the [backend spec](../specs/backend.md#live-collector)
describes and the LIVE tab of the [GUI spec](../specs/gui.md).

## Status

Planned 2026-10-13, after M1b was approved. Nothing built yet. Fixtures exist: the real BSON logs of
analysis 45 (`backend/tests/fixtures/cape/live_logs_45/*.bson`) and the calls CAPE's own processor
made of the same logs (`report_calls.json` beside them), which is exact ground truth for the parser.

## Outcome

While an analysis is `starting` or `running`, its page opens on a **LIVE** tab:
- A status bar: state, elapsed and remaining time.
- The **process tree** growing: processes appear and end as they do in the guest.
- The **event stream**: a virtual list that follows new events, can be paused (with a "+N new"
  backlog counter), hides API calls by default behind a toggle, and filters by process (click a
  process) and lane. If the stream is faster than the browser, it says "N events skipped".
- A **detections** panel: empty during the run, saying why (signatures run after the analysis;
  live rules arrive with Sigma in M4).
- The **desktop** of the guest, when the sample was submitted interactive: mouse and keyboard
  while the panel has focus (blue glow), fullscreen, Ctrl+Alt+Del. No clipboard, no file transfer.
- When the run ends the stream stops, the views load as in M1b, and the tab shows the last
  screenshot and a link to the finished views.

Out of scope: the query language, facets and the Events/Timeline tabs (M3), Sigma rules (M4),
Sysmon/ETW/Suricata sources, the guest-build wizard.

## Decisions (made now so no agent has to guess)

1. **The BSON log parser is written from the format, not copied.** CAPE's `netlog.py` is the
   reference for what the format is; its code is not copied into the repo, so Tartarus does not
   inherit CAPE's licence. The format: a stream of length-prefixed BSON documents per process
   (`logs/<pid>.bson`); "info" messages define, per API call index, the API name, the argument
   names and their types, the category and flag tables; call messages then carry an index, a
   timestamp, thread, return value and the argument values. **Ground truth:** parsing the two real
   logs must reproduce `report_calls.json` (every call's api, category, status, return value,
   argument names and values, repeat count, and timestamp), because CAPE's processor builds the
   report from the same files.
2. **The parser is a push parser:** `feed(chunk) -> records`, keeping the info tables per file and
   holding back a partial trailing record (CAPE's ResultServer writes non-atomically; a half
   record at the end of a file is normal mid-write, never an error). Feeding a file in random-sized
   chunks gives the same records as feeding it whole.
3. **Live events are the capemon events of M1b, produced incrementally.** The derivation rules
   (`capemon_rules.py`) are reused as they are: an incremental front-end feeds new calls through
   them and keeps their per-run state (created children, process identities). Event ids use the
   same inputs as the final ingest, so a live event and the final event for the same call are the
   same document. Fed everything, the incremental path must produce exactly the events the report
   path produces for the same calls (a test over the real fixture proves it).
4. **Clock.** capemon's timestamps are the guest monitor's clock, offset from true UTC by the host's
   UTC offset (M1b, decision 6). Live there is no `info.started`: the anchor is
   `analysis.started_at` from the database (CAPE's `started_on`, true UTC) against the earliest
   process time seen so far, with the same 15-minute rounding, via the one helper in `clock.py`.
5. **The index while live.** Events are bulk-indexed into the analysis's own index as they arrive
   (refresh 1 s, the template's default), so the REST backfill and, later, the M3 views work during
   the run. The final ingest still drops and rebuilds the index (M1b, decision 4), and the
   `phase: final` message tells clients to reload. Live indexing is best effort: if it fails the
   analysis is unaffected and the final ingest is authoritative.
6. **No checkpoint table.** The backend spec's per-file offset checkpoint in the `job` row is not
   built: after a restart the collector re-reads the logs from the start and upserts by event id,
   which is idempotent and cheap (logs are megabytes), and clients backfill through REST.
7. **The collector is started and stopped by the runner's state changes** (it starts when an
   analysis becomes `running`, or on backend start if one already is; it does a final drain and
   stops when the status leaves `running`), through a port like the ingester's, so the runner does
   not import the collector.
8. **What is live.** Calls and the events derived from them (process, file, registry, network and
   injection). Network records from the pcap, CAPE signatures and ATT&CK arrive at the final
   ingest. The LIVE tab says so; it does not fake them.
9. **Transport.** One in-process hub (the backend is one process) fans events out to the WebSocket
   clients of an analysis; each connection has a bounded queue and, when it falls behind, keeps the
   newest events and counts the `dropped` (the spec). Messages as in the backend spec:
   `status`, `events` (batched at most every 250 ms, without `tartarus.raw`), `process`, `counts`,
   `phase`, `error`. On connect the server sends the current `status` and the process tree, then
   only new events.
10. **Server-side filter in `subscribe`:** `{lanes?, pids?, include_api?}`. The `query` field of the
    spec belongs to M3 and is refused with `error` code `query_unsupported`.
11. **Interactive desktop (M2b).** The backend speaks the Guacamole protocol to `guacd`
    (`cape:4822`, already running) and tunnels it over `WS /ws/analyses/{id}/desktop`; the browser
    uses `guacamole-common-js`. `guacd` connects to the guest's VNC display, which libvirt binds to
    `127.0.0.1` inside the `cape` container on a port chosen when the guest starts: **how the
    backend learns that port is an open question**, answered by an investigation task before the
    tunnel is built (options: CAPE already records it for its own Guacamole view; a fixed port in
    the guest's libvirt XML; a small helper in the cape container). Clipboard, drag-and-drop and
    file transfer are disabled at `guacd` (connection parameters), not only in the page. Input is
    refused (`4409`) unless the analysis is `running` and was submitted interactive.
12. **The `interactive` option** joins the submission options (the API rejects unknown keys today):
    a boolean, default from the `default_interactive` setting, shown in the Submit dialog; CAPE's
    own `interactive=1` option is passed through when set.
13. **Frontend.** The LIVE tab exists only while the analysis is active (the tab registry learns
    that availability can depend on the analysis), and an active analysis opens on it. A
    `useLiveAnalysis(id)` composable owns the WebSocket (reconnect and backoff shared with the
    system health client in `services/ws.ts`, extracted rather than copied), the event buffer, the
    process tree and the counters; components only render.

## Waves

Tasks marked **care** follow rule 5's extreme-task process on Sonnet: small steps each ending in a
check that can fail, a notes file (done / running / next), and the planner re-runs the checks and
reads the diff before committing. Every task is test-first.

### Wave 1 (parallel, disjoint files)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **C1** | BSON log parser | Sonnet, **care** | `app/live/bson_log.py`: the push parser of decisions 1 and 2, producing raw call, process and thread records with typed values | Real fixture reproduces `report_calls.json` exactly; chunked feeding equals whole feeding for random chunk sizes including one byte at a time; a truncated record waits, never raises; garbage after a valid prefix is reported, not crashed on; a file with only info messages yields no calls |
| **D1** | Desktop investigation | Sonnet, **care** | A written finding in this plan (section "Desktop findings"): how the backend can learn the VNC port of the running guest, which `guacd` parameters disable clipboard and transfer, what a minimal Guacamole handshake with `guacd` needs; a throwaway script (not committed) that proves it against a really running interactive analysis | The finding states what was observed on the real stack, with the commands |

### Wave 2

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **C2** | Incremental events | Sonnet, **care** | `app/ingest/live_capemon.py`: raw records to events through the existing derivation rules, with the state they need; one shared `event_id` path with the final ingest; the calibrated clock of decision 4 | On the real fixture the live path and the report path give identical event sets (ids, actions, lanes, times); feeding in order of arrival across two processes interleaved gives the same set; process-created is derived once |

### Wave 3

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **C3** | Collector, hub and live WebSocket | Sonnet, **care** | `app/live/collector.py` (tails `logs/` of a running analysis, restart-safe by decisions 5 and 6), `app/live/hub.py`, `WS /ws/analyses/{id}/live` with the messages of decision 9, the runner port and its hooks (decision 7), counts and the process-tree snapshot | A fixture directory written incrementally (the real logs appended in slices) drives the collector: events and process deltas arrive in order, a partial record waits, the final drain catches the tail; a slow client is dropped to the newest events with the right count; a restart mid-run re-reads without duplicates; the runner starts and stops it on state changes; `subscribe` filters; `query` is refused |

Planner then runs a real analysis on the stack and watches the WebSocket (event counts against the
final index, latency from a call to its arrival).

### Wave 4 (parallel)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F5** | LIVE tab | Sonnet | `useLiveAnalysis`, the status bar, process tree, event stream, detections note, last-screenshot state, tab availability by status (decision 13); screenshot scenarios (running, paused with backlog, skipped events, empty, reconnecting, finished handover, narrow) with the WebSocket mocked at the Playwright level; rule 4 review |
| **D2** | Desktop tunnel (backend) | Sonnet, **care** | The Guacamole protocol client, `WS /ws/analyses/{id}/desktop`, the `interactive` option and its setting (decision 12), `guacd` parameters from D1, the `4409` rule |

### Wave 5

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F6** | Desktop panel and Submit option | Sonnet | `guacamole-common-js` panel with focus glow, Esc-Esc release, fullscreen, Ctrl+Alt+Del, keyboard layout; the interactive switch in the Submit dialog; screenshot scenarios; rule 4 review |
| **E1** | End to end | Sonnet | `make e2e` gains a live check: submit interactive, connect the WebSocket while running, assert events and process deltas arrive in order, the count after the final ingest equals the indexed events, `phase: final` arrives, and the desktop tunnel delivers a frame; a drill that restarts the backend mid-run and checks the stream resumes |

## Risks

| Risk | Handling |
|---|---|
| The parser misreads an argument type or flag table | The real fixture compared with CAPE's own report, field by field; a second real analysis added before M2 is called done |
| capemon versions differ in their log format | The parser reports an unknown message type instead of guessing; recorded as a known limit |
| A noisy sample floods the stream | Batching, bounded per-connection queues with a dropped count, API lane hidden by default, a virtual list in the browser |
| The VNC port cannot be learnt without touching libvirt | D1 settles it first; the fallback is a fixed port in the guest XML, redefined while the guest is off |
| Live indexing slows the run | It is best effort and off the runner's path; measured on the real stack |
| WebSocket through nginx | `/ws/system` already works through it; the live route reuses the same location rule, checked in E1 |
| Agents report results optimistically | The planner re-runs every gate, and `make e2e`, before committing |
