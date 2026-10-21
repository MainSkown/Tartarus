# P3 findings: two analyses at once (M9 wave 3)

Spike on the real stack, 2026-10-21. Guests `lab3` (.13, Defender off, Sysmon on) and `lab5` (.12, Defender on, Sysmon on),
both ready clones, so no clone was made. CAPE at the pinned `CAPE_REF`, agent 0.23. Samples: the self-test
`benign.exe`, route `inetsim`, `timeout=60`. Tasks were submitted straight to CAPE's API (`machine=<label>`), so
Tartarus' runner (one analysis at a time) was out of the loop; event counts come from running the backend's own
normalisers over each task's folder offline. Nothing in the repo was changed except this file and
[P3-notes.md](P3-notes.md); every temporary change is listed there and was reverted. Raw numbers: 16 CAPE tasks
(384 to 399): four parallel pairs, one triple, five solo.

## Verdict

**GO, with two prerequisites that wave 3 must carry as its first tasks, and a smaller wave than planned.**

CAPE itself handles two (and three) tasks at once without any change: both guests revert, run, report, with their own
folders, ResultServer stream, rooter rules, PCAP and event-log exports. What does not hold is **Tartarus' own network
isolation between guests**, and the code is mostly ready already: the live manager, hub, WebSocket routes, desktop
resolver and tunnel, finish route and gates are keyed per analysis; the single-slot logic is the runner, four
repository queries, and a handful of messages.

| Prerequisite | Why it blocks |
|---|---|
| **P-1 Guest-to-guest isolation** (task 3.0) | With two guests up, each reaches the other's CAPE agent (:8000, remote code execution), SMB and RPC, and answers ping. A sample on guest A could drive guest B's agent. One-at-a-time never exposed this. A per-port bridge flag fixes it (measured). |
| **P-2 The event-log module must wait for the agent** (task 3.1b) | When a guest is slow to answer after its revert (11 s instead of 4 to 6 s, seen once in 15 runs, right after the same guest's previous task), `event_logs.start()` finds no agent, reads no baseline and **silently skips the Sysmon export for the whole run** (582 events instead of about 625, no error anywhere). Load makes it likelier. |

## Step results

Each step had a check that could fail. All numbers are from this run; nothing is carried over from the spec.

| Step | Check | Result |
|---|---|---|
| 1 Inventory | two ready guests, scheduler settings known | **Pass.** Four ready guests: `win` .10, `lab1` .11, `lab5` .12 (clone of lab3), `lab3` .13 (clone of lab1). CAPE: `machinery = kvm`, `max_machines_count` not overridden (CAPE default 10), `max_vmstartup_count` 5. Tartarus pins with the form field `machine=<label>`, always sent (`backend/app/cape/client.py:70-95`). |
| 2 Two tasks at once | both reported, events like a solo run, no cross-talk | **Pass.** Tasks 387 (lab3) and 386 (lab5) submitted in the same instant: both "found useable machine" within 13 ms, ran about 60 s side by side, `reported` at 14:49:17 and 14:49:32. Events per lane, solo vs parallel: lab3 631 and 618 solo, 618 and 635 parallel; lab5 684 solo, 704 and 698 parallel (see the band below). process 21, file 3, registry 11 in every one; only `network` (background Windows traffic) moves, by up to about 20. Each PCAP holds only its guest's IP plus the gateway `.1` and only its own MAC; each `sysmon.xml` and `defender.xml` carries its own guest's `<Computer>`; each task's `cuckoo.log` holds only its own ResultServer lines. |
| 3a Isolation to the internet | both still blocked | **Pass.** Probes from inside each guest to 8.8.8.8:853/443 and 93.184.216.34:81 connect, but only to INetSim (the rooter DNATs every TCP/UDP/ICMP of each guest IP to `192.168.150.1`, rules written per IP for both guests at once); a capture on `eth1` during the probes held two docker mDNS packets and nothing from a guest. |
| 3b Isolation between guests | guest A cannot reach guest B | **FAIL.** From lab3 to lab5 and back: TCP 8000 (CAPE agent), 445, 135 connect; ICMP echo answers; the SYN/SYN-ACK is in `cross.pcap`. Causes: `tt-guest` is a plain bridge, `br_netfilter` is not loaded (`/proc/sys/net/bridge` absent) so iptables never sees bridged frames, and libvirt's own `LIBVIRT_FWX -i tt-guest -o tt-guest -j ACCEPT` would allow them if it did. The rooter even adds `CAPE_ACCEPTED_SEGMENTS -s <guest> -i tt-guest -o tt-guest ACCEPT` per guest. The guests' Windows firewall does not stop it. |
| 3c The fix | blocked both ways, host paths intact | **Pass (measured on the running taps).** `bridge link set dev vnet4 isolated on` and `vnet5` (kernel 7.2, iproute2): lab3 to lab5 8000/445/135 and ping all fail, lab3 and lab5 to `.1:2042` (ResultServer) and `.1:80` (INetSim) and to the DNATed "internet" still connect, the host reaches both agents. libvirt 10.0 accepts the declarative form: `virsh define` of a throwaway domain with `<port isolated='yes'/>` under `<interface>` kept it in the XML (domain removed again). The tap devices are recreated at every start, so the flag must come from the domain XML (or a hook), never by hand. Not yet measured: that a snapshot revert (restore from the memory state) re-applies it; task 3.0's check does. |
| 4 What breaks | see the table below | |

### Step 4 in detail

| Area | Result |
|---|---|
| ResultServer | **Holds.** One listener on `192.168.150.1:2042`; `ss` shows one connection per guest source IP; CAPE maps stream to task by source address, which is why duplicate guest IPs are refused by the engine (already so). |
| Analysis folders | **Holds.** `storage/analyses/<CAPE task id>`; ids are global and unique; Tartarus' `analysis.cape_task_id` is what reaches them. No collision, each folder complete. |
| Scheduler | **Holds.** Three tasks at once (lab3, lab3, lab5): the two on different guests ran together; the second lab3 task stayed `pending` while lab3 was busy (it was not moved to lab5), and started 1 s after the first lab3 task became `completed`, before that one was `reported`. CAPE queues per pinned machine by itself. |
| Snapshot revert | **Holds.** Both guests revert at once every time (`Starting analysis on guest` 0.3 to 0.6 s apart). One slow start of 11 s was seen (P-2). |
| Rooter / PCAP | **Holds.** Rules per guest IP, sniffer `tcpdump` per task with a `host <ip>` filter; the mid-run listing shows both sets, and the second task went on to finish normally after the first one's route was disabled (387 at 14:49:07, 386 ended 14:49:16; 395 at 15:10:01, 396 ended 15:10:12); the rules were not listed again after the first disable. |
| VNC / desktop ports | **Holds.** libvirt autoport gave 5900 (lab5) and 5901 (lab3) at once, QEMU listening on 127.0.0.1, CAPE recorded `vnc_port=` in each task's options even for non-interactive runs, and the backend reads exactly that (`app/desktop/vnc.py`, `admission.py:99-105`). A port is reused by the next guest to start; the tunnel re-checks the analysis' status every 2 s (`ws/desktop.py:69`), so the window in which a closed analysis' tunnel could land on another guest's screen is that interval. Two real tunnels were not opened (task 3.3's proof does). |
| Control service, per guest | **Holds.** `POST /tasks/{id}/finish {"guest":"lab3"}` ended only lab3's run (lab5 kept running to its own end). `POST /memory/{id}/analyse` on two 4 GiB dumps at once: both `200`, 6.0 s and 7.7 s (about 4 to 5 s alone), each with its own pids; the lock is per task id (`memory_logic.py:158-230`). |
| Memory dump on both | **Holds.** Two parallel `memory=1` runs (392, 393): dumps of 4,294,776,995 bytes each, written 10 s apart (the first while the other guest was still running), both `reported`. Truly simultaneous dumps were not forced; a libvirt `coreDump` is 1 to 2 s. |
| Event-log export (`event_logs`, baseline per record id) | **Holds with a gap.** State is per task (`EventLogs.collector` is set in `start()`, `cape/auxiliary/event_logs.py:238`); each run's baseline and export were its own guest's (checked by `<Computer>`). Gap: P-2. |
| Guest clock | **Holds.** CAPE set both guests to the same host time per task ("Date set to 20261021T14:48:15" in both analysis logs); the known 2 h offset between the guest's clock and UTC is per guest and read from each task's own `cuckoo.log`, which holds only that task's lines. No skew between the two guests. |
| **Interactive runs lose the event-log exports (not caused by parallelism)** | After an interactive analysis ends, the guest agent's `/execute` hangs (even `cmd /c echo hi`; `/status` still answers), so both exports time out (120 s + 30 s), the run takes 2.5 min longer to report and has no `sysmon.xml` or `defender.xml`. Seen in tasks 389, 388, 390, 391 (two guests) and 394 (**alone, ended by /finish**), never in a non-interactive run (384 to 387, 392, 393, 395, 396, 398, 399 exported in seconds; 397 is P-2, a different failure). Probes, the isolation flag and `memory=1` were ruled out by run 3 and run 4. S1's interactive run (RB3) exported fine with an earlier version of the module; nothing since has checked it. Side finding S-1, to be handled outside wave 3 (see task 3.8). |

### Event-count band

| Guest | Solo | Parallel |
|---|---|---|
| lab3 | 631 (task 384), 618 (398) | 618 (387), 635 (395) |
| lab5 | 684 (385), 688 (399) | 704 (386), 698 (396) |

Through Tartarus itself (Sigma rules, live collection) the same sample gives 626 events on lab3 and 709 on lab5 (analyses
384 and 385, run one after the other as the runner does today: 385 stayed `queued`, position 1, until 384 was `done`, then
started 2 s later). Those include detection events, so the proof in 3.6 compares Tartarus solo against Tartarus parallel,
not against the offline counts above.

Task 397 (lab3, waited pending then ran) had 582 events for the P-2 reason, not the band. Lanes `process`, `file` and
`registry` are identical in every other run, `api` stays within 465 to 472, `network` varies 91 to 197 with the guest
(Defender on adds about 60). The proof in 3.6 should therefore assert: same lane counts for `process`, `file`,
`registry`; `api` and `network` within 10 % of a solo run of the same guest; no `sysmon` loss (the `sysmon.xml` exists).

## Failure modes

| # | Mode | Seen | Handled by |
|---|---|---|---|
| F1 | Guest A reaches guest B's agent, SMB, RPC, ping | yes, both ways | 3.0 |
| F2 | `event_logs.start()` finds no agent, Sysmon export skipped silently | once in 15 runs (task 397) | 3.1b |
| F3 | `cape` restart (registering or deleting a guest) kills every running task; `restart_cape` also runs `pkill -x tcpdump` (`cape/guest_engine/host.py:114-118`), cutting every sniffer | by reading, matches S0b | 3.4 keeps the backend gate (`api/dependencies.py:56`) and names the blocking analyses; the shell `guest-build` bypasses it and stays documented |
| F4 | A queued analysis whose guest is busy blocks an idle guest's analysis behind it | by reading | 3.1 |
| F5 | Two analyses ingest in one runner tick: the second waits for the first's memory step and index, delaying its interactive deadline | by reading (`runner.py:523-560` awaited inside the tick) | 3.1 |
| F6 | Two memory-dump analyses each pass the room check alone but not together (`memory_disk.py:44-58` is per analysis; CAPE silently skips the dump below its 50,000 MB floor and the analysis still ends `done`) | by reading | 3.1 |
| F7 | Interactive runs lose the event-log exports and take 2.5 min longer to report | yes, solo too | 3.8 |
| F8 | A leftover `win2` libvirt domain (shut off, not registered) exists on the host | yes | none (harmless; the engine ignores it) |

Not exercised: more than three tasks, two interactive desktops open in a browser, a Linux guest, a build or clone
while another guest runs (the gates forbid it), and `max_vmstartup_count` pressure (5; at most 5 guests exist).

## Where the code assumes one running analysis

Ordered by wave-3 task. Anything not listed was read and is already per analysis.

### 3.1 Runner and repository

| Where | What it assumes |
|---|---|
| `backend/app/analyses/runner.py:131` | docstring: "one at a time and follows the active one" |
| `backend/app/analyses/runner.py:163`, `624-647` | `_collecting: int | None` is one slot for the live collector; `_start_live_if_running` skips when it is set to this id, `_stop_live` clears it. Becomes a set of ids (the manager underneath is already keyed) |
| `backend/app/analyses/runner.py:219-237` | `run_once` runs `_tick` once per kind; `_tick` asks `get_active_analysis` (one row) and either follows it or starts the next, never both |
| `backend/app/analyses/runner.py:239-246` | `_start_next` claims the oldest queued row without looking at its guest |
| `backend/app/analyses/runner.py:523-560` | `_ingest` awaits the memory step (`self._memory.run`, `:534`, a control-service call that takes seconds) and the index inside the tick, holding up the tracking of every other analysis |
| `backend/app/db/analysis_repository.py:179-189` | `get_active_analysis` has `.limit(1)` |
| `backend/app/db/analysis_repository.py:201-210` | `get_oldest_queued_analysis` ignores the guest in `options["guest"]` |
| `backend/app/db/analysis_repository.py:213-231` | `queue_positions` partitions by kind only: with several guests the position must be among the analyses waiting for the same guest |
| `backend/app/db/analysis_repository.py:262-282` | `begin_reingest` requires that no analysis at all is active (the runner follows one); with several this stays a safe rule but its message (`api/analyses.py:347`) must stop saying "another" |
| `backend/app/analyses/guest_choice.py:75-80` | the default guest is the preferred or first ready one, busy or not, so two default-guest submissions queue behind each other while another guest idles |
| `backend/app/analyses/submission.py:137-151`, `memory_disk.py:44-58` | the room for a dump is judged for this analysis alone (F6) |
| `cape/auxiliary/event_logs.py:238-248` | `start()` reads the code page and baselines once with `CONNECT_TIMEOUT_S = 5`, no wait for the agent (F2) |
| `docs/specs/backend.md:65` and `docs/specs/cape-integration.md:369-370` | "the runner follows one at a time", "two guests never run together" |

### 3.2 Live manager and collector

Nothing assumes one analysis. `LiveCollectionManager._collectors` is a dict by analysis id (`live/manager.py:31`),
`LiveCollector` takes its own `analysis_id`, `logs_dir` and index (`live/collector.py:79-107`), `LiveHub._states` is a
dict (`live/hub.py:226`), the WebSocket route is `/ws/analyses/{id}/live` (`ws/live.py`). The only coupling is the
runner's `_collecting` slot above. This task shrinks to a test.

### 3.3 Desktop and admission

Also per analysis: `AnalysisResolver(lookup, viewer, analysis_id)` (`desktop/resolver.py:50-75`), the VNC port from the
CAPE task (`desktop/admission.py:74-105`, `vnc.py:1-17`), the tunnel's status re-check (`ws/desktop.py:69`). The
guest-build desktop is a separate route by guest name. Two points to test, no code assumed wrong: `VNC_HOST =
"127.0.0.1"` (`tunnel.py:19`) is right because `guacd` runs in the `cape` container where QEMU listens; and the
2 s window above.

### 3.4 Gates

`has_analysis_needing_a_guest` is `exists()` over queued, starting and running runs (`analysis_repository.py:192-198`)
and `require_no_analysis_needing_a_guest` raises 409 with a fixed text (`api/dependencies.py:56-67`); build, resume,
restart, continue, cancel, clone, delete and check all call it (`api/guests.py:79,115,130,146,162,189,205,224`). That
already works for any number of analyses. `choose_guest(gate=True)` refuses every submission while a guest is
`building` or `testing` (`guest_choice.py:10-14,35-49`), also fine. What is missing is a test with two running and the
text naming them. `GUEST_NEEDING_STATUSES` (`analysis_repository.py:27-31`) leaves out `processing` and `ingesting`,
correct because only `cape` (the scheduler) is restarted, not `cape-processor`.

### 3.5 Frontend and header

| Where | What |
|---|---|
| `frontend/src/layouts/MainLayout.vue:106-108` | the header's `LIVE #42 01:12` chip and queue count are "deferred": nothing to make per-analysis, it has to be built |
| `backend/app/api/system.py:15-20` | only `/system/health`; `GET /system/queue` is in the spec (`docs/specs/backend.md:52`) but not built, and `/ws/system` has no `queue` push (`ws/system.py:47`). The chip needs `{running: [{id, guest, filename, elapsed_s}], queued}` |
| `frontend/src/pages/DashboardPage.vue`, `stores/analyses.ts` | list, polling and `queue_position` are generic; the position's meaning changes with 3.1 |
| `frontend/src/components/SubmitDialog.vue`, `composables/use-guest-choice.ts` | the guest list does not say a guest is busy; with parallel runs the choice matters |
| `LiveDesktopSlot.vue`, `use-live-analysis.ts`, `use-desktop-session.ts` | already take the analysis id from the route; nothing global |

### Already per guest, no change

`analyses/guest_badges.py:7-21` (a map by guest name), the finish route and control service (`POST /tasks/{id}/finish`
with the guest), the memory routes (per task), `selftest_runner` (queues an ungated analysis on a `testing` guest;
builds and analyses exclude each other first, so it is still alone), the sample store, the event index per analysis.

## Rewritten wave 3

The table now in [the plan](../m9-beyond-one-run.md#wave-3-parallel-analyses-after-spike-p3) replaces the old 3.0 to 3.6;
tiers follow rule 5 (the extreme tier is Sonnet with a notes file and a check the planner re-runs).
