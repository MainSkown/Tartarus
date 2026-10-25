# Plan: M11 follow-ups from the security review

What the [security review](m11-hardening-and-release.md) left open after waves A to C (reports in `m11-notes/`). The two easy items run first,
the same day; the rest are scheduled or recorded in `docs/security.md` as accepted risk. Rules 1 to 5 of `.claude/CLAUDE.md` apply: test first, and Haiku for the mechanical items.

## Today: easy

| # | Item | How | Check | Model |
|---|---|---|---|---|
| F1 | `GET /apiv2/` answers 500 (its template reverses UI routes the API-only URL config removed) | Failing test first in `cape/tests/test_web_settings.py`: `/apiv2/` answers 200 or a clean 404, never 500. Fix in `cape/web/tartarus_urls.py` (a plain redirect to `/apiv2/cuckoo/status/`, or a stub view). `/apiv2/cuckoo/status/` with a token must keep answering 200 | the new test; `make verify-cape-hardening`; one `curl` against the live stack | Haiku |
| F2 | Base images pinned by tag only (`python:3.12-slim`, `ghcr.io/astral-sh/uv:0.12`, `node:24-alpine`, `nginx:alpine`, `ubuntu:24.04` x5, `postgres:16`, `opensearchproject/opensearch:3.9.0`) | Pin each `FROM` and compose `image:` to `tag@sha256:digest` (read each digest from the registry with `docker buildx imagetools inspect`; `nginx:alpine` first gets a concrete version tag). `backend/tests/compose_images.py` and its users (testcontainers) must still parse the pinned form; `.github/dependabot.yml` already bumps digests. A test asserts no `FROM` or `image:` lacks a digest | the new test; `make smoke`; `docker compose build` of backend, frontend and cape; `make test-integration` (it starts the pinned postgres and opensearch) | Haiku |

Order: F1, then F2. Both land as two commits, test first. After F2, rebuild the stack once (`docker compose up -d --build`) and run `make e2e` pinned to `lab1` (`E2E_GUEST=lab1`), because F2 changes every image.

## Later: moderate

| # | Item | How | Needs | Model |
|---|---|---|---|---|
| L1 | `WinStore.App` seen open by the self-test on one of three `w10-q` clones | A settle-and-recheck in `quiet-desktop` (wait, list again, close what appeared). Prove with five clones of `w10-q` | a real guest, about 30 minutes | Sonnet |
| L2 | `make e2e` fails two checks on the Windows 10 guest (the process panel selects the first process, the Sigma alert triggers on a Sysmon event, not capemon) | Make both checks guest-aware, or pin the e2e's default guest (`E2E_GUEST`, already added) in `make e2e` documentation | a 13-minute run on `w10-q` | Sonnet |
| L3 | `GET /api/guests` returns the guest account password | A reveal endpoint, one call from `GuestCard.vue`, the field removed from the list model, `make api-sync` | rule 4 screenshot round | Sonnet |
| L4 | CSP keeps `style-src 'unsafe-inline'` | Try `style-src 'self'` with `style-src-attr 'unsafe-inline'` in a real browser against the production build, all routes plus the Guacamole desktop | a browser run | Haiku scan, Sonnet judgment |

## Recorded, not fixed (go into `docs/security.md`)

- **`cape` stays `privileged: true`.** Without it libvirt cannot set the bridge port flag `isolated` (sysfs is read-only in Docker). The way out is to drop `<port isolated>` from every domain XML and set it in the qemu hook with `bridge link set dev <tap> isolated on`: v1.1.
- **`diskcache` advisory.** No upstream fix; a transitive dependency of pySigma, its cache holds ATT&CK data and hostile input cannot reach it.
- **CAPE and Django advisories** at the pinned CAPE commit: a bump of `CAPE_REF` risks the analyzer patches, so it waits for a release that can be proven on a real guest.
- **Plain HTTP on 127.0.0.1.** A local tool; TLS is not offered.
