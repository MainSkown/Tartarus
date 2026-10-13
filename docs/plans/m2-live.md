# Plan: M2, watch an analysis while it runs

M1 shows a finished analysis. M2 lets the analyst watch one as it happens: the events and the
process tree filling in live, and, if the sample was submitted interactive, the guest's screen with
the keyboard and mouse. It builds the live collector the [backend spec](../specs/backend.md#live-collector)
describes and the LIVE tab of the [GUI spec](../specs/gui.md).

## Status

Planned 2026-10-13, after M1b was approved. **Built, committed and verified on the real stack the same day; the LIVE, desktop and Submit-dialog screens were reviewed and approved by the user.** Fixtures exist: the real BSON logs of
analysis 45 (`backend/tests/fixtures/cape/live_logs_45/*.bson`) and the calls CAPE's own processor
made of the same logs (`report_calls.json` beside them), which is exact ground truth for the parser.

**E1 (end to end), 2026-10-13, seen on the real stack.** `make e2e` follows the first analysis of the
run on `/ws/analyses/{id}/live` (client `scripts/lib/live_client.py`, checks `scripts/lib/e2e-live.sh`) and
passed step (h): statuses `starting -> running -> processing -> done` in order; `process` add for the
sample and its `cmd.exe` child, each `end` after its add; first events 30 s into the run, 30 s before
`processing`; `phase: final` once, last, then close 1000; no `error` besides the refused `query`
(`query_unsupported`, the stream went on); a client on the finished analysis gets `status`, `phase` and
1000 and no events; an unknown id closes 4404. Live against final, with `include_api`: 479, 481, 479 and
480 live events (four runs), each equal to the capemon events of the final index, with no event missing and none
extra (the "merged repeats" tolerance of five was never used). Step (f) with `DRILLS=1`: a live client
that reconnects across `docker compose restart backend` saw close codes `[1012, None x3..6 (502 while
the backend was down), 1000]`, got all 476 to 479 events again on the reconnected socket (the collector
resumes and replays from the start, decision 6), only ids of the final index, and `phase: final`.
`make e2e DRILLS=1` 71 checks, 0 failed, 13 min; `make e2e DESKTOP=1` 45 checks, 0 failed, 10 min,
including step (i): the desktop tunnel's first frame is `0.,36.<uuid>;`, a `size` follows at once, a
`clipboard` instruction sent by the client is not answered with one, the socket stays up (internal
`ping` echoed) and closes 1000 when the guest's VNC ends with the run, and a second client on the
finished analysis gets 4409; and the Playwright `desktop-flow.spec.ts` passed against the real guest with
the real `guacamole-common-js`.

Seen and not changed (E1 does not edit the backend):
- A raw client must send a `nop` at least every 15 s: `guacd` ends the connection with error 776
  (client timeout) otherwise. `guacamole-common-js` does this by itself.
- At the end of an interactive run `guacd` reports the guest's VNC going away (515) before the status
  leaves `running`, so the tunnel closes 1000 with the reason "desktop reported an error", not "analysis
  is no longer running".
- The tunnel forwards `blob` and `end` for a stream the browser never opened (the dropped `clipboard`
  one); `guacd` answers `ack ... Invalid stream index` (768) twice. Harmless, but not the silence the
  allow-list suggests.
- `default_interactive` is `true`, so the Submit dialog opens with the interactive switch on and a
  plain dialog submit holds the guest for the whole timeout. The submit flow of the e2e now turns the
  switch off.
- The e2e submit flow had been broken since the LIVE tab (two `.status-badge`, and the SCORE tile is on
  SUMMARY while the page stays on LIVE); `submit-flow.spec.ts` follows the new page now.

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

Out of scope (also): ending an interactive run early (see decision 12); the query language, facets and the Events/Timeline tabs (M3), Sigma rules (M4),
Sysmon/ETW/Suricata sources, the guest-build wizard.

**Backend done and checked on the real stack (2026-10-13)**, before any frontend: BSON parser (C1),
live events (C2), collector, hub, live WebSocket and runner hooks (C3), and the desktop tunnel's
backend (D2) are committed (1308 unit, 133 container tests). On real analyses of the benign sample:
the socket sees the status run starting, running, processing, ingesting, done and then `phase: final`;
the process tree gets its adds and ends; **the live events equal the final index exactly** in two of
three full comparisons (480 against 480, no difference in any field of any shared id); in the third,
three events differed, which is the documented case of CAPE merging identical consecutive calls.
**Pipeline delay** (log bytes written to events received by a client) is **under half a second**,
measured by sampling the log sizes every ~0.3 s beside the client. The call timestamps themselves
show about 7 s behind the client's clock because **the guest's clock runs behind the host's by
about 5 to 8 s** (an earlier comparison against the pcap gave 4 to 6 s): live and final events
carry the guest's time, so against pcap-derived network events they sit that much earlier. Not
corrected (the offset calibration rounds to a quarter hour, as designed); to be revisited when the
timeline (M3) puts both sources on one axis.

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
   same document, **except** where CAPE's processor merges consecutive identical calls into one
   with a higher `repeated` count and renumbers the calls after it (C1 found this; the parser does
   not merge, because a push parser would have to hold a call back). Live events are therefore
   best effort: the final ingest rebuilds the index and is authoritative, and the LIVE tab does not
   promise that an event's id survives the handover. Fed everything, the incremental path must produce exactly the events the report
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
11. **Interactive desktop (M2b), settled by the D1 investigation (see "Desktop findings").** The
    backend speaks the Guacamole protocol to `guacd` (`cape:4822`, already running) and tunnels it
    over `WS /ws/analyses/{id}/desktop`; the browser uses `guacamole-common-js`. **The VNC port
    comes from CAPE:** with `[guacamole] enabled = yes` (already set) CAPE appends `vnc_port=<n>` to
    the task's `options`, readable from `GET apiv2/tasks/view/{id}/` which the backend already
    polls (`TaskView` gains `options`); take the last `vnc_port`, accept only 5900-5999, always
    connect `guacd` to `127.0.0.1`. The port appears only once the guest is up, so the tunnel waits
    for it; a task being `running` does not mean the desktop is there. `guacd` connects with
    `disable-copy=true`, `disable-paste=true`, `read-only=false`, `color-depth=24`, `cursor=remote`,
    `autoretry=0` (this `guacd` has no file transfer or audio at all). The guest screen is
    1280x800 (16:10). `ready` also arrives when the guest is off, followed by an `error`: the
    tunnel treats the first `size`/`img` as connected and an `error` as "desktop not available".
    Input is refused (`4409`) unless the analysis is `running` and was submitted interactive.
12. **The `interactive` option** joins the submission options (the API rejects unknown keys today):
    a boolean, default from the `default_interactive` setting, shown in the Submit dialog. When on,
    the backend passes **`interactive=1,nohuman=yes`** to CAPE (as CAPE's own UI does; without
    `nohuman` the analyst fights CAPE's mouse mover and dialog closer). **An interactive run lasts
    the whole timeout** even when the sample exits early (the analyzer does not stop on an empty
    process list), about 3.5 minutes at the default; the Submit dialog says so beside the switch.
    Ending an interactive run early (CAPE watches for a "complete" file in the guest) is not built.
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

## Desktop findings

Task D1, observed on the real stack on 2026-10-13 (CAPE in the `cape` container, libvirt 10.0.0,
QEMU 9.2.2, `guacd` 1.6.0). Everything below was run from inside the `cape` container against CAPE's
HTTP API and `guacd` directly; the backend was not involved. The guest was never redefined and
`tartarus-clean` was never touched. One real run: task 79, `benign.exe`, options `interactive=1`,
timeout 150, route `inetsim`; deleted afterwards (`tasks/list` is back to 1-6 and 45, the analysis
folder is gone, `win` is shut off). The throwaway scripts are in the session scratchpad, not in the repo.

### 1. The guest's VNC port as libvirt and CAPE see it

While task 79 ran (17 s after submit):

```
$ virsh -c qemu:///system domdisplay win      -> vnc://127.0.0.1:0
$ virsh -c qemu:///system vncdisplay win      -> 127.0.0.1:0
$ virsh -c qemu:///system dumpxml win | grep -A2 '<graphics'
<graphics type='vnc' port='5900' autoport='yes' listen='127.0.0.1'>
$ ss -ltnp | grep qemu                        -> LISTEN 127.0.0.1:5900 users:(("qemu-system-x86",pid=4593,fd=30))
```

Display `:0` is TCP 5900. It is assigned at each start: `/var/log/libvirt/qemu/win.log` shows
`-vnc 127.0.0.1:0,audiodev=audio1` on all 12 starts, and `-incoming defer` each time, because
CAPE's start is a revert to `tartarus-clean` (a fresh QEMU process, memory loaded from
`win-clean.mem`). `autoport` takes the first free port from 5900, and with one guest and no other
listener in the `cape` container that is always 5900. All seven earlier tasks (1-6, 45) carry
`vnc_port=5900` too. So it is stable in practice, but it is not guaranteed by the definition.

CAPE records it, and the backend can read it. `cape/conf/web.conf` already sets
`[guacamole] enabled = yes`. With that, `analysis_manager.run_analysis_on_guest` calls
`KVM.store_vnc_port` (`modules/machinery/kvm.py:49`), which reads the port from the live domain
XML and `db.set_vnc_port` (`lib/cuckoo/core/data/tasking.py:923`) appends `vnc_port=<n>` to the
task's `options`. Observed through the API with the same token the backend uses:

```
GET /apiv2/tasks/view/79/     -> data.options = "interactive=1,vnc_port=5900"      (while running and after the run)
GET /apiv2/tasks/machine/79/  -> {"error": false, "machine": "win", "vnc_port": 5900}   (while running)
GET /apiv2/tasks/machine/79/  -> {"error": false, "machine": "win", "vnc_port": null}   (after the guest shut down)
```

`tasks/machine` (`web/apiv2/views.py:1155`) asks libvirt live, only answers a port for a domain in
state running, and returns `null` otherwise. Its docstring calls it a central-mode control-plane
read, authorised by `[api] control_plane_token` or by `is_local_admin`; with our single-tenant
setup the backend token passed (200). Nothing about the port is written under
`analyses/<id>/` on the `cape-storage` volume (no file there carries it); the task row is the only
record.

### 2. How the backend should learn the port: recommendation (a)

**Recommended: (a), CAPE already exposes it. Read `vnc_port=<n>` from the `options` string of
`GET /apiv2/tasks/view/{id}/`.** The backend already calls `tasks/view` while polling a task, so
this costs one new field on `TaskView` (`options: str | None`) and a parser. No new container,
port, file or libvirt access.

- Parse it as `key=value` pairs split on commas and take the **last** `vnc_port` (CAPE appends its
  own after the submitted options), then check it is an integer in 5900-5999. The submission API
  whitelists option keys, so a user cannot inject one, but the check keeps `guacd` pointed at the
  guest's display and nothing else. The `hostname` is always the constant `127.0.0.1`.
- It is absent until CAPE has started the guest and recorded the port; the tunnel waits for it
  while the analysis is `starting`. Task status reads `running` 2 s after submit, long before the
  guest is up (the analyzer started about 10 s later), so the status alone does not mean the desktop is
  there: the port appearing in `options` does.
- Trade-offs: it depends on `[guacamole] enabled = yes` (already in `cape/conf/web.conf`; a
  comment there says why) and on CAPE keeping the `store_vnc_port` behaviour, which is upstream
  code with a test file. The string stays after the run, so it is a record and not proof that
  the guest is up: the backend gates on the analysis status anyway (decision 11).
- `tasks/machine/{id}/` is the equivalent live read and answers `null` once the guest is off. It
  works with our token, but it is documented as a central-mode control-plane call and authorised
  by `is_local_admin`, which a future multi-tenant setting could withhold. Use it only as a
  fallback if `options` ever lacks the port.

**(b) Fixed port in `guest/domain.xml.tpl`: not needed, and riskier than it looks.** The change would
be `<graphics type='vnc' port='5900' autoport='no' listen='127.0.0.1'/>`. An existing guest is
redefined without a rebuild by `virsh dumpxml --inactive win`, editing that line and
`virsh define` while the guest is off (disks and NVRAM are untouched). The catch is
`tartarus-clean`: its snapshot XML embeds its own copy of the domain definition, and I saw it
carries `<graphics type='vnc' port='-1' autoport='yes' ...>`:

```
$ virsh snapshot-dumpxml win tartarus-clean | grep graphics
      <graphics type='vnc' port='-1' autoport='yes' listen='127.0.0.1'>
```

Every start is a revert to that snapshot, so I expect the old definition to win until the
snapshot XML is edited or the snapshot is retaken. That is an inference and not tested: I was not allowed to
redefine or edit anything. I only checked that `domxml-to-native` of a throwaway copy with
`port='5900' autoport='no'` is accepted and yields `-vnc 127.0.0.1:0`. It would also make a start fail if 5900
were ever taken, where autoport moves on. Since the port is already 5900 on every run, (b) buys
nothing.

**(c) Read-only helper in the `cape` container: not needed.** It would be a ~30-line Python
program under supervisord that opens `qemu:///system?readonly` and serves `{port}` on
`CAPE_INTERNAL_IP`. It duplicates `tasks/machine`, adds a listener on the internal network and a
process holding the libvirt socket (even read-only it can enumerate domains and read
their XML, which has device paths and the SMBIOS serials), needs its own port,
auth and tests. Only worth it if CAPE's two reads disappear.

### 3. The `interactive=1` option

Accepted: `POST /apiv2/tasks/create/file/` with form field `options=interactive=1` answered 200,
task 79 ran. The API treats `options` as an opaque string; nothing in apiv2 adds to it (the CAPE web
UI, `web/submission/views.py:356`, adds `interactive=1,` **and** `nohuman=yes,` together, and only when
`[guacamole] enabled`).

Where it is consumed (`analyzer/windows/analyzer.py`, in the guest):
- Line 636: the analyzer sets `INTERACTIVE_MODE`, injects the monitor into the `explorer.exe`
  shell, and (only with the separate `manual` option) copies the sample to the Desktop.
  Observed in `analysis.log`: `Interactive mode enabled - injecting into explorer shell`, `Interactive desktop enabled.`,
  and the option sent to every monitored process.
- Line 782: when the monitored process list is empty the analyzer normally ends
  (`Process list is empty, terminating analysis`, which analysis 45 logged). With
  `INTERACTIVE_MODE` it `continue`s instead. **Observed:** `benign.exe` ended 27 s in
  (`Process with pid 8332 has terminated` at 17:22:32), but the analysis stayed until the timeout
  (`Analysis timeout hit, terminating analysis` at 17:25:00). Submit to `completed` took 201 s for
  a 150 s timeout (boot and restore before, teardown after). So an interactive analysis always
  lasts the full timeout, unless the analyst leaves the "complete" folder CAPE's analyzer watches for
  (`md5("cape-<id>")` under `%TMP%` or `%SystemRoot%\Temp`), which the GUI would have to
  offer as a "stop" action; I did not try that.
- **Contradiction with the spec.** `docs/specs/cape-integration.md` says `interactive=1` "keeps the
  agent from auto-closing dialogs". It does not. The human-behaviour module (`Human`,
  `modules/auxiliary/human.py`) was started in the interactive run
  (`Started auxiliary module modules.auxiliary.human`); it is switched off by the separate option
  `nohuman` (`human.py:586`: `if nohuman: return`; read from the code, I did not run a second task
  to observe it). Decision 12 should pass `interactive=1,nohuman=yes` when the switch is on, as CAPE's
  own UI does. Without `nohuman` the analyst fights the mouse-mover and the dialog-closer.

### 4. The Guacamole handshake with `guacd`

`guacd` listens on `172.19.0.4:4822` (the `cape` container's address on `tartarus-internal`;
published nowhere). `backend -> cape:4822` connects (checked with a socket from the backend
container). `guacd` runs in the `cape` container, so the VNC target is `127.0.0.1:<port>` from
`guacd`'s point of view, and that worked.

Wire format: each instruction is `LEN.value,LEN.value,...;` with `LEN` counting Unicode
characters, not bytes. Sequence that worked (client sends C, `guacd` sends S):

```
C select,vnc
S args,VERSION_1_5_0,hostname,port,read-only,disable-display-resize,encodings,username,password,
       swap-red-blue,color-depth,cursor,autoretry,clipboard-encoding,dest-host,dest-port,
       reverse-connect,listen-timeout,recording-path,recording-name,recording-exclude-output,
       recording-exclude-mouse,recording-include-keys,create-recording-path,recording-write-existing,
       disable-copy,disable-paste,disable-server-input,wol-send-packet,wol-mac-addr,
       wol-broadcast-addr,wol-udp-port,wol-wait-time,force-lossless,compress-level,quality-level
C size,1280,800,96
C audio,
C video,
C image,image/png,image/jpeg,image/webp
C timezone,UTC
C connect,VERSION_1_5_0,127.0.0.1,5900,false,,,,,,24,remote,0,,,,,,,,,,,,,true,true,,,,,,,,,
S ready,$<connection id>                      (0.04 s after connect)
S size,-2,5,5   size,0,1280,800   rect/cfill/img/blob/end/copy/cursor ... sync,<ts>
C sync,<ts>                                   (ack every sync, or guacd stops sending frames)
```

`connect` takes one value per name in `args`, in the same order; unnamed ones are empty strings,
and the first value, for `VERSION_1_5_0`, is that same string echoed back (it is the protocol version the
client speaks). Build it from the `args` the server sent, so a `guacd` upgrade that adds a parameter
does not break the backend.

**Connection parameters to use** (all other `args` stay empty, i.e. their defaults):

| Name | Value | Why |
|---|---|---|
| `hostname` | `127.0.0.1` | The guest's VNC listens on loopback in the `cape` container |
| `port` | the `vnc_port` of the task | 5900 in practice |
| `read-only` | `false` | The analyst needs mouse and keyboard; the backend refuses input itself unless the analysis is running and interactive (`4409`) |
| `disable-copy` | `true` | Guest to client clipboard off |
| `disable-paste` | `true` | Client to guest clipboard off |
| `color-depth` | `24` | Nothing in these frames needed more |
| `cursor` | `remote` | Draws the guest's cursor in the browser; avoids a lagging local cursor |
| `autoretry` | `0` | A closed VNC must surface as an error (see below), not be retried silently |

The client `size` is a request only: I asked for 1024x768 and the display layer came back as the
guest's own 1280x800. Not set (untested): `disable-display-resize` (QEMU's VGA cannot resize
from the client anyway; set it to `true` if the browser panel ever sends a size change),
`swap-red-blue` (not needed as far as the screenshot colors go, but I did not view the Guacamole
frames themselves), `recording-*` (`guacd` could record sessions, which this design does not want).

**Clipboard and file transfer.** This `guacd` build's VNC `args` has **no** `enable-sftp`,
`sftp-*` or `enable-audio` parameters, so SFTP, audio and file transfer do not exist in it; there
is nothing to switch off, and the backend must still not forward `file`/`put` instructions
(refuse them in the tunnel regardless). The `audio` and `video` instructions answered with empty
mimetype lists are accepted. Clipboard, the two parameters above:

- Client to guest (`disable-paste`), **verified both ways**: I sent
  `clipboard,9,text/plain` then `blob,9,<base64>` and `end,9`. With `disable-paste=true`,
  `guacd` answered `ack,9,Clipboard unsupported,256` (and `ack,9,File transfer unsupported,256` for the
  blob that followed); with `disable-paste=false` it answered no error. So the parameter does
  switch the handler off at `guacd`, not just in the page.
- Guest to client (`disable-copy`): the parameter is in `args` and I set it, but I could not
  verify the effect, because no `clipboard` instruction arrived in either run to begin with
  (the guest's clipboard did not change while I watched), so there is no contrast case.
  Unverified.
- Drag-and-drop: there is no `guacd` parameter for it; in Guacamole it is the file upload over
  SFTP, which this build lacks. Not wired in the page either.

**What a frame stream looks like.** 10 s of a booted desktop, counted by opcode:
`{'ready': 1, 'size': 2, 'rect': 32, 'cfill': 31, 'img': 135, 'blob': 144, 'end': 135, 'cursor': 1, 'sync': 88, 'copy': 87}`.
`img`/`blob` carry PNG/JPEG tiles. The tunnel can be a plain relay; it only needs to parse
instructions enough to refuse the client opcodes `clipboard`, `file`, `put`, `get`, `nest`
and anything else not in an allow-list (`mouse`, `key`, `sync`, `ack`, `size`, `disconnect`, `nop`, `blob`
and `end` for streams the server opened).

**An unreachable VNC still answers `ready`.** With the guest shut off I got `ready` in 0.04 s, then
`error,Aborted. See logs.,519` and `nop`. So `ready` does not mean the desktop is up: the tunnel
should consider the connection good at the first `size,0,...` or `img`, and treat `error` (519 is
`guacd`'s "upstream error") as "desktop not available" instead of a bug.

### 5. Resolution

The guest runs **1280x800** (16:10): the `size,0,1280,800` layer from `guacd`, and a `virsh
screenshot win` PNG of the same task is 1280 x 800 and shows the Windows 11 desktop (taskbar, Edge
on the INetSim page, Polish UI, clock 17:23). Request `size,1280,800,96` and let the browser scale
the canvas to the panel (`Guacamole.Display.scale`). The GUI spec's mockup says 16:9 for the panel; the
real screen is 16:10, so the panel needs a 16:10 box, or it letterboxes.

### Unverified, and where this could differ

- A fixed port in the XML plus the snapshot behaviour (b): inference only (see 2).
- `nohuman=yes` stopping the dialog-closer: read from code, not run (one extra task would show it).
- Keyboard and mouse reaching the guest: one `mouse` instruction was sent and accepted; no key was
  sent and no visible effect was checked. Absolute mouse positioning should be fine as the guest
  has a USB tablet, but I did not test it.
- `disable-copy` (guest to client): see above.
- Behavior with two guests at once: there is only one machine, so autoport always gave 5900. Reading
  `vnc_port` from `options` is already per task, so it holds if more machines are added, but the 5900-5999
  range check would need widening.
- Whether the `complete` folder trick ends an interactive run early: not tried.
- Frame colors and the display's behavior in a browser through `guacamole-common-js`: only the protocol
  was exercised, not a client that draws it.

## After the review

- **Reported by the user:** after leaving the LIVE tab there was no way back to it. The tab ended its
  "live session" when another tab was picked; it now starts when the analysis is seen active (on
  whatever tab the page was opened) and stays for the page session, also after the run ended, where it
  shows the finished panel. Covered by a unit rule, page tests and two Playwright scenarios.
- **Found by my own end-to-end run:** the live-versus-final check compared ids, and CAPE's merging of
  identical consecutive calls shifts ids after the merge (the live path does not merge), so 6 live ids
  were missing in one run and none in four others. The check now compares the call (process, time,
  action, API). Making the live path merge like CAPE (one held-back call per process) would remove the
  divergence at the cost of showing the newest call late; not done.
- **Open:** a failed browser end-to-end test leaves its analysis behind (cleanup cannot delete a running
  one), which then blocks the next run's precondition; `default_interactive` is on, so a plain submit
  holds the guest for the whole timeout; the guest's clock runs 5 to 8 s behind the host's.
