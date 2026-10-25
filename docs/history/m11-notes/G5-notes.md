# G5 - secrets and compose networks

Status: done, not committed. Fixes C3 F4 to F8, C2 F8, F10, F15.
C3 F12 (floating tags) is out of scope. Nothing was started, stopped or rebuilt: the live stack was in use.

## Done
- Secrets (C3 F5, F6, F7; C2 F15): `.env.example` leaves the four secrets empty; compose already refuses empty
  values (`${VAR:?}` for all four). `scripts/gen-env.sh` (`make init-env`) writes `.env` with `openssl rand -hex 32`
  for each empty secret, mode 600, never overwrites. `scripts/lib/secrets.sh` holds the one list of secret names,
  placeholders and the minimum token length for gen-env and preflight. `scripts/preflight.sh` fails on a missing or
  placeholder secret, a token under 32 characters, a database password with characters that break the database URL,
  and warns when `.env` is readable by group or others. CI's compose-smoke job uses `scripts/gen-env.sh`.
- `data/secrets.env` (C3 F6): README, `docs/specs/backend.md`, `.env.example` and `.gitignore` now describe the
  generated `.env`; no new mechanism.
- smoke.sh (C3 F8): the resolved config goes to python over stdin (printf builtin), the program via `-c`; test
  `test_static_keeps_resolved_secrets_off_every_command_line` records python's argv.
- Networks (C3 F4): `tartarus-web` (frontend, backend), `tartarus-db` (backend, postgres, internal), `tartarus-search`
  (backend, opensearch, internal), `tartarus-cape-db` (cape, postgres, internal), `tartarus-internal` (cape, backend;
  cape's API/guacd and its route out; unchanged name so the verify-* scripts keep working), `tartarus-control`
  (unchanged). cape needs nothing from OpenSearch (no reference in `cape/`). Dev adds `tartarus-dev` for postgres and
  opensearch only so Docker publishes their loopback ports. smoke.sh gained four checks (opensearch peers, databases
  on internal networks, frontend peers, cape peers), tested in test_smoke.sh. Docs: architecture.md (Networks
  section), specs/cape-integration.md.
- C2 F10: `answer.iso` is built under `umask 077`. It is NOT deleted after the install: the install domain stays
  defined with it as a CD for every later restart and snapshot revert.
- C2 F8: `cape/auxiliary/event_logs.py`: `allow_redirects=False`, `stream=True`, body capped at `MAX_EXPORT_BYTES`
  (256 MiB), the written document capped too, and an overall deadline (connect + read timeout) enforced by a worker
  thread, since requests' read timeout restarts on every byte.

## Not done / next
- C3 F9 (cap_drop, no-new-privileges, read_only, limits) was not in the brief's task list and cannot be validated
  without restarting containers; C3 F11 (chmod 600 of cape's siteauth.sqlite) lives in supervisord.conf (G1/G2).
- The backend still has a route out: the CAPE API listens on `tartarus-internal` (supervisord.conf, G1/G2 scope),
  which must keep a route for cape's guests. Moving the API to `tartarus-control` would let `tartarus-internal`
  be cape-only.
- The cape entrypoint still accepts any non-empty `CAPE_API_TOKEN` (C2 F15 mentions it); preflight is the gate.
- Real restart with the new networks (ports published through `tartarus-web`, cape on three networks, `postgres`
  name resolution from cape) is unverified; needs `make up` once the e2e run is finished.
- The existing `.env` is mode 644 and keeps working; `chmod 600 .env` is the operator's call.
