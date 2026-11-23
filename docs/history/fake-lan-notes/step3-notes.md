# Fake LAN Step 3 notes: control-service endpoints

Resume file for an interrupted run (done / running / next). Brief: plan "Step 3" plus the contract the backend codes against
(`backend/app/guest/client.py`, `backend/app/analyses/lan_sessions.py`).

## Plan (each sub-step ends in a check that can fail)
1. `guest-firewall` subcommands `lan-open` / `lan-close KEY` / `lan-list` under the same flock. Check: `test_guest_firewall_command.py`.
2. Daemon heartbeat `<root>/alive` (`Layout.alive_file`, `daemon.py`). Check: `lan-sim/tests/test_daemon.py`, `test_lan_session.py`.
3. `analysis_files.place_once` (first copy wins, via link, capped, no symlink followed). Check: `test_analysis_files.py`.
4. `bin/lan_logic.py`: health, presets, list, open, close with injected runner / clock / sleep. Check: `test_lan_logic.py`.
5. Routes in `guest-control`. Check: `test_guest_control_lan.py`, existing control tests.
6. Whole cape suite, ruff check and format.

## Done
- 1: `guest-firewall` `lan-open` / `lan-close KEY` / `lan-list` (tests seen failing, then 40 pass in `test_guest_firewall_command.py`); `session_from_dict`
  made public in `lan_firewall.py` (the ledger and the command share it).
- 2: heartbeat. `Layout.alive_file` in `lan_session.py`, `Daemon._beat()` each poll, removed on stop. `test_daemon.py` 35 pass.
- 3: `analysis_files.place_once` (link into place, first copy wins). 26 tests in `test_analysis_files.py`.

- 4: `bin/lan_logic.py` (tests first: `test_lan_logic.py` 70 cases). Seven mutations of it (no firewall close on a failed open, no redaction,
  copy after the firewall close, republish on re-open, no cleanup, no firewall open, overwrite instead of link) each fail tests.
- 5: routes in `guest-control` (`test_guest_control_lan.py` 30 cases); `test_guest_control.py` copies `lan_logic.py` for its script-launch tests.
- 6: whole cape suite 3161 passed, 45 skipped; ruff check and format clean on every touched file; `Makefile` and `ci.yml` ruff lists gained `bin/lan_logic.py`.

## Running
- nothing

## Next
- the planner reads the diff. Real stack is Step 5 and 12: the daemon heartbeat on a real volume, `guest-firewall lan-*` with real nft, the `/run/lan-sim` ownership.

## Decisions
- `GET /lan/sessions` answers the union of the keys in the session directory and in the firewall ledger (read through `lan-list`, under
  the lock), so a half-open session after a restart (ledger gone, file left, or the reverse) is visible and the backend's reconcile
  closes it. `DELETE` closes both halves whatever is left.
- Re-opening a key with the same guest and preset runs `lan-open` again (idempotent) so a ledger lost in a restart is healed; it does not
  publish the file again (that would make the daemon rebind).
- `lan-list` is a third subcommand beyond the brief, so the listing reads the ledger under the lock without `guest-control` knowing the ledger's path.
- Answers carry `warnings` (a list) only when a step went wrong without failing the call (daemon did not confirm `closed`, copy failed); the
  backend's model ignores unnamed fields.
- A staged log that could not be copied for a reason a retry could mend (a full disk, too large) is kept; every other close deletes it.
