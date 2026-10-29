# Third-party components

Tartarus itself is licensed under the [GNU General Public License v3.0](LICENSE) (SPDX: `GPL-3.0-only`).
This file lists what it ships, builds, downloads or depends on, under which license, and what each
license asks of you. Everything below keeps its own license; none of it is relicensed by Tartarus.
The per-package list for the Python and npm dependencies is generated into [docs/licenses.md](docs/licenses.md).

Checked on 2026-10-26 against the files in this repository and the upstream sources named in each row.
Where a license could not be established from the source, the cell says **unverified** and
[Unverified items](#unverified-items) says how to check it. This is a good-faith inventory, not legal advice.

## Things to know

The short version: **the repository contains only the Sigma rules and the ATT&CK table among third-party
material.** Everything else (CAPE, QEMU, Volatility3, Sysmon, the ET rules, the guest's Python) is fetched
or built on your machine by `make up` and the guest build, from pinned sources. Tartarus does not publish
a container image or a guest disk image. The sections below say what changes if you do.

| Component | License | Does Tartarus redistribute it? | What the README and guide must tell the user |
|---|---|---|---|
| **Volatility3** 2.28.2 | [Volatility Software License 1.0](https://www.volatilityfoundation.org/license/vsl-v1.0) (VSL). **Not an OSI license** and not the GPL: it is a source-available copyleft written by the Volatility Foundation | **No.** Not in the repo. [cape/build/volatility3.requirements](cape/build/volatility3.requirements) pins the PyPI wheel by sha256; the `cape` image build installs it into CAPE's virtualenv on the user's machine | The `cape` image includes Volatility3 under the VSL, which is not the GPL. See the VSL paragraph below |
| **Sysmon** (Sysinternals) | [Sysinternals Software License Terms](https://learn.microsoft.com/sysinternals/license-terms) (Microsoft EULA, proprietary) | **No.** Downloaded from `live.sysinternals.com` into the build cache (sha256-pinned in [guest/profiles/windows/manifest.sha256](guest/profiles/windows/manifest.sha256)) and installed in the user's own guest | Building a guest with the Sysmon option on installs Sysmon and runs it with `-accepteula`, which **accepts Microsoft's license terms on the user's behalf**. Do not copy or share a built guest disk: the terms forbid publishing the software for others to copy |
| **Emerging Threats Open rules** | Per rule: GPL-2.0 for sids 1 to 3464 and 100000000 to 100000908; BSD-3-Clause for sids 2000000 to 2799999 (verified from `rules/LICENSE` in the ruleset archive) | **No.** `suricata-update` downloads them into the `cape` image at build time, as a snapshot (nothing in the container runs the updater afterwards) | Nothing blocks use. Keep the rules' `LICENSE` if you pass the ruleset on; the Pro range (sids 2800000 to 2900000) is not in the Open feed |
| **SigmaHQ rules** (61 files) | [Detection Rule License 1.1](rules/sigma/default/LICENSE.Detection.Rules.md) (DRL), permissive with attribution | **Yes, in the repo** under [rules/sigma/default](rules/sigma/default), copied unmodified at SigmaHQ commit `7d8b152a5fc062ebd309f62ae4d8276aca2786af` | Rules keep their `author` field and the DRL text sits beside them ([ATTRIBUTION.md](rules/sigma/default/ATTRIBUTION.md)). The DRL also says messages built from a rule match must keep the rule's author; see "DRL author retention" below |
| **MITRE ATT&CK** data (v19.2) | MITRE ATT&CK Terms of Use: free license for research, development and commercial use, provided MITRE's copyright and license are reproduced in any copy | **Yes, in the repo**, as the derived table [backend/app/data/attack_techniques.json](backend/app/data/attack_techniques.json) | The notice in [Notices](#notices) must stay with the table. It had been missing; it is added here |
| **Windows** (guest OS) | Microsoft's own license for the user's copy | **No.** The user supplies the ISO; Tartarus never bundles or downloads Windows | The user needs a valid Windows license and ISO. A built guest disk contains Windows and must not be shared |
| **kevoreilly/community** repo and **capa rules** | `community`: **no license file** in the repository, a mix of authors and vendored binaries (unverified). capa-rules and capa signatures: Apache-2.0 | **No.** `utils/community.py -waf -cr` downloads both from their `master` branches while the `cape` image builds | They are unpinned and arrive as the day's `master`. Auditing is the user's job if they redistribute the image |
| **QEMU, SeaBIOS, CAPEv2, INetSim, capemon** | GPL and LGPL (rows below) | **No**, built on the user's machine. QEMU and SeaBIOS are rebuilt with their anti-VM strings changed (`cape/build/kvm-config.sh`); the analyzer is patched by `cape/patches/` | Publishing a built `cape` image would be redistribution: you would owe the corresponding source for these (and the license texts), including the modified QEMU, SeaBIOS and analyzer |

**Volatility Software License.** The VSL lets you use, share and build with Volatility for free. It requires
that everyone who gets a copy from you also gets the license text or its link, that you keep copyright
notices, and that "Additions" be made publicly available. "Additions" include changes to Volatility and
"any software designed to execute the software and parse its results, such as a wrapper". Tartarus runs
the `vol` command line as a separate process and parses its JSON, in
[cape/bin/volatility.py](cape/bin/volatility.py), [cape/bin/memory_logic.py](cape/bin/memory_logic.py) and the
backend's `app/ingest/volatility*.py`. That code plausibly counts as an Addition. It is published here, in
the public repository, which is what the clause asks for. The VSL's wording on whether an Addition must also
be licensed under the VSL, rather than only be published, is not clear to us, and we are not a lawyer: the
code stays GPL-3.0-only and public; anyone who distributes a modified or closed build should have the VSL
read by a lawyer first. The VSL text is not in this repository because Volatility is not; it comes with the
wheel and is at the URL above.

**DRL author retention (resolved).** The DRL asks that messages based on a rule match retain the rule's
author when the rule supplies one. The loader ([backend/app/rules/loader.py](backend/app/rules/loader.py))
reads the rule's `author` into `Rule.author`; the Sigma alert it raises carries it as the ECS field
`rule.author`; the Detections view returns it as `author` and the detail pane prints "Rule author:
...". The HTML and PDF reports print the same line under each detection that has one. A rule without an
author shows nothing. The STIX, MISP and CSV exports do not print a rule's name or description, so there
is no rule-derived text in them that could carry the author.

**Why GPL-3.0 sits well with CAPE.** The `cape/` directory adds Python modules that CAPE imports (the
`event_logs` auxiliary) and patches CAPE's analyzer. Those are derivative of CAPEv2 (GPL-3.0), so the
project's own GPL-3.0 license is the one that keeps that code compatible. Talking to CAPE only over its REST
API, as the backend does, would not have required it.

## Built or bundled into the images

"Pin" is how the source is fixed. "In repo" means the files are in this repository; everything else is
fetched when the image or guest is built.

### The `cape` image ([cape/Dockerfile](cape/Dockerfile))

| Component | Version or pin | License (SPDX) | How it is included | Source |
|---|---|---|---|---|
| CAPEv2 | `CAPE_REF` 9f806acd24ae23ee9a52cf4f1e82657635f07659 (git commit) | GPL-3.0 (the `LICENSE` file is the GPLv3 under a Cuckoo Foundation header; it does not say "or later") | Fetched by commit SHA, installed in `/opt/CAPEv2`; Tartarus patches its analyzer and adds an auxiliary module | https://github.com/kevoreilly/CAPEv2 |
| capemon (CAPE's monitor DLL) and the analyzer | Prebuilt `capemon.dll` and `capemon_x64.dll` in the CAPEv2 tree at `CAPE_REF` | GPL-3.0 (GitHub license API for capemon). Derived from cuckoomon-modified (spender-sandbox); also includes code derived from Scylla, WOW64Ext and W64oWoW64, whose licenses are **unverified** | Part of the CAPEv2 checkout; the analyzer and DLLs are uploaded into the guest for every task | https://github.com/kevoreilly/capemon |
| CAPE Python dependencies | 196 packages from CAPEv2's own `uv.lock` | 181 permissive, 5 LGPL (chardet, paramiko, pebble, psycopg2-binary, pygal), 3 GPL (crudini GPL-2.0, pcodedmp and sflock2 GPL-3.0), 1 MPL-2.0 (certifi), 6 declare nothing in PyPI metadata (**unverified**: bs4, ida-settings, maco, peepdf-3, pythonaes, setuptools) | `uv sync --frozen --no-dev` into CAPE's virtualenv. Counted from PyPI metadata at the locked versions; CAPE runs them as its own program, Tartarus code does not import them | https://github.com/kevoreilly/CAPEv2/blob/9f806acd24ae23ee9a52cf4f1e82657635f07659/uv.lock |
| CAPE community content | `master` of kevoreilly/community, unpinned | **unverified**: no license file in the repo; mixed authors and vendored tools | `utils/community.py -waf -cr`: signatures, parsers, YARA rules, analyzer modules, data | https://github.com/kevoreilly/community |
| capa rules and FLARE signatures | `master` of mandiant/capa-rules and mandiant/capa `sigs/`, unpinned | Apache-2.0 (repository license; the signatures' own terms are **unverified**) | Downloaded by the same command | https://github.com/mandiant/capa-rules |
| QEMU | 9.2.2, source tarball | GPL-2.0 (the emulator as a whole; some files BSD, MIT or GPL-2.0-or-later per QEMU's `LICENSE`) | Built from source by CAPE's `kvm-qemu.sh` with Tartarus's anti-VM strings, packaged as `qemu.deb` | https://download.qemu.org/qemu-9.2.2.tar.xz |
| SeaBIOS | 1.16.3 | LGPL-3.0 (most files; a few others per Debian's copyright file) | Built from source by `kvm-qemu.sh seabios`, strings replaced; only `bios.bin` and `bios-256k.bin` are copied into the final image | https://github.com/coreboot/seabios |
| libvirt | Ubuntu 24.04 package (10.0) | LGPL-2.1-or-later (library; daemon parts GPL-2.0-or-later by Debian's file) | `libvirt-daemon-system`, `libvirt-clients` from apt | https://libvirt.org |
| libvirt-python | Pinned to the installed libvirt version | LGPL-2.1-or-later (**unverified** from the source; PyPI lists LGPL) | `uv pip install` in CAPE's virtualenv | https://pypi.org/project/libvirt-python/ |
| OVMF (UEFI firmware) | Ubuntu 24.04 `ovmf` package, two `4M.ms` images | BSD-2-Clause-Patent for EDK II, with per-file licenses (OpenSSL, BSD-3-Clause, MIT) | Two firmware files extracted from the apt package | https://github.com/tianocore/edk2 |
| swtpm | Ubuntu 24.04 package | BSD-3-Clause (with some CPL-1.0 files, per Debian's copyright) | apt | https://github.com/stefanberger/swtpm |
| Apache Guacamole `guacd` | 1.6.0, sha256 `8bc45675...bf13f2b` (checked: the tarball's `LICENSE` is Apache-2.0) | Apache-2.0 | Built from the source tarball, VNC only | https://archive.apache.org/dist/guacamole/1.6.0/source/ |
| INetSim | 1.3.2 (Ubuntu package) | GPL-2.0-or-later (Debian copyright; `Fork.pm` is GPL-1.0-or-later or Artistic) | apt; one line of its DNS module is patched with `sed` | https://www.inetsim.org |
| Suricata | 7.0.x from `ppa:oisf/suricata-7.0` (not pinned) | GPL-2.0 (per Debian's copyright; some files MIT or Apache-2.0) | Installed by CAPE's `cape2.sh suricata` | https://suricata.io |
| ET Open ruleset | Whatever `suricata-update` fetches at build time (not pinned) | GPL-2.0 and BSD-3-Clause by sid range, see "Things to know" | `suricata-update` during the image build | https://rules.emergingthreats.net/open/ |
| Volatility3 | 2.28.2, sha256 `0461d6dd...165181fbd3c3` | VSL 1.0 (PyPI metadata says `VSL`; the repo's `LICENSE.txt` is the text) | `uv pip install --no-deps --require-hashes` into CAPE's virtualenv; run as a subprocess | https://github.com/volatilityfoundation/volatility3 |
| 7-Zip console build (`7za.exe`, x86) | 26.03 (2026-09-04), `7z2603-extra.7z` sha256 `191894e6...2e59b8f` | LGPL-2.1-or-later (the 7-Zip license puts the `unRAR license restriction` on some code of `7z.dll` only; `7za.exe` is the standalone console build, which has no RAR code, and "all other files" are plain LGPL). Its `License.txt` is installed beside it as `7-Zip-License.txt`, which the license asks for in binary redistributions | Downloaded from 7-zip.org by the `cape` build, checked against the pinned hash, unpacked with the image's `7z` and installed as `analyzer/windows/bin/7z.exe`, so the analyzer uploads it to the guest for every task. CAPE's `zip` package needs it to open AES-encrypted zips (`cape/patches/zip-bundled-7zip.py` adds its path). Run as a separate process, not linked | https://www.7-zip.org ([license](https://www.7-zip.org/license.txt)) |
| Windows symbols for Volatility | Fetched from Microsoft's symbol server when a memory dump is analyzed | Microsoft's symbol server terms: **unverified** | `cape/bin/symbols_logic.py` (`msdl.microsoft.com`) | https://msdl.microsoft.com/download/symbols |
| tcpdump and libpcap | Ubuntu 24.04 packages | BSD-3-Clause (tcpdump; libpcap is BSD-3-Clause too, **unverified**) | apt; given `cap_net_raw` and `cap_net_admin` as file capabilities | https://www.tcpdump.org |
| Other apt packages: `dnsmasq-base`, `iptables`, `nftables`, `p7zip-full`, `upx-ucl`, `xorriso`, `wimtools`, `supervisor`, `cron`, `curl`, `sudo`, `iproute2`, `gettext-base` | Ubuntu 24.04 (digest-pinned base image) | dnsmasq GPL-2.0 or GPL-3.0; iptables and nftables GPL-2.0; p7zip LGPL-2.1-or-later (the unRAR code is removed in Debian's repack); upx GPL-2.0-or-later with a special exception; xorriso GPL-2.0-or-later (libisoburn); wimlib GPL-3.0-or-later and LGPL-3.0-or-later; supervisor BSD-style; cron ISC and GPL-2.0-or-later. From Debian's current copyright files, not the exact Ubuntu 24.04 versions: **unverified** for those versions | apt in the final image | https://packages.ubuntu.com/noble/ |
| mingw-w64 (`gcc-mingw-w64-x86-64`) | Ubuntu 24.04 package | GPL-3.0-or-later compiler with the GCC Runtime Library Exception; mingw-w64 runtime LGPL-2.1-or-later, ZPL and public-domain parts | apt, in the final image to build the guest self-test's benign sample on request. Nothing it compiles ships | https://www.mingw-w64.org |
| Ubuntu 24.04 base | `ubuntu:24.04@sha256:68ee2200...` | Many (each package its own; see `/usr/share/doc/*/copyright`) | Base image of all `cape` stages | https://ubuntu.com |
| uv | 0.12, digest-pinned | MIT OR Apache-2.0 | Copied into the build stage only | https://github.com/astral-sh/uv |

### Other images

| Component | Version or pin | License (SPDX) | How it is included | Source |
|---|---|---|---|---|
| PostgreSQL | `postgres:16` by digest | PostgreSQL License | Separate container, pulled from Docker Hub | https://www.postgresql.org/about/licence/ |
| OpenSearch | `opensearchproject/opensearch:3.9.0` by digest | Apache-2.0 | Separate container, pulled from Docker Hub | https://github.com/opensearch-project/OpenSearch |
| nginx | `nginx:1.31.8-alpine3.24` by digest | BSD-2-Clause | Serves the built frontend; the base of the `frontend` image | https://nginx.org/LICENSE |
| Alpine Linux, Node.js 24 | `node:24-alpine` by digest | MIT (Node.js); Alpine packages each their own | **Build stage only**, not in the final frontend image | https://nodejs.org |
| Python 3.12 and Debian slim | `python:3.12-slim` by digest | PSF-2.0 (CPython); Debian packages each their own | Base of the `backend` image | https://www.python.org |

### Backend (Python) dependencies

74 production packages, resolved by `backend/uv.lock`. Counted by declared license
(see [docs/licenses.md](docs/licenses.md) for each one):

| License | Packages |
|---|---|
| MIT | 27 |
| BSD (2-clause, 3-clause and unspecified) | 21 |
| Apache-2.0 | 16 |
| Several permissive licenses combined (e.g. `Apache-2.0 AND MIT`, `MIT AND PSF-2.0`, `BSD; Public Domain`) | 5 |
| PSF-2.0 | 2 |
| MPL-2.0 (certifi) | 1 |
| LGPL-2.1-only (pySigma) | 1 |
| GPL-2.0+ / LGPL-2.1+ / MPL-1.1 tri-license (pyphen) | 1 |

Method: `uv sync --frozen --no-dev` into a scratch environment, then `uvx pip-licenses --from=mixed --with-urls --format=json`
(the exact commands are at the top of [docs/licenses.md](docs/licenses.md)). The PyPy-only `brotlicffi` is
not installed on CPython and is not counted; PyPI declares it MIT. No AGPL, SSPL, proprietary or
"no license" entry is in the production set. Installed into the `backend` image from PyPI; not vendored.

### Frontend (npm) dependencies

120 packages in the production tree (`npx license-checker --production --excludePrivatePackages`):
MIT 106, BSD-2-Clause 2, BSD-3-Clause 2, Apache-2.0 3, MPL-2.0 2, ISC 2, 0BSD 1, one `Apache-2.0 AND BSD-3-Clause`, and `guacamole-common-js` (shown as `BSD*`, Apache-2.0 in fact).
The direct runtime dependencies are Vue 3, Quasar and `@quasar/extras`, Pinia, Vue Router, vue-i18n,
cytoscape, cytoscape-dagre and `guacamole-common-js` 1.5.0, all MIT except `guacamole-common-js`
(Apache-2.0: its license file is the Apache License 2.0; `license-checker` shows it as `BSD*` because it
cannot parse the metadata). Compiled into the bundle served by nginx.

Also in the built frontend: the **Material Icons** and **Material Icons Outlined** fonts (Google), two
`woff2` files copied from `@quasar/extras`, whose `LICENSE` for both is Apache-2.0. The theme uses system
fonts, so no other font is shipped.

The production tree includes build tools that only run at build time (`vite`, `terser`, `lightningcss`,
`typescript` come in as optional peers). They are not in the bundle. The dev toolchain (eslint, vitest,
Playwright, the OpenAPI generator, `vue-tsc`) is not shipped and not scanned.

## Guest provisioning (downloaded into the Windows guest)

Fetched by the guest build's `fetch` step into a local cache, checked against
[guest/profiles/windows/manifest.sha256](guest/profiles/windows/manifest.sha256), then copied into the guest.
None of it is in the repository. The `fetch` step downloads all three files whatever the options;
Sysmon is only installed in the guest when its option is on.

| Component | Version or pin | License (SPDX) | How it is included | Source |
|---|---|---|---|---|
| Python for Windows (32-bit) | 3.11.9, sha256 `af19e5e2...` | PSF-2.0 (the installer also carries other libraries under their own licenses: unverified) | Installed in the guest so CAPE's agent can run | https://www.python.org/ftp/python/3.11.9/python-3.11.9.exe |
| Pillow (win32 wheel) | 10.4.0, sha256 `7086cc1d...` | HPND (declared in PyPI metadata; the wheel bundles C libraries under their own licenses: unverified) | Installed in the guest for screenshots | https://pypi.org/project/pillow/10.4.0/ |
| Sysmon64 | Latest at the pinned sha256 `83d31f24...` | Sysinternals Software License Terms (proprietary EULA, not redistributable) | Installed in the guest when the option is on; configured with Tartarus's own `sysmon-config.xml` (GPL-3.0-only, written for this project) | https://live.sysinternals.com/Sysmon64.exe |
| Windows 11 or 10 | The user's ISO | Microsoft | Installed by the guest build from `data/iso/` | n/a |
| CAPE agent and analyzer | From the `cape` image | GPL-3.0 | Uploaded into the guest by CAPE for every task | see CAPEv2 above |

The guest self-test and the profile's PowerShell scripts are Tartarus's own code (GPL-3.0-only).

## Data and rules in the repository

| Item | License | Notes |
|---|---|---|
| [rules/sigma/default](rules/sigma/default) | DRL 1.1 | 61 SigmaHQ rules, unmodified. Attribution and license text beside them |
| [rules/sigma/tartarus](rules/sigma/tartarus) | GPL-3.0-only | The project's own self-test rule |
| [backend/app/data/attack_techniques.json](backend/app/data/attack_techniques.json) | MITRE ATT&CK Terms of Use | Technique ids, names and tactics from the Enterprise matrix v19.2, built by `scripts/build-attack-table.py` from `mitre-attack/attack-stix-data` |
| [guest/profiles/windows/sysmon-config.xml](guest/profiles/windows/sysmon-config.xml) | GPL-3.0-only | Written for this project, not copied from a public configuration set |
| `verify-cape.sh` test image | Cirros 0.6.3, sha256-pinned; license **unverified** | Downloaded only when you run `make verify-cape`; not part of the product |

## Review items from the dependency audit

The earlier audit ([docs/history/m11-notes/C5-dependencies.md](docs/history/m11-notes/C5-dependencies.md),
section 6) flagged four entries. Verdicts for a GPL-3.0-only project:

| Entry | License | Verdict | Reasoning |
|---|---|---|---|
| **pySigma** 2.0.1 | LGPL-2.1-only | **Compatible** | LGPL-2.1 section 3 lets anyone apply the ordinary GPL to a copy of the library, and says a later GPL version than 2 may be named, which covers GPLv3. Tartarus imports it unmodified from PyPI and does not vendor or alter it, so the LGPL's own conditions (keep the notices, allow replacing the library) are met by the way it is installed. The `-only` only blocks moving to LGPL-3.0, which nothing here needs |
| **pyphen** 0.18.1 | GPL-2.0+ or LGPL-2.1+ or MPL-1.1 | **Compatible** | A tri-license is a choice. We take the GPL-2.0-or-later (or LGPL-2.1-or-later) option; "or later" allows combining with GPLv3 code. It is used by WeasyPrint for hyphenation in the PDF report |
| **certifi** 2026.10.19 | MPL-2.0 | **Compatible** | MPL-2.0 section 3.3 allows combining with GPL-3.0 code (GPL is a listed Secondary License) unless the file carries an "Incompatible With Secondary Licenses" notice; certifi is an unmodified data bundle and we do not edit its files |
| **lightningcss** 1.33.0 | MPL-2.0 | **Compatible, build-time only** | A CSS minifier used by Vite while building. It is not in the served bundle, MPL-2.0 is file-level copyleft, and its output is not a derivative of it |

The audit's first-line finding stands: no AGPL, SSPL, proprietary or unlicensed runtime dependency.
`guacamole-common-js`, reported as `BSD*`, is Apache-2.0 (Apache-2.0 and GPL-3.0 are compatible one way:
Apache-2.0 code may go into a GPL-3.0 work).

## Notices

**MITRE ATT&CK.** The technique table `backend/app/data/attack_techniques.json` is derived from
MITRE ATT&CK®. MITRE's terms ask that this designation and license are reproduced in any copy:

> The MITRE Corporation (MITRE) hereby grants you a non-exclusive, royalty-free license to use ATT&CK® for
> research, development, and commercial purposes. Any copy you make for such purposes is authorized
> provided that you reproduce MITRE's copyright designation and this license in any such copy.
>
> "© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation."

Terms of use: https://attack.mitre.org/resources/legal-and-branding/terms-of-use/. The sentence in quotes
is printed in the footer of the HTML and PDF reports and on the Settings page's About card, with a link
to the terms. The STIX and MISP exports, which also name ATT&CK techniques, do not carry it yet.

**SigmaHQ rules.** The files in `rules/sigma/default` come from https://github.com/SigmaHQ/sigma
(`rules/windows/`), licensed under the [Detection Rule License 1.1](rules/sigma/default/LICENSE.Detection.Rules.md);
the rule authors are named in each file's `author` field.

## Unverified items

| Item | How to check |
|---|---|
| kevoreilly/community repo-wide license and its vendored tools (7zz, innoextract, TrID, procyon, NETReactorSlayer, YARA rule sets) | The repo has no `LICENSE`; inspect each tool's license in `data/` and the headers of `data/yara/` after the image build, inside `/opt/CAPEv2/` |
| capemon's bundled Scylla, WOW64Ext and W64oWoW64 code | Read the headers in https://github.com/kevoreilly/capemon and each upstream's license |
| CAPE virtualenv packages with no license metadata: bs4 0.0.1, ida-settings, maco, peepdf-3, pythonaes, setuptools | `docker run --rm --entrypoint /opt/CAPEv2/.venv/bin/python tartarus-cape -c "import importlib.metadata as m; print(m.metadata('<name>'))"`, then the package's own repository |
| Debian and Ubuntu package licenses in the `cape` image | Licenses above are from Debian's current copyright files (sources.debian.org). For the exact versions, read `/usr/share/doc/<package>/copyright` in the image |
| libvirt-python and libpcap exact license | https://libvirt.org/git/?p=libvirt-python.git and https://github.com/the-tcpdump-group/libpcap/blob/master/LICENSE |
| Windows symbol server terms of use (Volatility PDB downloads) | Microsoft's symbol server and Terms of Use pages, before relying on bulk downloads |
| FLARE signatures `sigs/` terms | https://github.com/mandiant/capa/tree/master/sigs |
| Libraries bundled inside the guest's Python 3.11.9 installer and the Pillow 10.4.0 wheel | Open the wheel (`unzip -l`) and check its `licenses` folder; read the Python 3.11.9 installer's license notices |
| Whether the DRL is accepted as free by the OSI or FSF | Not checked. Its text is MIT-like with attribution conditions; the rules are data under their own license, kept apart from Tartarus's code |
