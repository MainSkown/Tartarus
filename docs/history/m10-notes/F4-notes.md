# M10 F4 notes (English Defender service names tripped the `virus` giveaway)

## State: done (planner re-runs the checks and proves it on the w10 guest)

- done: failing tests first, then the fix, then green; spec sentence added under "Names and giveaways".
- running: nothing.
- next (planner): `docker cp` the fixed `guest-facts.ps1` and run the self-test on `w10`.

## The rule chosen

`LEGITIMATE_WORDS = ("antivirus",)` in `cape/guest_engine/giveaways.py`. `find_giveaway` lower-cases the text,
replaces each legitimate word with a SPACE, then runs the substring check on that. Token and prefix checks use
the original text (no legitimate word contains one). Results: `Antivirus Service`, `ANTIVIRUS` -> none;
`virus`, `myvirus`, `virus-lab`, `Antivirus virus`, `antivirusvirus` (leaves ` virus`) -> `virus`;
`antywirusowa` untouched. A space, not an empty string, so `viantivirusrus` does not glue into `virus`.
`guest-facts.ps1` mirrors it: new `$LegitimateWords` parameter and the same replace in `Find-Giveaway`.

## Failing first (new tests, engine had the constant but not the rule, script had neither)

`pytest -q tests/test_giveaways.py tests/test_windows_profile.py` -> 9 failed, 200 passed:
- 6x `test_ordinary_names_...[Microsoft Defender Antivirus Service | ...Network Inspection Service |
  ...Network Realtime Inspection | antivirus | ANTIVIRUS | Antivirus]`: `AssertionError: assert 'virus' is None`
  (`find_giveaway('Microsoft Defender Antivirus Network Inspection Service')` = 'virus')
- `test_the_facts_script_carries_the_same_word_list_as_the_engine[LegitimateWords]`: `KeyError: 'LegitimateWords'`
- `test_no_shipped_file_contains_a_giveaway`: `selftest/guest-facts.ps1:52: virus` (the `Fact 'defender.antivirus_enabled'`
  allow-list entry was removed: the scan now follows the shared rule instead of a second list)
- `test_the_scan_does_not_flag_a_legitimate_word_but_flags_a_giveaway_beside_it`: `['sample.ps1:1: virus'] == []`

The pwsh parity test passed at that point (both sides agreed on the old behaviour). Proven able to fail: with the
script's replace line disabled it fails (`1 failed, 58 passed`); script restored afterwards.

## Design

- New tests: engine case tables (GIVEAWAY_CASES / ORDINARY_CASES in `test_giveaways.py`), a check that a legitimate word
  contains a giveaway substring and no token/prefix word, sync of all four word lists between engine and script
  (parsed from the script's param defaults), and a pwsh test that runs the script's own `Split-Tokens` + `Find-Giveaway`
  (cut out of the file) over every case of both tables and compares with `find_giveaway` (skips without pwsh).
- The profile file scan (`giveaway_findings` in `test_windows_profile.py`) now uses `giveaways.lowered_without_legitimate_words`.
  No second list. The `defender.antivirus_enabled` line allow-list entry is gone.
- Other callers confirmed: `validation.py` (_identity_problem: account and computer name), `names.py` (generators),
  `registry.py` (carried giveaways of an adopted guest) all call `find_giveaway`; nothing else to change.
- Engine comment must not name an OS (`test_only_the_two_vocabulary_lines...`), hence the neutral wording there.

## Results

- no shim: `uv run --no-project --with pytest pytest -q` in cape -> 1977 passed, 9 skipped
- shim on PATH: same -> 1986 passed
- `ruff check guest_engine auxiliary tests` -> All checks passed; `ruff format --check ...` -> 88 files already formatted
- `bash scripts/tests/test_windows_steps.sh` -> 59 ok lines, "all tests passed"
