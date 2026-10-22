# G6 dependency fixes notes

## Done
- Step 1 (pillow 13.0.0, certifi 2026.10.19): uv.lock upgraded via `uv lock --upgrade-package`. Both transitive, no pyproject change needed. ruff, mypy, pytest (-m "not integration", 4251 passed) and tests/export/report (158 passed) all passed at that point.
- Step 2 (pypdf 6.21.2): pyproject dev floor raised to `pypdf>=6.21.1`, uv.lock upgraded. pypdf-dependent tests pass (tests/export/report 158 passed, mypy clean). Later full-suite and ruff failures are from another agent's in-progress files (see Step 2 result below), not from this bump.
- Step 3 (diskcache): investigated, no code change. See below.

- Step 4 (js-yaml override): `overrides: {"js-yaml": ">=4.3.2"}` in frontend/package.json. npm audit: 0 vulnerabilities. The override resolved js-yaml to 5.5.0 (a major jump, argparse 3.0.3) on the dev-only path. Lint, typecheck, unit tests (238 files, 3575 tests) pass; `npx openapi-ts --help` loads. Kept as specified; `^4.3.2` would stay on the 4.x line if the major jump is unwanted.
- Step 5 (dependabot): .github/dependabot.yml written, 7 entries (uv /backend; npm /frontend, /frontend/src-pwa; docker /backend, /cape, /frontend; github-actions /), weekly, open-pull-requests-limit 5, minor+patch grouped. Parses as YAML.

## In progress
- none

## Next
- none (report to caller)

## Step 2 result (kept)
- ruff: 14 errors, all in files other agents are editing (`tests/test_browser_guard.py` untracked, imports missing `app.browser_guard`; `tests/live/test_collector.py` and `tests/test_report_summary.py` I001 import order; `tests/test_browser_guard.py` E501/SIM117).
- pytest -m "not integration" --ignore=tests/test_browser_guard.py: 45 failed, 4218 passed. Failures are 421 Misdirected Request (26), 202-vs-404/422 (22), 421==200 (15), WebSocketDisconnect (11). Source: untracked `backend/app/browser_guard.py` (BrowserOriginGuard refuses unknown hosts with 421) and an edit to `backend/app/main.py` that adds it, both by another agent. Not touched by this step.
- Not reverted: the failures are external to the pypdf change and reverting pyproject/uv.lock would not fix them.

## Step 3 diskcache findings
- Direct dependency? No. Transitive only: `pysigma 2.0.1 -> diskcache 5.6.3` (`uv tree --invert`). Also `diskcache-stubs` via pysigma. No `diskcache` in backend/pyproject.toml.
- No version fix: 5.6.3 is the latest release and pysigma requires `diskcache>=5.6.3,<6.0.0`, so the advisory (PYSEC-2026-2447 / CVE-2025-69872) has no fixed version on the PyPI line. Not fixable by a bump in this repo.
- What it caches: only in `sigma/data/mitre_attack.py` and `sigma/data/mitre_d3fend.py` (pysigma). The parsed MITRE ATT&CK / D3FEND STIX data (tactics, techniques, software, etc.) under `~/.cache/pysigma/mitre_attack` and `.../mitre_d3fend`, written by `cache.set("mitre_attack_data", ...)`.
- Who reads it: `sigma/validators/core/tags.py` imports those modules and reads the cache when the pysigma tag validator runs. The app never runs pysigma validators (grep for `SigmaValidator`, `sigma.validators`, `validators` in backend/app and backend/tests: no hits). So in the running app the cache is not read or written.
- Pickle exposure: diskcache stores non-primitive values with pickle (`diskcache/core.py` default disk pickle protocol). An attacker who can write files in the cache directory could plant a pickle that executes on read. That requires write access to the backend user's home cache dir, meaning code execution already. Hostile rule or event input cannot reach the cache: rule YAML is parsed by pysigma, never written to diskcache, and the MITRE data comes from the MITRE GitHub URL, not from user input (`set_url` / `set_cache_dir` are not called by app).
- Conclusion: not a remote path. Accept as-is; it would be cleared by dropping pysigma's MITRE validator path or by a diskcache release, neither of which exists. No code changed.
