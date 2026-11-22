# Plan: M11 follow-ups from the security review

What the [security review](m11-hardening-and-release.md) left open after waves A to C (reports in `m11-notes/`). The two easy items run first,
the same day; the rest are scheduled or recorded in `docs/security.md` as accepted risk. Rules 1 to 5 of `.claude/CLAUDE.md` apply: test first, and Haiku for the mechanical items.

## Today: easy

| # | Item | How | Check | Model |
|---|---|---|---|---|
| F1 | `GET /apiv2/` answers 500 (its template reverses UI routes the API-only URL config removed) | Failing test first in `cape/tests/test_web_settings.py`: `/apiv2/` answers 200 or a clean 404, never 500. Fix in `cape/web/tartarus_urls.py` (a plain redirect to `/apiv2/cuckoo/status/`, or a stub view). `/apiv2/cuckoo/status/` with a token must keep answering 200 | the new test; `make verify-cape-hardening`; one `curl` against the live stack | Haiku |
| F2 | Base images pinned by tag only (`python:3.12-slim`, `ghcr.io/astral-sh/uv:0.12`, `node:24-alpine`, `nginx:alpine`, `ubuntu:24.04` x5, `postgres:16`, `opensearchproject/opensearch:3.9.0`) | Pin each `FROM` and compose `image:` to `tag@sha256:digest` (read each digest from the registry with `docker buildx imagetools inspect`; `nginx:alpine` first gets a concrete version tag). `backend/tests/compose_images.py` and its users (testcontainers) must still parse the pinned form; `.github/dependabot.yml` already bumps digests. A test asserts no `FROM` or `image:` lacks a digest | the new test; `make smoke`; `docker compose build` of backend, frontend and cape; `make test-integration` (it starts the pinned postgres and opensearch) | Haiku |

Order: F1, then F2. Both land as two commits, test first. After F2, rebuild the stack once (`docker compose up -d --build`) and run `make e2e` pinned to `lab1` (`E2E_GUEST=lab1`), because F2 changes every image.

## Later: moderate (all done)

| # | Item | Outcome |
|---|---|---|
| L1 | `WinStore.App` seen open by the self-test on one of three `w10-q` clones | Two changes. `quiet-desktop` looks again after each pass and closes what opened meanwhile (up to four passes). That alone was not enough: five of five fresh Windows 10 clones still failed, because the Store opens during the idle that followed the quiet pass, so the snapshot step now idles first and runs the pre-snapshot steps after it. Five fresh clones of the same Windows 10 guest all reached `ready` with a clean self-test |
| L2 | `make e2e` fails two checks on the Windows 10 guest | The process-panel check picks the sample by name (done earlier). The Sigma source check failed on a letter case alone: Windows 10's Sysmon reports `SOFTWARE\Tartarus\SelfTest`, the check wanted `Software`; it now compares without regard to case. A full run on Windows 10 failed that check and no other |
| L3 | `GET /api/guests` returns the guest account password | A reveal endpoint, one call from `GuestCard.vue`, the field removed from the list model |
| L4 | CSP keeps `style-src 'unsafe-inline'` | `style-src 'self'` with `style-src-attr 'unsafe-inline'`. The one inline element, Cytoscape's container rule, is a stylesheet of its own; `frontend/tests/e2e/csp.spec.ts` records policy violations on every route and analysis tab |

## Recorded, not fixed (go into `docs/security.md`)

- **`cape` stayed `privileged: true` at v1.0.0**, because libvirt could not set the bridge port flag `isolated` (sysfs is read-only in Docker). Closed afterwards: the qemu hook sets the flag and the container runs with a fixed capability list (see the [2026-11-12 review](../security-audit-2026-11-12.md)).
- **`diskcache` advisory.** No upstream fix; a transitive dependency of pySigma, its cache holds ATT&CK data and hostile input cannot reach it.
- **CAPE and Django advisories** at the pinned CAPE commit: a bump of `CAPE_REF` risks the analyzer patches, so it waits for a release that can be proven on a real guest.
- **Plain HTTP on 127.0.0.1.** A local tool; TLS is not offered.
