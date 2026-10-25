# B4 notes (live desktop of a guest during its build)

Baseline: `uv run pytest tests/desktop tests/test_ws_desktop.py -q` = 172 passed.

## Done
- Tunnel: `GuacdTunnel.open`, `connect_instruction`, `connect_values` take `vnc_host` (default `VNC_HOST`), tested first.
- `app/desktop/resolver.py` (VncTarget, DesktopResolver, AnalysisResolver, CheckUnavailableError) and `app/desktop/guest_build.py` (GuestBuildResolver); `app/ws/desktop.py` runs one `_DesktopSession` over a resolver; new route `WS /ws/guests/{name}/desktop`; `CLOSE_SERVER_ERROR` moved to admission.py.
- Tests: tests/desktop/test_guest_build_resolver.py (25), tests/test_ws_guest_desktop.py (25), host tests in test_tunnel.py / test_tunnel_values.py; shared socket helpers moved to tests/desktop/sockets.py; StubGuestControl in tests/desktop/stubs.py.
- Full run: 3398 passed, 267 deselected, 1 xfailed, 2 failed (tests/test_analyses_api.py, B5's in-flight `guest` option, not this task); mypy app clean; ruff format --check clean; ruff check clean for B4 files (4 errors left in other agents' files).

## Running
- nothing

## Next
- Planner: run the tunnel against a real guest build desktop (not run). Update docs/specs/backend.md (not in B4's edit list) with the new route.
