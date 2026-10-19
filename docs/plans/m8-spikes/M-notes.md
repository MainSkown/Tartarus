# Task M notes: the event logs module (M8)

## Done

- Tests first (`cape/tests/test_event_logs.py`, fake guest and fake clock in `cape/tests/fixtures/event_log_guest.py`,
  CAPE import stub in `cape/tests/fixtures/cape_modules.py`, called from `cape/tests/conftest.py`); watched them fail
  on the missing module, then wrote `cape/auxiliary/event_logs.py`. Mutation checks on the module (baseline forced to
  0, settle cap removed, timeout bound removed, config apply removed, wrapper slicing removed, ...) each failed at
  least one test.
- Channel table: Sysmon (`wevtutil`, guest ANSI code page, `sysmon/sysmon.xml`, carries the Sysmon config) and
  Defender (PowerShell `ToXml()`, UTF-8, `aux/defender.xml`, settle predicate).
- Baseline by `wevtutil gli` (channel exists, record count) then newest record id; no clear.
- Sysmon config: `guest/profiles/windows/sysmon-config.xml` replaced by S1's proposed v2 plus
  `<WmiEvent onmatch="exclude" />`, new header comment; `profile.json` help text of the `sysmon` option; the profile
  tests (`TestSysmon`) now guard the ImageLoad include rule, the empty exclude blocks and the one-field-per-block rule.
- The module reads the config from `/usr/local/lib/tartarus/profiles/windows/sysmon-config.xml`, which the existing
  `COPY guest/profiles/` already puts there (one copy of the file, no second COPY).
- `cape/Dockerfile` COPY of the module (owner `cape`), `cape/conf/auxiliary.conf` `[event_logs] enabled = yes`,
  `Makefile` lint now covers `cape/auxiliary`, `docs/specs/cape-integration.md` section "Event logs module".

## Not done / next

- Nothing runs against a real guest (no `docker build`, no stack): the real-run proof task checks the agent
  commands, `/store` and `/remove`, `wevtutil gli` output, the empty-`wevtutil` output and the PowerShell script.
- The copies of the old `sysmon` help text in `backend/tests/guest/fixtures/profiles.json`,
  `frontend/tests/screenshots/guest-wizard-data.ts` and `cape/tests/fixtures/profiles/windows.json` are fixtures of
  their own and were left alone (nothing compares them to `profile.json`).
