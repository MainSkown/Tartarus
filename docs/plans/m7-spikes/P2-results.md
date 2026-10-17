# P2 results: the `+60s` extend and the backend-ended deadline on the real stack

Run on 2026-10-17 on the rebuilt stack (API http://127.0.0.1:8080/api), guest `lab3` (Defender off), sample
`benign.exe` (the S1 copy; no other sample was run), route `inetsim`, package `exe`. Runs were one at a time.
All times are UTC. Every analysis the spike created (257 to 261) was deleted afterwards with
`DELETE /api/analyses/{id}`, and the stack is as it was found: the same ten analyses remain (45, 144, 193,
201, 224, 227, 228, 229, 230, 231, all `done`), no guest was touched, and no product, docker or compose file
was changed. The only restart was R4's `docker compose restart backend`. Nothing was committed.

## Verdict

**R1, R2, R3 (a to e) and R4 PASS on the numbers below.** No requirement failed. Several things surfaced that the
spec did not ask about, and they are listed under Anomalies: one logged finish-path failure in R1 (a 502 from
the guest agent, retried), processing times that are 10 times shorter than S1 measured, and the extra detections
in the 240 s run (R2), which were not attributed.

## Method

- **Driver:** `scratchpad/p2/p2_run.py` (modes `r1`, `r2`, `r4`, `r3a`, `r3b`), adapted from the S1 driver. It
  submits the sample (multipart, same options as S1 plus `interactive`), polls `GET /api/analyses/{id}` every
  0.5 s, and makes the calls its mode needs. Its `extend` and `finish` calls go through the public API only.
- **Live socket:** `scratchpad/p2/live_client_p2.py`, a copy of `scripts/lib/live_client.py` that also keeps
  `remaining_s`, `elapsed_s` and a wall-clock stamp on every status message (the repo copy drops `remaining_s`).
  The repo file is unchanged.
- **Monitor time (the reference for "seconds"):** a `docker exec tartarus-backend` loop polls for the first
  `logs/*.bson` in the task folder every 0.1 s. At first detection it records the minimum mtime of the
  `*.bson` files (`find -printf '%T@'`), which is the value `monitor.first_monitor_log_time` returns. Every
  offset below is from that value. It was also checked against `deadline_at`: in R1, R2 and R4 the deadline is
  the monitor value plus `timeout` to within 0.3 microseconds, so the runner's first poll saw the same value.
- **Collection:** `scratchpad/p2/collect.py` (a copy of S1's) reads the finished analysis: summary, processes,
  network, detections, artifacts, pcap, events search and facets. It runs before `DELETE`.
- **Backend log:** `docker compose logs backend`, filtered for WARNING and ERROR from 15:45 on.
- **Raw data:** `scratchpad/p2/out/run-{r1,r2,r4,r3a,r3b}.json` (every poll change, call, restart, and derived
  figure), `run-*.log`, `live-*.json` (the live socket), `collect-*.json`.

## Table 1: runs, analysis ids and timestamps

| Run | Analysis | CAPE task | options | submitted / started_at | monitor (min bson mtime) | deadline_at | deadline - monitor | deadline - started_at |
|---|---|---|---|---|---|---|---|---|
| R1 | 257 | 245 | interactive, timeout 120 | 15:48:43.58 / 15:48:44 | 15:49:02.582 | 15:51:02.583 | 120.000 s | 138.58 s |
| R2 | 258 | 246 | interactive, timeout 120 | 15:51:42 / 15:51:42 | 15:51:58.481 | 15:55:58.481 (+60 at 15:52:28.66, +60 at 15:52:38.84) | 240.000 s | 256.48 s |
| R4 | 259 | 247 | interactive, timeout 120 | 15:56:37 / 15:56:37 | 15:56:52.436 | 15:58:52.436 | 120.000 s | 135.44 s |
| R3b | 261 | 249 | interactive, timeout 1200 | 16:00:25 / 16:00:25 | 16:00:39.231 | 16:20:25 | 1185.77 s | **1200.000 s** |
| R3a | 260 | 248 | non-interactive, timeout 60 | 15:59:20 / 15:59:20 | 15:59:43.344 | none | none | none |

Times relative to the monitor (seconds, from the monitor value; "+" is later):

| Run | deadline first seen by GET | extend calls | status left `running` | `done` | left running minus deadline | done minus deadline |
|---|---|---|---|---|---|---|
| R1 | +1.38 s | none | +130.72 s (15:51:13.30) | +133.77 s (15:51:15.86) | **+10.72 s** | +13.77 s |
| R2 | +0.24 s | +30.18 s (200), +40.36 s (200) | +249.35 s (15:56:07.83) | +258.13 s (15:56:16.61) | **+9.35 s** | +18.13 s |
| R4 | +0.80 s (restart at +0.80, returned +5.60, rc 0) | none (restart only) | +125.88 s (15:58:58.32) | +133.49 s (15:59:05.93) | **+5.88 s** | +13.49 s |
| R3b | +2.15 s | 409 at +2.15 (cap); 422 and 422 and 404 at +2.15; `finish` 200 at +60.51 | +64.58 s (4.08 s after finish) | +72.20 s (16:01:51.44) | n/a (finished early) | n/a |
| R3a | none | 409 at -20.87 (2.57 s after submit, status running) | +30.87 s | +36.96 s | n/a | n/a |

Processing (status `processing` to `done`, from the live socket and the GET polls): R1 3.0 s, R2 8.8 s, R4 7.6 s,
R3b 7.6 s, R3a 6.1 s. See Anomaly 2.

Result per run through the public API (same counts as S1 where the run is comparable):

| Run | status | events | processes | detections (signatures) | score | screenshots | pcap bytes | network flows / hosts | error |
|---|---|---|---|---|---|---|---|---|---|
| R1 | done | 4158 | 6 | 14 (13) | 6.0 | 2 | 347929 | 177 / 5 | null |
| R2 | done | 6025 | 13 | 18 (17) | 6.0 | 3 | 450218 | 259 / 7 | null |
| R4 | done | 4173 | 6 | 14 (13) | 6.0 | 3 | 328415 | 187 / 5 | null |
| R3b | done | 4075 | 6 | 14 (13) | 6.0 | 2 | 205057 | 115 / 4 | null |
| R3a | done | 561 | 2 | 13 (12) | 6.0 | 3 | 123878 | 69 / 4 | null |

S1 comparison: R1 is inside S1's ranges for 120 s runs (events 4148 to 4415, processes 6 to 7, 13 signatures
and 14 detections, score 6.0, screenshots 2 to 4). The "(n)" counts in the detections column are the signatures.

## Answers

**R1: PASS.** The backend alone ended the run.
- `deadline_at` was first seen by GET 1.38 s after the monitor (requirement: within about 5 s).
- It equals monitor + 120 s: the difference is 120.000 s (to 0.3 microseconds).
- The status left `running` 10.72 s after `deadline_at` (requirement: 5 to 15 s).
- It reached `done` with a summary, a readable pcap, 2 screenshots and events and processes in line with S1
  (4158 events, 6 processes). No `finish` or `extend` call was made.

**R2: PASS.** Both extends answered 200 and the deadline moved as required.
- Extend 1 at monitor + 30.18 s: `deadline_at` went from 15:53:58.481 to 15:54:58.481, +60.000 s.
- Extend 2 at monitor + 40.36 s: `deadline_at` went from 15:54:58.481 to 15:55:58.481, +60.000 s.
- The live `remaining_s` jumped by +60 at each extension. Before extend 1 it read 89.91 at +30.09 s; at +31.09 s it
  read 148.91. Left to run down, it would have been 88.91, so the jump is +60.00. Before extend 2 it read 139.91
  at +40.09 s; at +41.09 s it read 198.91, against 138.91 on the trend, so +60.00.
- The run ended at monitor + 240.000 s (the final `deadline_at`). It left `running` 9.35 s after that and reached
  `done` 18.13 s after it, with a summary and a pcap (see Anomaly 3 for the counts).
- During the countdown the live `remaining_s` read 0.0 from +240.16 s until the status changed, which matches the "ending" state.

**R3: PASS on all five refusals.**
- (a) Non-interactive, timeout 60: extend answered 409 "Analysis 260 is not an interactive run: only an
  interactive run can be extended", 2.57 s after submit, while `running`. The run then ended `done` (see Anomaly 5).
- (b) Interactive, timeout 1200: `deadline_at` = `started_at` + 1200.000 s (16:20:25 against started 16:00:25),
  set 2.15 s after the monitor. Extend answered 409 "The run is already at its longest (20 minutes)". Then
  `POST /finish` answered 200 at monitor + 60.51 s and the run went `done`.
- (c) `seconds` 0 and 601 answered 422 with `validation_error`: "Input should be greater than or equal to 1" and
  "Input should be less than or equal to 600".
- (d) Analysis 999999 answered 404 "Analysis 999999 not found".
- (e) Extend on the finished analysis 261 answered 409 "Analysis 261 is done: only a running analysis can be
  extended".

**R4: PASS.** The backend restart did not change the run.
- The deadline was set 0.80 s after the monitor and the restart was issued at once: `docker compose restart backend`
  returned rc 0 after 4.8 s (monitor + 0.80 to + 5.60).
- The API answered 502 on three polls (+6.1, +6.6, +7.1 s), then 200 again. The status stayed `running` throughout.
- `deadline_at` was not changed: the record shows one deadline value, set before the restart, and the same value at
  the end.
- The backend ended the run at the deadline (`left running` +5.88 s after `deadline_at`, `done` +13.49 s), with no
  call from me after the restart.
- The live socket closed 1012 and reconnected seven times (InvalidStatus while nginx had no backend), reattaching
  about 7 s after the close.
- Caveat: the restart came before the sample ran (see Anomaly 4).

## Anomalies

1. **R1: a logged finish failure.** The backend log has one WARNING at 15:51:11.21, which is deadline + 8.6 s:
   "Ending analysis 257 at its deadline failed, retrying: guest control finish_task: HTTP 502: the guest agent is
   unreachable (URLError)". The runner re-sends the finish on every 2 s poll while the run is `running` and past
   its deadline, and it logs only the failures, so the earlier attempts and whether they succeeded are not in the
   log. The status left `running` at deadline + 10.72 s, the largest lag of the three runs that ended by the
   deadline (R2 9.35 s, R4 5.88 s). The 502 is the likely cause of the extra lag, but I did not confirm that. The
   retry worked. No other WARNING or ERROR appeared in the backend log for R2, R4 or R3b.
2. **Processing time is about 10 times shorter than S1 measured.** S1 measured 83 to 88 s from the finish call to
   `done` (processing), and S1's findings rely on that figure. Here it was 3.0 s (R1), 8.8 s (R2), 7.6 s (R4),
   7.6 s (R3b) and 6.1 s (R3a). The results are complete (summary, detections, pcap, screenshots and the events
   index all present, same score and signatures), so this is a timing difference, not a missing result. I did not
   find the cause. If it stands, S1's processing figure is wrong for this stack.
3. **R2's 240 s run has more processes and detections than the 120 s runs.** It had 13 processes against 6, and 18
   detections against 14. The extra processes are Windows background processes (`backgroundTaskHost.exe` four
   times, `WMIADAP.EXE`, `SecurityHealthHost.exe`). The extra detections are `creates_suspended_process`,
   `resumethread_remote_process`, `mountpoint_manager_access` and `per_file_acl_token_check`. The analysis was
   deleted before I read which process each detection points at, so I cannot say whether they come from
   `benign.exe` or from Windows background activity. This matters for a longer run, and it is not verified.
4. **The R4 restart came 0.8 s after the monitor, before the sample ran.** The spec said "once `deadline_at` is set",
   and I followed it literally. In S1 the sample executed 5 to 6 s after the monitor. So R4 proves a restart
   before the sample runs, not a restart in the middle of the sample. It is not a mid-run restart.
5. **R3a (non-interactive, timeout 60) ended at monitor + 30.9 s, not at its 60 s timeout.** It has 561 events and
   2 processes, against about 4100 to 4200 and 6 for the interactive runs. Not part of P2; I did not investigate.
6. **`deadline_at` has whole seconds in R3b** (16:20:25Z). That is expected: `started_at` is whole seconds
   (CAPE's `started_on`), and the cap is `started_at` + 1200.
7. **The live status message carrying the new deadline arrived 0.91 s after the extend call** (R2, extend 1). The
   status comes about once a second, so this does not show whether the push was immediate or on the next tick.
8. **The deadline reference is the stalest log mtime at the first poll.** The runner takes the minimum last-write
   time of the `*.bson` files, not their creation time. In R1 the file that held the oldest mtime at detection had a
   later mtime by the end of the run (the listing at `done` has no entry at the detection value). In R1, R2 and R4
   the deadline still matched the detection value to 0.3 microseconds, so the first poll saw the same file times.
   A log that is rewritten between detection and the first poll would move the reference. Not seen in these runs.

## Not verified

- A restart in the middle of the sample's run (Anomaly 4).
- A run ended by the backend at the cap (`started_at` + 1200 with no finish). R3b was finished at +60 s, so the
  cap-end path was not exercised.
- The clamp: an extend that would pass the cap and is moved down to it (for example 60 s requested with 30 s left
  before the cap). Only the "already at its longest" 409 was tested.
- The number and outcome of the finish attempts before the logged 502 in R1, and when the first accepted attempt
  was (Anomaly 1).
- Why processing took 3 to 9 s here and 83 to 88 s in S1 (Anomaly 2).
- Which process each of R2's extra detections points at, and whether `benign.exe` or Windows causes them (Anomaly 3).
- That the status message is pushed at once on an extend rather than on the next one-second tick (Anomaly 7).
- Events produced during the R4 outage, compared with the index (not compared).
- Other guests and samples: `lab3` and the benign sample only.
- Variance: one run per mode, except the 409 and refusal checks, which are single calls. No repeats were made, so
  there is no spread to set against the numbers above.
- The frontend `+60S` button (outside this spike).
