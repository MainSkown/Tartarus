# C5 dependency audit

Scope: backend/, frontend/ (+ src-pwa/), cape/, guest/, all Dockerfiles and docker-compose files, .github/. Read-only: no source file edited, nothing committed, no git write command run. Raw tool output was kept under the session scratchpad (`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/fd294e31-e4f8-404a-abc0-7c8ec6a3339d/scratchpad/audit/`).

Tool versions: uv 0.12.21, pip-audit 2.10.1, npm 12.2.1, license-checker (npx, latest), pip-licenses (via `uv run --frozen --with pip-licenses`).

Caveat on severity: pip-audit prints no severity field, so the pip counts below are per advisory with no critical/high split. Nothing in this report assigns a severity that a tool did not print.

---

## Summary

| Area | Scope | Count | Severity as printed | Runtime reach |
|---|---|---|---|---|
| Backend, prod lock (`uv export --no-dev`, 75 pkgs) | backend prod image | 37 entries | not printed | see section 1 |
| Backend, full lock (98 pkgs incl. dev) | adds dev only | 38 entries (37 unique IDs) | not printed | pypdf is dev-only |
| Frontend `npm audit --omit=dev` | frontend prod | 0 | - | - |
| Frontend `npm audit` (full) | frontend dev + prod | 4 | 4 high | dev only (see section 2) |
| src-pwa `npm audit --omit=dev` / full | PWA | 0 / 0 | - | - |
| CAPE locked Python deps (`/opt/CAPEv2` uv.lock at pinned SHA, `--no-dev`) | cape image | 338 entries across 36 pkgs | not printed | cape-web runs (section 3) |
| Guest-side Pillow pin `pillow==10.4.0` (guest/profiles/windows/manifest.sha256:8) | Windows analysis guest | 63 entries | not printed | guest agent, not host |

Critical or high items:
- npm: 4 high, all in the @hey-api/openapi-ts devDependency chain (js-yaml). Dev tooling only, not in the shipped bundle.
- No critical items printed by any tool.
- Backend and CAPE have many Pillow, Django, pypdf, cryptography and pyjwt advisories. These are not labelled critical or high by pip-audit, so the severity question is open. Upgrades are listed in section 1 and 3.

---

## 1. Backend Python (`backend/`)

Commands:
- `cd backend && uv export --frozen --no-hashes > req.txt` (281 lines; `--no-dev` variant gave 75 pinned packages)
- `uvx pip-audit -r req.txt --no-deps -f json`

Output as printed (full export, 98 packages):
```
Found 38 known vulnerabilities in 4 packages
```

Per package (installed version, advisory id, fix version as printed):

| Package | Installed | Advisory | Fix | Group / reach |
|---|---|---|---|---|
| pillow | 12.3.0 | 34 advisories, see list below | 13.0.0 | prod (weasyprint 70.0 → pillow) |
| diskcache | 5.6.3 | PYSEC-2026-2447 (CVE-2025-69872, GHSA-w8v5-vhqr-4h9v), listed twice | none printed | prod (pysigma 2.0.1 → diskcache) |
| certifi | 2026.7.22 | PYSEC-2026-4320 (GHSA-6q48-6c7w-9gw2) | 2026.10.19 | prod (httpx, opensearch-py, requests) |
| pypdf | 6.20.1 | CVE-2026-113786 (GHSA-5hx5-vpf9-5wcv) | 6.21.1 | dev group only (`uv tree --invert`: `pypdf v6.20.1 └── tartarus-backend v0.1.0 (group: dev)`) |

Pillow 12.3.0, 34 advisories, all fixed in 13.0.0 as printed: CVE-2026-112895, CVE-2026-112400, CVE-2026-112397, CVE-2026-112896, CVE-2026-112897, CVE-2026-112395, CVE-2026-112404, CVE-2026-112899, CVE-2026-112402, CVE-2026-112900, CVE-2026-112893, CVE-2026-112392, CVE-2026-112891, CVE-2026-112405, CVE-2026-112390, CVE-2026-112401, CVE-2026-112901, CVE-2026-112391, CVE-2026-112894, CVE-2026-112406, CVE-2026-112399, CVE-2026-112892, CVE-2026-112393, CVE-2026-112396, CVE-2026-96638, CVE-2026-96641, CVE-2026-96640, CVE-2026-96642, CVE-2026-96639, CVE-2026-96643, CVE-2026-96637, CVE-2026-96644, CVE-2026-96778, CVE-2026-96636.

Prod-only audit (`uv export --no-dev`, 75 packages): 37 entries, pillow 34 + diskcache 2 + certifi 1. pypdf is the one dev-only finding.

Reachability notes (from code and `uv tree`, not from a running system):
- pillow: no direct `import PIL` under backend/app. It is reached through WeasyPrint, which the report export uses at runtime (backend/app/export/report/render.py:57 and :72). Exposure depends on whether WeasyPrint decodes raster images from report content. Not verified.
- diskcache: no direct import under backend/app. Reached through pysigma. The advisory needs write access to the cache directory. Whether pysigma touches a diskcache at runtime was not checked.
- certifi: the advisory concerns a revoked root in the bundled CA store. Used by every HTTPS client in prod.
- pypdf: used only by backend/tests (integration tests). Not in the prod image.

Upgrade candidates (not applied): pillow to >=13.0.0; certifi to >=2026.10.19; diskcache has no fixed release in the advisory data. pypdf to >=6.21.1 for the dev group.

---

## 2. Frontend (`frontend/`, `frontend/src-pwa/`)

Commands: `npm audit --omit=dev`, `npm audit`, and `npm audit --json`, run in both directories.

### frontend/ `npm audit --omit=dev`
```
found 0 vulnerabilities
```

### frontend/ `npm audit` (full), as printed
```
4 high severity vulnerabilities

To address all issues (including breaking changes), run:
  npm audit fix --force
```

| Package | Severity | Path | Dependency kind | fixAvailable (as printed) |
|---|---|---|---|---|
| @hey-api/openapi-ts 0.99.0 | high | direct, devDependencies (package.json:35) | dev | `@hey-api/openapi-ts@0.97.0` (semver-major, "breaking change") |
| @hey-api/json-schema-ref-parser 1.4.4 | high | transitive via @hey-api/openapi-ts | dev | same |
| @hey-api/shared 0.5.0 | high | transitive via @hey-api/openapi-ts | dev | same |
| js-yaml 4.2.0 | high | transitive via @hey-api/json-schema-ref-parser | dev | same |

js-yaml advisories printed by npm: GHSA-52cp-r559-cp3m (quadratic CPU, YAML merge keys), GHSA-5p4m-2wfm-xmqj (CVE-2026-59870, quadratic CPU in !!omap, "fix not backported"), GHSA-2883-xcg3-v3hh (maxTotalMergeKeys). Affected range 4.0.0 - 4.3.1.

Reachability: all four are devDependency tooling. @hey-api/openapi-ts generates frontend/src/api/*.gen.ts at build-time and is not imported from frontend/src (checked: the only matches are the "auto-generated" headers and a comment in src/api/sdk.gen.ts:738). The shipped nginx image (frontend/Dockerfile:20-22) serves only `dist/pwa`. Not in the shipped bundle.

npm's suggested fix is a downgrade to 0.97.0, which npm labels breaking. Not recommended as printed. `npm view js-yaml` shows 4.3.2 as a release outside the affected range, so an `overrides` entry for js-yaml might remove the finding without touching openapi-ts. Not tested.

### src-pwa/ `npm audit --omit=dev` and full
```
found 0 vulnerabilities
```
(both)

---

## 3. cape/ and guest/ (downloads and pins)

### 3a. cape/Dockerfile

| Line | What | Pinned? | Checksum / signature? |
|---|---|---|---|
| cape/Dockerfile:3-4 | `CAPE_REF` (kevoreilly/CAPEv2) | Yes: enforced 40-char commit SHA | No signature. Commit SHA via git fetch (line 7). |
| cape/Dockerfile:7-8 | `git fetch ... github.com/kevoreilly/CAPEv2.git "$CAPE_REF"` | Yes (the SHA above) | Commit-level only, no GPG check |
| cape/Dockerfile:38-39 | `GUACAMOLE_VERSION=1.6.0`, `GUACAMOLE_SHA256=8bc4...` | Yes | Yes: sha256 checked at line 47 (`sha256sum -c -`) |
| cape/Dockerfile:45-46 | curl archive.apache.org guacamole-server 1.6.0 tarball | Yes | Verified by line 47 |
| cape/Dockerfile:74 | `uv pip install "libvirt-python==$(pkg-config --modversion libvirt)"` | Version = whatever libvirt the image has | No hash. Version follows the apt package. |
| cape/Dockerfile:79 | `uv pip install --no-deps --require-hashes -r volatility3.requirements` | Yes: `volatility3==2.28.2` (cape/build/volatility3.requirements:5) | Yes: sha256 pinned in the requirements file |
| cape/Dockerfile:75 | `.venv/bin/python utils/community.py -waf -cr` | Not pinned: community.py:315 downloads `github.com/kevoreilly/community/archive/master.tar.gz` (`--branch` default "master", community.py:208) | No checksum |
| cape/Dockerfile:75 | (same command) capa rules | Not pinned: community.py:47 `github.com/mandiant/capa-rules/archive/master.zip`, and community.py:38-40 `mandiant/capa/raw/master/sigs/*.sig` | No checksum |
| cape/Dockerfile:127-128 | `cape2.sh suricata` then `suricata-update` | Not pinned: installer/cape2.sh:739 `add-apt-repository -y ppa:oisf/suricata-7.0`; line 740 installs `suricata` unversioned. suricata-update fetches the ruleset at build time. | No checksum |
| cape/Dockerfile:109 | `apt-get download ovmf` (no version) | No | No checksum |
| cape/Dockerfile:22-23, 41-43, 62-64, 91-92, 164, 169 | `apt-get install` of many packages, no versions | No (floating Ubuntu 24.04 archive) | apt's own signing only |
| cape/Dockerfile:26-28 | QEMU / SeaBIOS build via CAPE's `kvm-qemu.sh` | `qemu_version=9.2.2` (installer/kvm-qemu.sh:61), `seabios_version=1.16.3` (:65) | QEMU: `wget` of qemu-9.2.2.tar.xz and .sig (:861-862), then `gpg --verify` (:863). No key import in the script, no `set -e`, and gpg's exit status is not checked, so the signature is not an enforced gate. SeaBIOS: `wget` of GitHub tag tarball (:981-982), no checksum, no signature. |
| cape/Dockerfile:65 | `COPY --from=ghcr.io/astral-sh/uv:0.12` | Tag only (minor) | No digest |
| cape/Dockerfile:2,13,37,60,85 | `FROM ubuntu:24.04` (5 stages) | Tag only | No digest |

Note on the libvirt tarball: kvm-qemu.sh:487-489 downloads libvirt sources with a gpg check, but the Dockerfile uses Ubuntu's libvirt packages, so that path is not run.

### 3b. cape/ runtime fetches (not in Dockerfile)
- cape/bin/symbols_logic.py:45 `SYMBOL_SERVER = "https://msdl.microsoft.com/download/symbols"`: Windows PDBs fetched at runtime. Identified by PDB GUID, not by a pinned hash.
- cape/bin/memory_logic.py and volatility: the wheel itself is hash-pinned (above).

### 3c. guest/ (Windows analysis guest provisioning)

guest/profiles/windows/manifest.sha256 (lines 7-9), enforced by guest/steps/fetch:
- :7 `af19e5e2f03e715a822181f2cb7d4efef4eda13fa4a2db6da12e998e46f5cbf9 python-3.11.9.exe https://www.python.org/ftp/python/3.11.9/python-3.11.9.exe`. Pinned version and sha256. Verified at fetch:34 (`has_sha256 ... || fail "sha256 mismatch"`). No signature check.
- :8 `7086cc1d5eebb91ad24ded9f58bec6c688e9f0ed7eb3dbbf1e4800280a896496 pillow-10.4.0-cp311-cp311-win32.whl https://files.pythonhosted.org/...`. Pinned version and sha256. Verified at fetch:34. Installed offline by guest/profiles/windows/provision.ps1:108 (`pip install --no-index`).
- :9 `83d31f2478dc6716cfdbf69e5c384bf043072b5f0d8d7b2eea365f709fda4352 Sysmon64.exe https://live.sysinternals.com/Sysmon64.exe`. Pinned by sha256 only. The URL has no version (Sysinternals updates in place), so a Sysmon update fails the build (fail-closed) rather than silently changing the binary. Verified at fetch:34.
- guest/steps/fetch:33 `curl -fsSL --retry 3 ... "$url"` with the hash check at :34. Sound for what the manifest lists.
- guest/steps/install:40-43 reads the same manifest and requires the cache file to exist.

Pillow 10.4.0 guest pin, audited separately with `uvx pip-audit -r` on `pillow==10.4.0`: 63 advisory entries, fix versions up to 13.0.0 as printed. This pin is not in the backend or CAPE lock. It is in the Windows guest, so exposure is through the analysed guest's agent, not the host containers.

### 3d. CAPE locked Python dependencies (in the cape image)

CAPE's own uv.lock at the pinned SHA (`/opt/CAPEv2`, Dockerfile line 72 `uv sync --frozen --no-dev`). Exported with `uv export --frozen --no-hashes --no-dev --no-emit-project` (196 pins) and audited:

338 advisory entries across 36 packages. Largest counts as printed: django 6.0 (51), pypdf 6.5.0 (82), pillow 12.0.0 (71), cryptography 46.0.3 (13), pyjwt 2.10.1 (22), sqlparse 0.5.5 (9), pyasn1 0.5.1 (8), urllib3 2.6.2 (9), soupsieve 2.8.1 (6), djangorestframework 3.15.2 (5), daphne 4.2.1 (4), pymongo 4.15.5 (4), pyopenssl 25.3.0 (4). Other packages with 1 to 3 entries: anyio, autobahn, capstone, certifi 2025.11.12, django-allauth, h2, hpack, idna, lxml, mako, msgpack, multidict, orjson, paramiko (no fix printed), pip, protobuf, pygments, python-dotenv, pyzipper, requests, setuptools, twisted, werkzeug.

Reachability: supervisord runs `cape-web` (gunicorn serving web.wsgi, Django) at `%(ENV_CAPE_INTERNAL_IP)s:8000` (cape/supervisord.conf:114-115). That is the CAPE_API_URL the backend uses (docker-compose.yml:69). So Django and DRF are in a running, network-reachable service, not only installed. Other items (pypdf, pillow, daphne) were not traced to a runtime path.

Per-advisory fix versions are in the JSON file under the scratchpad path above (cape-pipaudit.json). The "fix" column above is only the highest value listed per package.

---

## 4. Base images (FROM and image:)

Pinned by tag only, with no `@sha256:` digest anywhere in the repo (grep returned none).

| File:line | Image | Pin |
|---|---|---|
| backend/Dockerfile:1 | `python:3.12-slim` | floating patch, no digest |
| backend/Dockerfile:3 | `ghcr.io/astral-sh/uv:0.12` | minor tag, no digest |
| frontend/Dockerfile:1 | `node:24-alpine` | major tag, no digest |
| frontend/Dockerfile:20 | `nginx:alpine` | floating, no version, no digest |
| cape/Dockerfile:2,13,37,60,85 | `ubuntu:24.04` (5 stages) | tag only, no digest |
| cape/Dockerfile:65 | `ghcr.io/astral-sh/uv:0.12` | minor tag, no digest |
| docker-compose.yml:4 | `postgres:16` | major tag, no digest |
| docker-compose.yml:29 | `opensearchproject/opensearch:3.9.0` | exact version tag, no digest |
| docker-compose.yml:58,108,132 | `tartarus-backend:latest`, `tartarus-frontend:latest`, `tartarus-cape:latest` | built locally, `:latest` |
| docker-compose.dev.yml:11,32 | `tartarus-backend:dev`, `tartarus-frontend:dev` | built locally |

Lockfile integrity is complete for the app dependencies: frontend/package-lock.json has 816 `"integrity"` entries, src-pwa/package-lock.json has 349, backend/uv.lock has 648 `sha256:` references. cape/build/volatility3.requirements is hash-pinned. The CAPE uv.lock is checked out at the pinned SHA, not in this repo.

CI (`.github/workflows/ci.yml`): actions are referenced by tag, not SHA (`actions/checkout@v4`, `astral-sh/setup-uv@v5`, `actions/setup-node@v4`). No dependency-audit step runs in CI.

---

## 5. Dependabot

`.github/dependabot.yml`: does not exist. `.github/` contains only `workflows/ci.yml`.

Proposed (not created):

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
  - package-ecosystem: "npm"
    directory: "/frontend/src-pwa"
    schedule:
      interval: "weekly"
  - package-ecosystem: "docker"
    directory: "/backend"
    schedule:
      interval: "weekly"
  - package-ecosystem: "docker"
    directory: "/cape"
    schedule:
      interval: "weekly"
  - package-ecosystem: "docker"
    directory: "/frontend"
    schedule:
      interval: "weekly"
  - package-ecosystem: "docker-compose"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

Caveats, not verified against Dependabot docs in this session:
- The "pip" ecosystem reads pyproject.toml and does not update uv.lock. If Dependabot offers a "uv" ecosystem in your account, use that for /backend so uv.lock is bumped.
- The "docker-compose" ecosystem name is unverified here. Remove that entry if Dependabot rejects it.
- Dependabot cannot update the CAPE_REF SHA or the manifest.sha256 entries. Those need a manual bump.

---

## 6. Licenses (shipped runtime dependencies)

### 6a. Backend (prod)

Command: `cd backend && uv run --frozen --no-dev --with pip-licenses pip-licenses --format=csv --with-urls`. The environment also contained dev packages (pytest, ruff, mypy, testcontainers appear in the listing), so the CSV was filtered to the 75 names from `uv export --no-dev`. 74 of 75 matched. `brotlicffi` (in uv.lock with a marker) is absent from this interpreter's listing, so it was not checked.

Copyleft or non-permissive entries in the prod set, verbatim from pip-licenses:
- pySigma 2.0.1: `LGPL-2.1-only`. Weak copyleft. The FSF lists LGPLv2.1 as GPLv3-compatible, but this is a `-only` license, so review before release.
- pyphen 0.18.1: `GNU General Public License v2 or later (GPLv2+); GNU Lesser General Public License v2 or later (LGPLv2+); Mozilla Public License 1.1 (MPL 1.1)`. Tri-licensed. The GPLv2+ option is usable under GPLv3.
- certifi 2026.7.22: `Mozilla Public License 2.0 (MPL 2.0)`. Compatible with GPLv3 (MPL 2.0 secondary-license clause).

No AGPL, SSPL, proprietary, or "no license" entries in the backend prod set.

Also in the list: `Apache-2.0` (9), `Apache Software License` (7), `MIT` / `MIT License` / `MIT-0` / `MIT-CMU` (total 27 incl. `MIT AND PSF-2.0`), `BSD` variants (25), `PSF-2.0` (2), `Apache-2.0 OR BSD-2-Clause`, `Apache Software License; MIT License`, `MIT OR AFL-2.1`. All GPLv3-compatible.

### 6b. Frontend (`frontend/`, `npx license-checker --production --summary`)

```
MIT: 106
Apache-2.0: 3
BSD-2-Clause: 2
MPL-2.0: 2
ISC: 2
BSD-3-Clause: 2
(Apache-2.0 AND BSD-3-Clause): 1
BSD*: 1
UNLICENSED: 1
0BSD: 1
```

- MPL-2.0 (2): lightningcss and lightningcss-linux-x64-gnu 1.33.0. Reached through vite 8.3.4 (`npm ls`: `@quasar/app-vite@3.10.2 → vite@8.3.4 → lightningcss@1.33.0`). Build-time CSS tooling. MPL-2.0 is GPLv3-compatible.
- BSD*: guacamole-common-js 1.5.0. license-checker could not parse the metadata. Its LICENSE file is the Apache License 2.0 text (frontend/node_modules/guacamole-common-js/LICENSE). Apache-2.0 is GPLv3-compatible.
- UNLICENSED: `tartarus-frontend@0.0.1`, the project's own private root package (frontend/package.json has `"private": true` and no `license` field). Not a third-party dependency, but see the project-license gap below.

Not GPL-3.0-compatible: none found in the frontend prod set.

### 6c. src-pwa (`npx license-checker --production --summary`)
```
UNLICENSED: 1   (quasar-pwa-app@1.0.0, the project's own root)
MIT: 1
```

### 6d. Gap for the release LICENSE step
- No LICENSE, COPYING or NOTICE file exists at the repo root (`ls -la` showed none).
- frontend/package.json and frontend/src-pwa/package.json have no `license` field, and the root packages are `UNLICENSED` per license-checker.
- Backend pyproject.toml was not checked for a license field in this audit.

Decide and add the project license before the release step. Nothing in this audit selects one.

---

## Critical and high: list

- npm: 4 high, all devDependency (@hey-api/openapi-ts, @hey-api/json-schema-ref-parser, @hey-api/shared, js-yaml). Not in the shipped bundle. Fix: an `overrides` for js-yaml to 4.3.2 (untested) rather than npm's suggested downgrade.
- No critical findings from any tool.
- No high findings in pip-audit, because pip-audit prints no severity. Advisories that matter most in runtime scope: pillow 12.3.0 (34, prod), certifi (1, prod), diskcache (2, prod), and CAPE's Django 6.0 (51) in a running service.
- Guest Pillow 10.4.0 (63): in the Windows guest, not the host containers.
