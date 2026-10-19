# Y notes: the Windows kernel symbol file (ISF) for Volatility3 (M8, resume file)

Baseline before any change: `make test-cape` 1683 passed, 1 skipped.

## Design (decided from reading the code)
- `cape/bin/symbols_logic.py`: `ensure_symbols(guid, age, symbols_dir, fetch, convert)`, pure and injected; real fetch
  (https, fixed host, redirects only to Microsoft hosts, size cap) and real converter (Volatility3's own `pdbconv
  --file`, as the `cape` user through `volatility.run_command`) in the same module.
- Entry points: `POST /symbols` in `guest-control`; `cape/bin/guest-symbols` (CLI) for the build step, because a step is
  a separate process with a stripped environment (no token), so it cannot call the route.
- Build step `symbols` in `guest/profiles/windows/` (script in `steps/`, RSDS reader in `steps/lib/pdb_id.py`), placed
  after the last Windows step and before `snapshot` in the build and clone pipelines: the guest is still running and its
  agent answers there; `snapshot` shuts the guest down. Non-fatal: always exits 0.
- Missing symbols answer of `analyse`: `windows.info` is run with `-v`; Volatility logs at INFO "The symbols can be
  downloaded later using pdbconv.py -p ntkrnlmp.pdb -g <GUID><age decimal>" (pdbutil.py, 2.28.2).
- Volatility 2.28.2 facts (read in the wheel, sha256 0461d6dd...): its own PDB URL is `http://msdl.microsoft.com/download/symbols/<pdb>/<GUID><age as decimal>/<pdb>`;
  `pdbconv -f <pdb> -p ntkrnlmp.pdb -o x.json.xz` converts a local file (xz chosen by the extension; `-p` sets the ISF's
  `database`, without it the ISF says `unknown.pdb` and Volatility's identifier lookup misses it).

## Done (all test-first; `make test-cape` 1866 passed, 1 skipped; baseline was 1683 passed, 1 skipped)
- `cape/bin/symbols_logic.py` (+ `test_symbols_logic.py`, 114 tests): id validation, URL, size cap, atomic write,
  idempotence, cleanup, redirect policy, real fetcher, real converter, `POST /symbols` answer, CLI line.
- `POST /symbols` in `cape/bin/guest-control` (+ `test_guest_control_symbols.py`).
- `cape/bin/guest-symbols` (CLI for the step; + `test_guest_symbols.py`).
- `volatility.py`: `CAPE_USER`, `CAPE_ENVIRONMENT`, `SYMBOLS_DIRECTORY`, `VOLATILITY_PYTHON` moved here from
  `memory_logic` (shared by the converter); `-v` option; `MissingSymbols` parsed from the INFO line.
- `memory_logic.py`: the probe runs with `-v`; `missing_symbols` in the 200 body and `run.json`.
- Windows profile: `steps/symbols`, `steps/lib/pdb_id.py` (stdlib RSDS reader), `guest_agent.py retrieve-system`,
  `profile.json` (`symbols` before `snapshot` in the build and clone pipelines, timeout 900, weight 2).
  Tests: `test_pdb_id.py`, `test_guest_build_agent.py`, `test_windows_profile.py`, `scripts/tests/test_windows_steps.sh`
  (all 10 new cases and the whole file pass, 50 s).
- `docs/specs/cape-integration.md`, Makefile lint lists.

## Not done / needs the real run
- No real fetch from Microsoft, no real `pdbconv` run on a real PDB, no real guest kernel read, no real dump with
  missing symbols (see the real-run checklist in the final report of this task).
- No `symbols` profile option (see the report: the step is non-fatal and bounded; an option is GUI-visible and would
  need backend and frontend tests).
