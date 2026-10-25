# S1 findings: ending an interactive run from the backend (`+60s`, decision 5)

Spike on the real stack, 2026-10-17, guest `lab3` (Defender off), sample `benign.exe` (the self-test sample,
copied out of the cape image), `route inetsim`, `package exe`, `interactive true`. No product code was changed.
All times are UTC. Every analysis the spike created (235 to 243) was deleted afterwards; the stack was left as
found (10 analyses, guests `win`, `lab1`, `lab3`, `lab5` ready). The scratch driver and the raw per-run data
(`run-*.json`, `collect-*.json`, `live-*.json`, `cape-log-*.txt`) are in the session scratchpad, not in the repo.

## Verdict

**GO on "submit with `timeout=1200` and end it from the backend through `POST /finish`".** A run ended that way
is as complete as one CAPE ends itself: same status path, same signatures, detections, techniques, score,
artifact kinds, network tables, report and live feed; every count that differs is inside the spread between two
identical CAPE-ended runs (A against A2). Two things in decision 5 must change, because they were measured wrong
in the plan:

1. **The reference point must not be `started_at`.** CAPE's own timeout counts from the sample's execution in the
   guest, which is 20.6 to 24.5 s after `started_at` (monitor up 15.3 to 19.6 s after it). A deadline of
   `started_at + timeout` gives the analyst `timeout - ~22 s` of sample runtime (a 60 s deadline would be about
   38 s). Count from the monitor start (below).
2. **The cap is not `started + 1200 - small margin`, it is a measured number** (below).

## Method

A scratch driver (Python, public API only) submitted the multipart request, polled `GET /api/analyses/{id}` every
0.5 s, ran `scripts/lib/live_client.py live` against the live socket for the whole run, and watched
`/cape-storage/analyses/<task>/logs/*.bson` in the backend container (the exact test `_monitor_started` makes)
to timestamp the monitor without calling `/finish`. After `done` a collector read the analysis, processes,
network, registry, detections, artifacts, screenshots, pcap, events search/facets for each run; CAPE's
`analysis.log` of each task was read from the cape container for the guest-side times. Runs, one at a time:

| Run | Purpose | options.timeout | How it ended |
|---|---|---|---|
| A, A2 | reference: CAPE's own timer | 120 | left alone |
| B | run B as specified | 1200 | `POST /finish` 120 s after the first `logs/*.bson` |
| B2 | run B with the guest runtime matched to A | 1200 | `POST /finish` 128 s after the first `logs/*.bson` |
| W1, W2, W3 | the 409 window | 1200 | `POST /finish` polled every 0.5 s from `running`; the first 200 ends the run |
| R | backend restart | 1200 | `docker compose restart backend` 40 s after the first bson, `POST /finish` 85 s after it |
| L | CAPE's own limit | 1200 | left alone |

B used the 120 s the task set; the guest's sample ran 114.3 s against A's 122.5 s, so B2 (finish at +128 s) was
added to compare like with like. A2 was added to measure how much two identical CAPE-ended runs differ.

## Measured numbers

Seconds after the analysis's `started_at` (CAPE's `started_on`, whole seconds, so each figure carries up to
1 s of truncation; polling adds up to 0.5 s). "running" is when my poll first saw it.

| Run | Analysis id | CAPE task | started_at | running | first bson | finish 200 | left `running` | `done` |
|---|---|---|---|---|---|---|---|---|
| A | 235 | 223 | 12:58:46 | 3.1 | 19.6 | | 159.6 | 244.4 |
| A2 | 242 | 230 | 13:29:11 | 2.3 | 15.3 | | 150.5 | 234.8 |
| B | 236 | 224 | 13:03:39 | 3.0 | 18.1 | 138.6 | 143.1 | 226.4 |
| B2 | 240 | 228 | 13:16:44 | 1.9 | 16.4 | 144.6 | 148.1 | 231.3 |
| W1 | 237 | 225 | 13:09:36 | 3.2 | 17.5 | 17.5 | 29.2 | 97.2 |
| W2 | 238 | 226 | 13:12:34 | 2.2 | 16.0 | 16.0 | 30.7 | 94.1 |
| W3 | 239 | 227 | 13:14:29 | 2.7 | 15.8 | 16.0 | 30.7 | 94.1 |
| R | 241 | 229 | 13:22:20 | 2.6 | 16.3 | 101.6 | 106.2 | 190.4 |
| L | 243 | 231 | 13:35:01 | 2.4 | 15.8 | | 1244.5 | 1368.1 |

Guest side, from CAPE's `analysis.log` (seconds after `started_at` unless noted):

| Run | sample executed | CAPE "timeout hit" | "Shutting down package" | guest "Analysis completed" | sample runtime (exec to shutdown) |
|---|---|---|---|---|---|
| A | 24.5 | 147.0 (exec + 122.5) | 153.0 | 153.4 | 128.5 s |
| A2 | 20.6 | 143.2 (exec + 122.6) | 144.3 | 145.3 | 123.7 s |
| B | 23.9 | none | 138.3 | 139.2 | 114.4 s |
| B2 | 21.3 | none | 143.8 | 144.1 | 122.5 s |
| W1 / W2 / W3 | 23.1 / 21.8 / 21.6 | none | 26.1 / 24.9 / 24.6 | 26.2 / 25.8 / 25.5 | 3.0 s each |
| L | 21.7 | 1223.7 (exec + 1202.1) | 1239.8 | 1240.3 | 1218.1 s |

Result per run, through the public API:

| Run | status | events | processes | api / file / network / process / registry events | dns / http / flows / hosts | screenshots | pcap bytes | detections (signatures) | score | `duration_s` |
|---|---|---|---|---|---|---|---|---|---|---|
| A | done | 4415 | 7 | 4171 / 2 / 202 / 18 / 22 | 3 / 2 / 196 / 5 | 2 | 343499 | 14 (13) | 6.0 | 157 |
| A2 | done | 4175 | 6 | 3930 / 2 / 204 / 17 / 22 | 3 / 2 / 198 / 5 | 2 | 351914 | 14 (13) | 6.0 | 149 |
| B | done | 4184 | 6 | 3940 / 2 / 203 / 17 / 22 | 3 / 2 / 197 / 5 | 3 | 348464 | 14 (13) | 6.0 | 141 |
| B2 | done | 4311 | 7 | 4072 / 2 / 197 / 18 / 22 | 3 / 2 / 191 / 5 | 4 | 336035 | 14 (13) | 6.0 | 147 |
| R | done | 4148 | 6 | 3917 / 2 / 190 / 17 / 22 | 3 / 2 / 184 / 4 | 2 | 325421 | 14 (13) | 6.0 | 104 |
| L | done | 28231 | 45 | 27484 / 88 / 563 / 65 / 31 | 4 / 2 / 556 / 8 | 3 | 985266 | 21 (20) | 7.0 | 1243 |
| W1 / W2 / W3 | done | 401 / 402 / 408 | 3 | about 345 / 2 / 40 / 12 / 3 | | 2 | about 62 to 71 kB | 11 | 6.0 | 28 / 29 / 28 |

Every one of these runs ended `done` with `error: null`, a non-null `summary`, a readable pcap, a screenshot
list and the live socket closing `1000` after a `done` status message.

## (1) Equivalence: is run B as complete as run A?

**Yes, within run-to-run noise; no difference was found that comes from how the run was ended.**

Identical in A, A2, B and B2: status path (`starting, running, processing, ingesting, done`; the runner skipped
`ingesting` in some polls only because it lasted under 0.5 s), `error`, score 6.0, max severity `high`, the same
13 signatures, the same 12 ATT&CK techniques, the same 14 detections (the 13 signatures plus the Tartarus
self-test registry rule), the same artifact kinds and names (`benign.exe` dropped, `cmd.exe` and `benign.exe`
procdumps, `tartarus-benign.txt`), `files_written` 7, `registry_keys_written` 16, DNS 3, HTTP 2, 5 hosts,
`simulated` true, pcap and report present, live feed reached `done`. The guest's shutdown path in the analyzer
log is the same (terminate event per process, "Shutting down package", auxiliary modules, dropped files upload,
"Analysis completed").

Differences, all listed:

- **The analyzer log has no "Analysis timeout hit, terminating analysis" line in B/B2** (the finish folder is
  noticed instead); nothing in the API shows it.
- **Counts differ, but A against A2 differs as much as A against B2**: events 4415 / 4175 / 4184 (B) / 4311 (B2),
  processes 7 / 6 / 6 / 7 (the WmiPrvSE and svchost instances Windows starts on its own come and go), network
  flows 196 / 198 / 197 / 191, pcap 343 / 352 / 348 / 336 kB, `duration_s` 157 / 149 / 141 / 147. The sample
  itself (`benign.exe`, `cmd.exe`) and its file, registry, DNS and HTTP effects are identical every time.
- **B ran shorter than A because of the reference, not the mechanism**: finishing 120 s after the first bson gave
  the sample 114.3 s against A's 122.5 s (the sample starts 4.9 to 5.9 s after the first bson). B2, finishing at
  +128 s, ran the sample 122.5 s, equal to A.
- **Screenshots: A 2, A2 2, B 3, B2 4** (R 2, L 3). Run B-style runs had more, not fewer; four-versus-two samples
  are too few to call it systematic. It is not a loss.

Not a difference: a run ended through `/finish` at 17 s (W) still produces a normal `done` analysis with a
report (see 2).

## (2) The 409 window

`POST /finish` stops answering 409 (the backend's "any `logs/*.bson`" test) **16.0, 16.0 and 17.5 s after
`started_at`** in W1 to W3, which is **13.8, 13.3 and 14.3 s after my poll first saw `running`**. The first
bson (the same test, timed by a separate probe) appeared 15.3 to 19.6 s after `started_at` over all nine runs
(median 16.3). So the plan's "about 25 s" is too long for this guest; the window is 13 to 15 s from `running`,
15 to 20 s from `started_at`. It also ends before the sample starts: the sample executes 20.6 to 24.5 s after
`started_at`, 4.9 to 5.9 s after the first bson.

What happens when the call is accepted at that moment (W1 to W3): the finish folder is created, the analyzer
picks it up as soon as its main loop starts, and runs the sample for only 3.0 s and shuts down normally. The
analysis ends `done` with a report (about 400 events, 3 processes, score 6.0). No hung guest, no `failed`.
The 409 guard before the monitor was not tested by finishing earlier (that is the case the code comment warns
about; I did not try to reproduce it, see "Not verified").

A deadline of 60 s (the minimum) therefore falls well after the window whichever reference is used: the monitor
is up by at most 19.6 s after `started_at`. If the reference were `started_at`, a 60 s deadline would still pass
the guard, but would leave the sample about 36 to 39 s. **Earliest safe moment to call finish: the first
`logs/*.bson` exists, 15.3 to 19.6 s after `started_at` (so a deadline never needs to be set earlier than
`started_at + 20 s`); the runner should still treat 409 as "try again on the next poll".**

## (3) End latency after the finish call is accepted

| Run | accept to status leaves `running` | accept to `done` | note |
|---|---|---|---|
| B | 4.6 s | 87.8 s | late finish (sample had run 114 s) |
| B2 | 3.6 s | 86.7 s | same |
| R | 4.6 s | 88.8 s | same, after a backend restart |
| W1 | 11.7 s | 79.7 s | finish accepted before the sample started |
| W2 | 14.7 s | 78.1 s | same |
| W3 | 14.7 s | 78.2 s | same |

For a finish at a real deadline (B, B2, R): **min 3.6, median 4.6, max 4.6 s** to leave `running`
(n=3), and 86.7 to 88.8 s to `done` (processing of a 2.5-minute run took about 83 s). When the call is accepted
before the sample has started (W) it is 11.7 to 14.7 s, which is the "11 to 18 s measured earlier"; that does
not apply once the sample has run. For comparison, CAPE ending a run itself: "timeout hit" to `processing` 12.6 s
(A), 7.3 s (A2); in L 20.8 s because shutting down 45 processes took 16 s. A backend-ended 1200 s run has not been
measured; I expect the same 16 s shutdown, but this is not verified.

The countdown should read the remaining time to the deadline and stop at 0 with "ending". The status leaves
`running` about 4 to 5 s later (up to about 20 s for a long, busy run); do not add that to the countdown.

## (4) CAPE's own limit (run L, `timeout 1200`, never finished)

CAPE's analyzer fired its timeout 1202.1 s after the sample was executed in the guest, which is **1223.7 s
after `started_at`**; the status left `running` **1244.5 s after `started_at`** (20.8 s later, because the
guest took 16 s to shut down 45 monitored processes, plus about 4 s). The analysis ended `done` (28231 events,
45 processes, score 7.0, 21 detections).

So CAPE's own timer fires at `started_at + 1222.6 to 1226.7 s` (exec 20.6 to 24.5 plus 1202.1; the
nine-run spread of exec is 20.6 to 24.5) and at `first bson + 1207 to 1208 s`. An extension may go as far as
`started_at + 1200 s` with at least 22 s to spare (and still about 18 s after allowing the runner's 2 s poll and
about 1 s for the analyzer to see the folder). Beyond that CAPE ends the run itself, which is harmless (a normal
`done` run, a later `/finish` would answer 409 "already over") but the analyst's deadline would not have been
honoured and the countdown would have lied.

## (5) Backend restart

Run R, `timeout 1200`, `docker compose restart backend` 40 s after the first bson (the `restart` returned after
5.3 s):

- The API answered 502 (nginx) for about 1.5 s (3 polls), then 200 again; the analysis was still `running`.
- The live socket closed with 1012; the client reconnected once per second (7 refused attempts while nginx had
  no backend) and attached again 8 s after the close; it received `status running` and `counts` again and
  closed 1000 after `done`.
- `POST /finish` 45 s after the restart answered 200 and the run ended exactly like B (left `running` 4.6 s
  later, `done`, 4148 events, 6 processes, score 6.0).

So the runner picked the active analysis up again from the database, kept following it, and the finish path
works after a restart. That is what the planned deadline check relies on. What was not exercised: the deadline
itself being enforced after a restart (it does not exist yet), and whether events produced during the
roughly 8 s outage reach the reattached live view (the live client records the counts and statuses again; I did
not diff the events).

## Recommendation for decision 5

**Go.** Amend decision 5 as follows.

- **Submit:** an interactive task goes to CAPE with `timeout=1200` whatever `options.timeout` says (measured: the
  run ends at the backend's finish call with no loss against a CAPE-ended run).
- **Reference point:** do **not** use `started_at`. Set `deadline_at` when the runner first sees the monitor
  started (the `logs/*.bson` test `_monitor_started` already makes; the runner has `cape_storage_path`), to
  `that moment + options.timeout`. This is the moment finish becomes acceptable, so the deadline can never fall
  inside the 409 window, and it is 4.9 to 5.9 s before the sample executes, so the analyst gets
  `timeout - ~5 s` of sample runtime (B2 at monitor + 128 s matched A's 122.5 s). If a storage probe in the
  runner is unwanted, the cheaper approximation is `started_at + 22 s + options.timeout` (the sample start was
  20.6 to 24.5 s after `started_at` on `lab3`, n=9; another guest or a slower revert was not measured).
- **Margin before 1200:** a deadline must not exceed `started_at + 1200 s` (CAPE's own timer fires at
  `started_at + 1222.6 s` at the earliest, measured; 22 s of margin, about 18 s after the poll and the
  analyzer's pickup). Expressed from the monitor reference it is `first bson + 1190 s`. The cap is therefore
  `min(requested, 1190 s after the monitor)`, and the button says "cannot extend past 20 minutes" when disabled.
- **Enforce:** when `now >= deadline_at` and `running`, call the same finish path; on 409 retry at the next poll
  (2 s). Expect the status to leave `running` 3.6 to 4.6 s later (up to about 20 s for a long, busy run).
- **Countdown:** show `deadline_at - now`, switch to the warning colour for the last 30 s as planned, and at 0
  show "ending" until the status leaves `running`; do not add the end latency to the number. After the
  status leaves `running` the page shows processing as today (about 83 to 88 s for a 2.5-minute run, 120 s for
  a 20-minute one).
- **Restart:** no extra component is needed; the runner re-reads state after a restart (R).

## Not verified

- A backend-ended run **at 1200 s** (or any long, busy run): the guest shutdown there took 16 s when CAPE ended
  it (L); the finish path was only measured on runs of about 2 to 2.5 minutes.
- The deadline being enforced by the runner after a backend restart: only that tracking, the live view and
  `POST /finish` survive a restart was measured.
- Events produced during the live view's outage after a restart (not compared with the final index).
- Ending a run **before** any monitor exists (the 409 guard's reason): not reproduced, on purpose.
- Other guests (`win`, `lab1`, `lab5`) and other samples: all runs used `lab3` and the one benign sample, which
  exits at once and leaves the guest idle. A real sample that keeps the CPU busy could shift the monitor and
  shutdown timings, and the lead from `started_at` to the sample start depends on the guest's boot.
- Why the screenshot counts differ (2, 2, 3, 4): not investigated; no run had fewer than A.
- `started_at` is whole seconds (CAPE's `started_on`); every offset from it has up to 1 s of error, and the
  polling error is up to 0.5 s. Run R's guest log was not saved before its analysis was deleted, so R has no
  guest-side times.
- The time the sample's own monitor (its pid's bson) appears, as opposed to the first bson of any process
  (explorer.exe's, found 4.9 to 5.9 s before the sample starts); `scripts/lib/e2e-finish.sh` uses the sample's.
- Only one CAPE-ended 1200 s run (L) was made; its 1223.7 s should be read as one sample of a figure that
  varies with the guest's boot lead (20.6 to 24.5 s in the other runs).
