# B3 notes (guest self-test through Tartarus)

## Plan (each step ends in a check that can fail)
1. Client: `selftest_sample` / `selftest_checks` on `GuestControl` + `HttpGuestControl` (tests first), fakes.
2. `GuestProfile.selftest.signals` in the schemas (the runner reads the signal list from the profile).
3. `selftest_verdict.py`: pure verdict, table-driven tests first.
4. `selftest_runner.py`: `GuestSelfTest` (analysis wait, event evidence, checks), fake-driven tests.
5. main.py wiring; full gate.

## Done
- Step 1 (client, schemas incl. profile selftest signals, fakes): tests/guest green (197).
- Step 3: `selftest_verdict.py` (pure) + `selftest_evidence.py` (one OpenSearch aggregation) with tests; the evidence query also ran green against real OpenSearch on the analysis 6 fixture (tests/integration/views/test_selftest_evidence.py).
- Step 4: `selftest_runner.py` (GuestSelfTest), tests/guest/test_selftest_runner.py with the real AnalysisSubmitter on sqlite and a fake pipeline; mutation checked (gate=True, no progress floor fail tests).
- Step 5: main.py wires GuestSelfTest. Full: 3590 passed, 271 deselected; ruff check, ruff format --check, mypy app clean.
- DNS: the real analysis 6 records the lookup of tartarus-selftest.example with `answers: []`, so the signal requires the lookup, not an answer (reported, not required).

## Running
- nothing

## Next
- Planner: real run against control service (C5) and a real guest; update specs.
