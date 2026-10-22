# Plan: M11, hardening and release

Last milestone of the [finish line](finish-line.md#m11-hardening-and-release). No feature is added; every finding becomes a
test-first fix or a recorded decision. Notes files under `m11-notes/`.

## Order

Screenshot fixes → CI → security review → fixes → docs move → new docs → license/release files → clean-host test → tag.
Docs move comes late so plan links stay valid while agents work; the new docs need a stable code to describe.

## Waves

| Wave | Tasks | Gate |
|---|---|---|
| A. Green baseline | A1, A2 | `npm run screenshots` exits 0 |
| B. CI | B1, B2 | pipeline green on a pushed branch |
| C. Security | C1 to C5, then C6 | every finding fixed or recorded; unit suites + `make check` green |
| D. Docs | D1 to D3 | no dead link in `docs/` and README |
| E. Release files | E1 to E5 | version shown in app, API and package files |
| F. Clean host | F1 | README alone gets a user to a first analysis |
| G. Tag | G1 | `v1.0.0` |

A to C run in parallel with D1 prep only if disjoint; E needs the logo (user).

## Tasks (rule 5)

| # | Task | Tier |
|---|---|---|
| A1 | Fix the 50 failing screenshot specs: add the unmocked `/api/iocs/*/analyses` routes, replace the "not implemented yet" assertion, mock export/report toasts in `artifacts`, `export-menu`, `report-dialog`, `filter-on`, `submit-memory`, `timeline`, `events`, `shell`, `placeholders`. Mocks/assertions only; if a spec fails for a real UI bug, fix test-first | Haiku, per spec group |
| A2 | Make the harness CI-ready: no dependence on `data/`, a running stack or a display | Sonnet |
| B1 | `.github/workflows/ci.yml`: jobs `backend` (ruff, ruff format --check, mypy, `pytest -m "not integration"`), `backend-integration` (Docker is on hosted runners), `cape-unit` (`make test-cape`), `frontend` (eslint, vue-tsc, vitest, i18n key test), `screenshots` (Playwright, browsers cached), `compose-smoke` (`make smoke`, `MODE=static`); concurrency cancel, uv and npm caches; `make e2e`/`verify-*` stay manual (no nested KVM) | Sonnet |
| B2 | README badge; `docs` note that the real-guest checks are manual | Haiku |
| C1 | Backend: untrusted report parsing (CAPE JSON, Sysmon EVTX, Defender log, PCAP/memory import, ZIP/upload handling, filename and path handling, size limits, query compiler and Sigma input, SSRF-ish fetches, report/PDF HTML escaping) | Sonnet, `security-review` + `code-review` |
| C2 | Control service and cape container: token check (constant time), command construction, path inputs, privileges, what the privileged container exposes | Sonnet, extra care |
| C3 | Compose network layout: published ports bound to 127.0.0.1, guest bridge isolation, internal networks, secrets in env/logs, default `.env.example` values, `make smoke MODE=prod` assertions | Sonnet |
| C4 | Frontend: XSS (`v-html`, event/report fields rendered raw), CSP and nginx headers, WebSocket/Guacamole token handling | Haiku scan, Sonnet judgment |
| C5 | Dependency audit: `uv pip audit` / `pip-audit`, `npm audit --omit=dev`, base image tags and pins; Dependabot config | Haiku |
| C6 | Fix each finding test-first (regression test fails first); record accepted risks in `docs/security.md` | by finding |
| D1 | `git mv docs/plans docs/history`, write `docs/history/README.md` index (milestone, outcome, spike notes); rewrite every link in specs, backend/cape/script docstrings (14 files grep `plans/`), README, `tartarus-v1.md`; link-check script in CI | Haiku |
| D2 | User docs under `docs/guide/`: install, first analysis, building a guest (wizard + ISO notes from the spec, Win10/en-GB), reading a report, backup and disk use, troubleshooting (from M10 findings), safety/network routes | Haiku draft from specs, user reads |
| D3 | Contributor docs: architecture overview (short, links to the specs), running the tests (unit/integration/e2e/verify), the rules in plain language, adding a guest profile / event source (Normalizer) / message key | Haiku draft from specs |
| E1 | `LICENSE` (GPL-3.0), `NOTICE`/`THIRD_PARTY.md`: CAPEv2 (GPL-3.0), capemon, INetSim, Guacamole, Sigma rules attribution (`rules/sigma/default/ATTRIBUTION.md`), Sysmon config, npm/PyPI licenses checked with a license scan | Sonnet (compat check) + Haiku |
| E2 | `CONTRIBUTING.md`, `CHANGELOG.md` (Keep a Changelog; `1.0.0` entry from milestones), `SECURITY.md` | Haiku |
| E3 | One version source: `backend/pyproject.toml` → `GET /api/version` (test first) → About card in Settings (message keys) and footer; set frontend `package.json` to the same | Haiku, test-first |
| E4 | App icon from the logo: favicon, PWA manifest icons (`public/icons`), header mark; a screenshot Artifact round (rule 4) | Haiku; **needs logo** |
| E5 | Rewrite README status/doc table (still says M0 to M7) | Haiku |
| F1 | Clean-host test on a machine/VM that never ran Tartarus: `git clone` → README → `make preflight` → `make up` → ISO → wizard build → first analysis → report. Every gap becomes a doc or preflight fix. User runs it, Claude reads the transcript | user + Sonnet |
| G1 | Re-run CI, `make check`, `verify-guest` and `e2e` on the final commit; tag `v1.0.0`; GitHub release with changelog | me |

## Needs from the user

- The logo (before E4).
- A clean machine or fresh VM with `/dev/kvm` for F1, plus an ISO.
- Approval to push the branch (CI can only be proven on GitHub) and to publish the tag/release.
- Screenshot Artifact review for E4 and the About card.

## Risks

| Risk | Handling |
|---|---|
| CI is only provable after a push | Work on a branch; B1 iterates until green before merging |
| Docs move breaks links in code comments | D1 link-check script; run in CI |
| A security finding needs design change | Record in `docs/security.md`, ask the user before expanding scope |
| Hosted runners lack disk/time for screenshots or integration containers | Split jobs; OpenSearch heap tuned; fall back to unit-only and record |
| Agents over-report (seen in M6) | I re-run each gate and read the diff before committing |

## Proof

CI green on the release commit; zero failing screenshot specs; every C finding closed or recorded; link check clean; F1
transcript shows no undocumented step; `v1.0.0` tag exists.
