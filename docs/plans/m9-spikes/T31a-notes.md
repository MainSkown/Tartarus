# T31a notes: runner and repository for several analyses

Task 3.1a of [the plan](../m9-beyond-one-run.md).

## Done
- Repository: `get_active_analyses` (all, oldest first), `get_oldest_startable_analysis` (oldest queued row whose
  guest has no active analysis; analyses with no guest, i.e. imports, share one slot per kind), `queue_positions`
  partitioned by kind and guest, `begin_reingest` keeps its gate.
- Runner: `_collecting` is a set; each active analysis is followed in its own task (`_followers`); the loop does not
  wait for them, a nudge that meets a task in progress makes it follow once more; `run_once` waits for the tasks it
  started; `stop` waits for them within `shutdown_patience`, then cancels. Starting stops after a row that went back
  to the queue (unreachable), so no later row starts ahead of it.
- Re-ingest 409 message no longer says "another".
- Checks: `tests/analyses/test_runner_parallel.py`; the slow-ingest test fails when the loop awaits the follower
  (mutation tried); repository tests for busy-guest skip and per-guest positions.

## Next
- 3.1c (idle-first default guest) and 3.2 build on this.
