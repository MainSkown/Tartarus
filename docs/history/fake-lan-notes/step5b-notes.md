# Step 5b notes: three isolation gaps of the lan-sim daemon

Started 2026-11-23. Brief: the Findings list of step5-notes.md. Isolation-relevant; assume the daemon is compromised.

## Done
1. Gap 1: `LAN_SIM_UID = 10001` in `guest_engine/lan_session.py`; `egress.py` renders `meta skuid 10001 ct state new counter reject` as the
   first output rule. Check: test_container_egress.py (failed first on the import; 34 pass, incl. the one test that reads
   docker-compose.yml, lan-sim/Dockerfile and cape/entrypoint.sh and compares them with the constant; it lives in cape/tests because
   backend/ was off limits); `nft -c` through the cape image: rc 0.
2. Gap 2: `lan_session.open_regular_file` / `read_regular_file` (NOFOLLOW|NONBLOCK|CLOEXEC, fstat of the open descriptor, S_ISREG, size
   cap, read bounded from the descriptor), used by `read_status`, `read_session`, `read_heartbeat` and by `analysis_files.place_once`
   (its own `_open_staged` is gone; the exception classes now live in lan_session and analysis_files re-imports them). Tests with real
   FIFOs/symlinks/directories and a thread bound (cape/tests/hostile_files.py): they failed first, and fail again with O_NONBLOCK or
   O_NOFOLLOW removed (checked by mutation). A log that is not a regular file is not copied and is deleted, not kept for a retry.
3. Gap 3: the daemon writes the namespace name (`lan_session.network_namespace()`, `write_heartbeat`, atomic) every poll; `LanSessions.health`
   compares it with its own (injectable) and says "run `docker compose up -d` to recreate it"; an empty heartbeat counts as the wrong one.
   daemon test: the symlink-based "heartbeat cannot be written" test became a directory (atomic_write replaces a link).

4. Docs: security.md (cape container row), architecture.md (lan-sim namespace bullet), compose comment. Suites: cape 3252 passed / 45 skipped,
   lan-sim 858 passed, backend test_lan_sim_service + test_image_pins 19 passed. ruff clean on touched files (two untouched cape test files,
   test_snapshot_step.py and test_windows_profile.py, already fail E501/format on their own).
5. Real stack (2026-11-23, no analysis running, guests `win` and `w10` shut off, none started; images cape and lan-sim rebuilt, `up -d`):
   (a) uid 10001 in lan-sim: connect to 127.0.0.1:8000, 172.23.0.2:8002, 172.20.0.2:4822 and :8000 all ECONNREFUSED (the rule's counter
   counted the 4 packets); root in cape still connects to 8000 and 8002. Session step5b-check (win, small-office) 201, 16 listeners, a connect to
   192.168.150.200:445 completed (the daemon's SYN-ACK passes: counter stayed at 4), DELETE 200, ss, nft tartarus_guest, iptables tartarus-lan
   and proto 77 routes identical to the baseline.
   (b) FIFO status/planted-fifo.json: GET /lan/sessions 0.10 s, DELETE 0.13 s, FIFO removed. Symlinks logs/hostile-log.jsonl and a FIFO log with
   a throwaway analysis folder 999999 (cape-owned, removed after): copied false with a warning, nothing in the folder; a regular log into 999998
   copied true (positive control).
   (c) `up -d --force-recreate cape`: the first answer of the control service (12 s after the container started) was ready false, "old network
   namespace"; `up -d` restored ready true, lan-sim recreated.

## Running
(nothing)

## Next
- Nothing from this brief.
