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
| Guest network | A Tartarus-owned nftables ruleset sits ahead of CAPE's rooter rules: a guest reaches only its gateway, internal and private networks are rejected on every route, a spoofed address is dropped at the bridge port, and guests cannot reach each other. `make verify-isolation` proves each rule from inside two real guests | `cape/guest_engine/firewall.py`, `cape/libvirt/qemu-hook`, `scripts/verify-isolation.sh` |
| Compose networks | The stack is split by need: OpenSearch is reachable only from the backend, the databases sit on internal networks, the control network is internal | `docker-compose.yml`, [architecture](architecture.md) |
| Browser origin | The backend and nginx answer 421 to a foreign `Host` and 403 to a foreign `Origin` on writes and WebSockets; every response carries `nosniff`, frame and referrer headers; nginx sends a CSP | `backend/app/browser_guard.py`, `frontend/nginx.conf` |
| Secrets | `make init-env` generates a mode-600 `.env` with random secrets; compose refuses to start without them; preflight rejects placeholders and short tokens; each cape program starts with only the secrets it reads | `scripts/gen-env.sh`, `cape/bin/keep-secrets` |
| Cape container | The `cape` user is out of the host's disk group, `tcpdump` runs on a file capability instead of `sudo`, the CAPE tree is root-owned, and CAPE's web UI answers only `/apiv2` with `DEBUG` off | `cape/Dockerfile`, `cape/web/`, `make verify-cape-hardening` |
| Hostile data | Report, pcap and JSON input is size- and depth-bounded; live BSON values that are out of range are corrupt records, not crashes; uploads are refused by `Content-Length` before the body is read; report and export output is escaped; the frontend has no `v-html` sink | `backend/app/ingest/json_file.py`, `backend/app/live/`, `backend/app/api/upload_limit.py` |
| Supply chain | Base images are pinned by digest (a test fails on an unpinned one), CAPE, the guest tools and Volatility are pinned by hash or commit, Dependabot watches uv, npm, docker and actions | `backend/tests/test_image_pins.py`, `.github/dependabot.yml` |

## The v1 review

Five reviews ran before the release, each read-only: the backend, the control service and cape container, the compose stack, the frontend
and the dependencies. Their reports are kept in [the history](history/m11-notes/). Every finding was fixed or is listed below. The reviews were
checked against the running stack where they claimed an exploit; one claim was refuted (OpenSearch is not reachable from a guest) and one was
found to be worse than reported (guest-to-guest through the gateway worked in both directions).

The security-critical code has had these automated reviews and real-stack proofs (`verify-isolation`, `verify-cape-hardening`, `e2e`), and no
independent audit yet. The files to audit first are `cape/guest_engine/firewall.py`, `cape/bin/guest-firewall`,
`backend/app/browser_guard.py` and `cape/bin/keep-secrets`.

## Accepted risks

| Risk | Why it stays | What would close it |
|---|---|---|
| **The cape container is `privileged: true`.** A root compromise inside it (guest-control, libvirtd, a QEMU escape that escalates) has the host's devices and capabilities | Without it libvirt cannot set the bridge port flag `isolated`: Docker mounts sysfs read-only. A minimal capability and device set was tried twice and reverted | Drop `<port isolated>` from every domain XML and set it in the qemu hook with `bridge link set dev <tap> isolated on`; then drop `privileged` (v1.1) |
| **`GET /api/guests` returns the guest account password**, shown with reveal and copy on the guest card | It is a throwaway account on an isolated machine, and the browser-origin checks close the cross-site reader | A reveal endpoint and a change to the guest card (follow-up L3) |
| **The CSP keeps `style-src 'unsafe-inline'`** | Quasar uses inline style attributes | Try `style-src 'self'` with `style-src-attr 'unsafe-inline'` in a real browser (follow-up L4) |
| **Plain HTTP on `127.0.0.1`** | A local tool with one user; no port is published beyond loopback in production. A LAN install needs `TARTARUS_ALLOWED_HOSTS` and the nginx host map, and TLS in front | A TLS-terminating proxy, outside v1 |
| **No login** | One user on their own machine | Out of scope for v1 |
| **`diskcache` has an advisory with no upstream fix** | It is a transitive dependency of pySigma, caches ATT&CK data only, and hostile input cannot reach its pickle storage | An upstream release |
| **CAPE and Django advisories at the pinned CAPE commit** | A bump of `CAPE_REF` risks the analyzer patches and needs a proof on real guests | The next CAPE bump, with `make verify-guest` and `make e2e` |
| **The `internet` route reaches the internet** | It is the point of the route. Use a separate network or a VPN for live malware | The routes `none` and `inetsim` |
| **Two Windows 10 limits:** `make e2e` fails two checks on a Windows 10 guest (a process-panel and a Sigma source check, test-side), and the self-test failed once on an open `WinStore.App` window after `quiet-desktop` | Test and flake issues, not exposure | Guest-aware e2e checks and a settle-and-recheck (follow-ups L1 and L2) |
| **`GET /apiv2/` redirects** to the status endpoint | The API index page needs routes the API-only web config removed | Nothing to close |

## Hardening checklist for a LAN or shared install

1. Keep the default: production publishes the app only on `127.0.0.1`. Do not publish other ports.
2. If you must browse by name, set `TARTARUS_ALLOWED_HOSTS` and edit the host map in `frontend/nginx.conf`, and put TLS in front.
3. Keep `.env` at mode 600 (`make preflight` warns otherwise) and do not reuse its secrets.
4. Run analyses with the `inetsim` route unless you need the real internet.
5. After a kernel update on the host, reboot before starting guests: the `tun` module must match the running kernel.
