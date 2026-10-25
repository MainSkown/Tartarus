# C2a notes (done / running / next)

## Done
- Read CLAUDE.md, the M6 plan, S0e/S0b/S0d findings, build-guest.sh, domain.xml.tpl, protocol.py, errors.py.
- Read-only fixtures of the running guest: cape/tests/fixtures/win.dumpxml.xml, win.registration.conf.

## Running
- nothing; all six modules done

## Next (in order, each test-first)
1. giveaways  2. names  3. profile (+ fixtures)  4. registry  5. registration  6. validation
7. make test-cape, ruff check, ruff format --check

## Decisions taken (to report)
- Empty registration renders `[kvm]\nmachines =\n` (cape/conf/kvm.conf does the same; wait-then-exec treats it as "no guest yet").

## Progress log
- giveaways (38 tests) and names (15) done, ruff clean.
- profile.py + fixtures (profiles/windows.json, profiles/ubuntu.json, profile_samples.py): 135 tests pass, ruff clean.
- NOTE: an early `ruff format guest_engine tests` of mine touched C3's tests/test_media_mount.py (whitespace only); from now on ruff only on my own files.
- registry.py (44 tests) and registration.py (16 tests) done, ruff clean. Profile gained agent.work_root, adoption{account,machine,password,work_dir,media,options}, option_defaults(), path_separator; names gained folder_name.
- validation.py (104 tests) done. Mutation check: 11 deliberate breaks of the code, each caught by a test (the one that survived, fsync, got its own test).
- Final: make test-cape 673 passed (371 of them mine), ruff check and format --check clean.
- Open for the planner: "windows" appears twice in profile.py as schema vocabulary (cape.platform values, agent.path_style values) and trips a case-insensitive grep gate.
