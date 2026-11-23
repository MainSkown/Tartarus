# Fake LAN Step 4 notes: the lan-sim framework

Files: `cape/guest_engine/lan_session.py`, `cape/tests/test_lan_session.py`, everything under `lan-sim/`.
Run: `cd lan-sim && uv run --no-project --with pytest pytest -q` (plain `asyncio.run` in tests, no
pytest-asyncio, nothing to download); `cd cape && uv run --no-project --with pytest
--with-requirements build/pycdlib.requirements pytest -q`.

## Decisions
- `lan_session` is imported as a top-level module from lan-sim (conftest puts `cape/guest_engine` on
  sys.path), like `machine_broker_client`: Step 5 copies the one file next to the package.
- The daemon's `reconcile()` is callable by hand, so tests never wait for the poll.
- Aggregates and `session-end` bypass the hard cap (bounded by construction).
- `read(n)` caps the TOTAL bytes read per connection (64 KiB); a per-connection lifetime cap (300 s) was added.

## Done
- lan_session (134 tests), events, limits, session_log, service, daemon, `__main__`, SCHEMA.md.
- 100 lan-sim tests in under 1 s; whole cape suite 3011 passed, 45 skipped; ruff clean on both.
- Mutation check on a copy: unknown source served, no refcount, bind failure keeps listeners, no host
  check, no hard cap, no sanitising, no session-end on close: each made a test fail.

## Running
(nothing)

## Next
- Step 5: image, compose, mounts (the daemon needs write access to `status/` and `logs/`, read-only `sessions/`).
- Protocol services register in `lan_sim/__main__.py::build_registry`.
