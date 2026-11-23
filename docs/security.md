# Security

How Tartarus is built to contain what it runs, what the v1 security review found and fixed, and the risks that remain. Tartarus runs live malware
in Windows guests and parses the data that malware produces, so both directions matter: a hostile guest must not reach anything but its
gateway, and hostile data must not harm the backend or the analyst's browser.

To report a vulnerability, see [SECURITY.md](../SECURITY.md).

## Threat model

- **The sample** runs in a guest. It may try to reach the host, other guests, the compose services or the LAN, and it may try to confuse
  everything that reads what it leaves behind (CAPE's report, event logs, memory images, screenshots, file and process names).
- **A web page the analyst has open** may try to talk to the local app (cross-site requests, WebSockets, DNS rebinding).
- **Not in scope:** an attacker who already has a shell on the host, a malicious analyst (there is one user and no login), a network attacker
  against `127.0.0.1` traffic, and sandbox evasion by the sample (guests carry some giveaways; the wizard lists them).

## Layers

| Layer | What it does | Where |
|---|---|---|
| Guest network | A Tartarus-owned nftables ruleset sits ahead of CAPE's rooter rules: a guest reaches only its gateway, internal and private networks are rejected on every route, a spoofed address is dropped at the bridge port, and guests cannot reach each other (the qemu hook isolates each port, and the bridge carries no frame between ports). The ruleset owns its default-deny: only a running guest's own address is forwarded, and only the ports that listen on the gateway are accepted. `GUEST_BLOCKED_ADDRESSES` adds addresses such as the host's public one. `make verify-isolation` proves each rule from inside two real guests | `cape/guest_engine/firewall.py`, `cape/guest_engine/port_isolation.py`, `cape/libvirt/qemu-hook`, `scripts/verify-isolation.sh` |
| Compose networks | The stack is split by need: OpenSearch is reachable only from the backend, the databases sit on internal networks, the control network is internal | `docker-compose.yml`, [architecture](architecture.md) |
| Browser origin | The backend and nginx answer 421 to a foreign `Host` and 403 to a foreign `Origin` on writes and WebSockets; every response carries `nosniff`, frame and referrer headers; nginx sends a CSP that allows no inline script and no inline `<style>` element or stylesheet (only `style` attributes, which Quasar sets), proven in a browser on every route and tab by `frontend/tests/e2e/csp.spec.ts` | `backend/app/browser_guard.py`, `frontend/nginx.conf` |
| Secrets | `make init-env` generates a mode-600 `.env` with random secrets; compose refuses to start without them; preflight rejects placeholders and short tokens; each cape program starts with only the secrets it reads | `scripts/gen-env.sh`, `cape/bin/keep-secrets` |
| Cape container | Not privileged: a fixed capability and device list, so no host device but `/dev/kvm` and the tun and vhost nodes exists in it, and no program in it holds `SYS_ADMIN`: the entrypoint drops it from the bounding set before it starts anything, so root there cannot mount, remount `/proc/sys` or make a device node. The `cape` user, which parses hostile output, may only read from libvirt (a polkit policy); a root broker reverts, stops and dumps a registered guest for it. Its programs' outgoing connections are default-deny per user: `cape` reaches the CAPE database only, and not Docker's resolver either (a query name can carry data out); the entrypoint resolves the database's name for it. The fake-host daemon (`lan-sim`, uid 10001), which shares that namespace and parses a guest's traffic, may start no connection at all, so loopback does not open CAPE's API, the control service or guacd to it; what it writes into the shared directory is read by root only as a regular file under a size cap, never through a link or a pipe. Image groups have reserved gids, `tcpdump` runs on a file capability instead of `sudo`, the CAPE tree is root-owned, and CAPE's web UI answers only `/apiv2` with `DEBUG` off | `docker-compose.yml`, `cape/libvirt/polkit/`, `cape/bin/machine-broker`, `cape/guest_engine/egress.py`, `cape/Dockerfile`, `make verify-cape-hardening` |
| Hostile data | Report, pcap and JSON input is size- and depth-bounded; live BSON values that are out of range are corrupt records, not crashes; uploads are refused by `Content-Length` before the body is read; report and export output is escaped; the frontend has no `v-html` sink | `backend/app/ingest/json_file.py`, `backend/app/live/`, `backend/app/api/upload_limit.py` |
| Supply chain | Base images are pinned by digest (a test fails on an unpinned one), CAPE, the guest tools and Volatility are pinned by hash or commit, Dependabot watches uv, npm, docker and actions | `backend/tests/test_image_pins.py`, `.github/dependabot.yml` |

## The v1 review

Five reviews ran before the release, each read-only: the backend, the control service and cape container, the compose stack, the frontend
and the dependencies. Their reports are kept in [the history](history/m11-notes/). Every finding was fixed or is listed below. The reviews were
checked against the running stack where they claimed an exploit; one claim was refuted (OpenSearch is not reachable from a guest) and one was
found to be worse than reported (guest-to-guest through the gateway worked in both directions).

After the release, the [2026-11-12 hardening review](security-audit-2026-11-12.md) looked at the cape container's privileges and packaging; its
seven findings and what was done about each are recorded there.

The security-critical code has had these automated reviews and real-stack proofs (`verify-isolation`, `verify-cape-hardening`, `e2e`), and no
audit by an outside party yet. The files to audit first are `cape/guest_engine/firewall.py`, `cape/bin/guest-firewall`,
`backend/app/browser_guard.py`, `cape/bin/keep-secrets`, `cape/bin/machine_broker_logic.py` and `cape/guest_engine/egress.py`.

## Accepted risks

| Risk | Why it stays | What would close it |
|---|---|---|
| **QEMU and libvirt are built from pinned source tarballs, so no distribution update reaches them.** A fix arrives only when the pin is bumped and the image rebuilt | QEMU carries the anti-VM patches, and QEMU 11 needs a newer libvirt than Ubuntu 24.04 ships | `make check-qemu-age` and its weekly workflow fail when either pin is over 180 days old or QEMU has a newer point release; bump as "Updating QEMU and libvirt" in the [CAPE integration spec](specs/cape-integration.md) describes |
| **Plain HTTP on `127.0.0.1`** | A local tool with one user; no port is published beyond loopback in production. A LAN install needs `TARTARUS_ALLOWED_HOSTS` and the nginx host map, and TLS in front | A TLS-terminating proxy, outside v1 |
| **No login** | One user on their own machine | Out of scope for v1 |
| **`diskcache` has an advisory with no upstream fix** | It is a transitive dependency of pySigma, caches ATT&CK data only, and hostile input cannot reach its pickle storage | An upstream release |
| **Advisories left in CAPE's Python packages** after the 2026-11-14 bump of `CAPE_REF` (18 entries in 4 packages, down from 389 in 38: pyasn1, msgpack, paramiko, capstone) | They are what CAPE's own lock pins at that commit; CAPE's web process answers only the backend, on an internal network | The next CAPE bump, with `make verify-guest`, `make verify-isolation` and `make e2e` |
| **The `internet` route reaches the internet** | It is the point of the route. Use a separate network or a VPN for live malware | The routes `none` and `inetsim` |
| **`GET /apiv2/` redirects** to the status endpoint | The API index page needs routes the API-only web config removed | Nothing to close |

## Hardening checklist for a LAN or shared install

1. Keep the default: production publishes the app only on `127.0.0.1`. Do not publish other ports.
2. If you must browse by name, set `TARTARUS_ALLOWED_HOSTS` and edit the host map in `frontend/nginx.conf`, and put TLS in front.
3. Keep `.env` at mode 600 (`make preflight` warns otherwise) and do not reuse its secrets.
4. Run analyses with the `inetsim` route unless you need the real internet.
5. After a kernel update on the host, reboot before starting guests: the `tun` module must match the running kernel.
