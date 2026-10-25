# C1 notes (control service)

Resume point for an interrupted run. Updated after every step.

## Design decisions taken

- Shared HTTP module `cape/bin/control_http.py`; finish logic shared in `cape/bin/finish_logic.py`.
- Scripts put their own directory on `sys.path` (they run with `python3 -I`, which drops it).
- Docker DNS alias per network (`cape-internal`, `cape-control`) tells the entrypoint which interface is which;
  verified in a scratch compose project: a container resolves its own alias to its address on that network.
- Probe guest in verify-cape is pinned to the pool start by a DHCP host reservation (`virsh net-update`).

## Done

- control_http.py + test_control_http.py (33 tests, seen failing first: ModuleNotFoundError)
- finish_logic.py + test_guest_control_finish.py (seen failing first); finish-run moved onto both, test_finish_run.sh 18/18
- guest-control + test_guest_control.py (seen failing first); pytest 235 passed over my 3 test files; ruff clean

- verify-cape: probe on a DHCP reservation in the pool, check 8 (control), `control` argument; test_verify_cape.sh all pass (25 new/changed tests seen failing first); `verify-cape.sh control` run against the old stack FAILED as expected
- entrypoint (alias-based addresses, interface for routing.conf), tt-guest.xml pool .100-.119, start-guest-network, supervisord guest-control, Dockerfile (wimtools layer, guest_engine copy), compose (tartarus-control, aliases, backend env), .env.example, .env token appended

## Running

(nothing)

## Next

Report to the planner. Image rebuilt, stack up, `verify-cape.sh control` 14 OK, full verify-cape exit 0 (kvm.conf.d restored, hashes equal).
