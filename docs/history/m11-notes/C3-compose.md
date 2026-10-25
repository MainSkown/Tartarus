# C3 - compose stack security review

**Status: done.** Read-only audit; no source edited, no container started or stopped. Evidence came from
reading the files, `docker compose config`, `docker inspect`/`docker network inspect`, and read-only
`docker exec` of `ss`/`iptables-save`/`id` in the running stack (prod compose, no analysis running).

- Done: areas 1 to 7, findings table.
- In progress: nothing.
- Next (for C6): fix findings test-first; record accepted risks (F3, F9, F12) in `docs/security.md`.
  Runtime check of F2 (guest to cape's own addresses during an analysis on every route) needs a
  guest and was not done.

Threat model used: single analyst on one host, UI on `127.0.0.1`; adversaries are (a) a malware sample
running in a guest, (b) a hostile web page open in the analyst's browser, (c) a compromised container
(parser bug in backend/cape, nginx) pivoting inside the compose networks, (d) a LAN neighbour.

## Area 1 - Published ports

Prod (`docker compose config`): only `frontend` publishes, `127.0.0.1:${TARTARUS_PORT:-8080}->80`
(docker-compose.yml:116). Dev override adds postgres `127.0.0.1:5432`, opensearch `127.0.0.1:9200`,
backend `127.0.0.1:8000`, frontend `127.0.0.1:5173` (docker-compose.dev.yml:3-26, `ports: !override` for
the frontend). `docker ps` of the running stack confirms: backend/postgres/opensearch/cape show only
EXPOSEd ports, nothing published. `smoke.sh static` asserts loopback-only, frontend-only (prod), no cape
ports, no host network, no docker.sock.

LAN neighbour: cannot reach backend, OpenSearch, Postgres, CAPE API, guacd or guest-control, nor the
guest desktop (VNC is `127.0.0.1` inside cape, qemu.conf:13; domain.xml.tpl:79). Nothing in compose lets
`TARTARUS_PORT` change the bind address; going off-loopback means editing the compose file. Checked,
nothing found for LAN exposure. Remaining exposure is local-browser, see F1.

Dev only (F10): OpenSearch (no auth) and Postgres (`change-me`) on loopback are reachable by every local
user and by DNS-rebinding web pages.

## Area 2 - Networks

- `tartarus-internal` (bridge, NOT `internal`): postgres, opensearch, backend, frontend, cape. Flat:
  every member reaches every port of every other member, and all have internet egress (F4).
- `tartarus-control` (`internal: true`): cape + backend only (verified with `docker network inspect`).
  guest-control listens on 172.18.0.3:8002 (control IP only), bearer token, constant-time compare,
  token >= 32 chars enforced by the service. Good.
- Guest bridge `tt-guest` lives in the cape container's own netns (no host network, no host bridge).
  `FORWARD` policy is DROP; libvirt's LIBVIRT_FWX/FWI/FWO reject anything but intra-bridge traffic
  (intra-bridge is blocked by the isolated port flag, proven by `verify-isolation.sh`). Routing:
  `route=inetsim`, `reject_segments` covers RFC1918/link-local/CGNAT so an `internet` route cannot
  reach the LAN or the docker bridges. Guest services on the gateway: ResultServer 2042 and INetSim,
  all bound to 192.168.150.1.
- Not checked/known gap: IPv6 (not in `reject_segments`; docker IPv6 is off by default, so info only).
- The guest can address the cape container's OTHER local addresses (F2). The `INPUT` chain is
  `ACCEPT` and only libvirt's DNS/DHCP rules are in it.

## Area 3 - Secrets

- `.env` is user-created from `.env.example`; gitignored (.gitignore:23-24); mode 644 on this host
  (F7). Nothing generates secrets: `.env.example:1` and docs/specs/backend.md:605 say they are
  "generated into data/secrets.env on first start", but no code does that and `data/secrets.env` does
  not exist (F6, doc bug). `CAPE_API_TOKEN`/`GUEST_CONTROL_TOKEN` are empty in the example and compose
  refuses to start without them (`${VAR:?}`), verified with `docker compose --env-file .env.example
  config`: it errors. Good.
- But defaults are accepted: `POSTGRES_PASSWORD=change-me` (.env.example:263), `CAPE_DB_PASSWORD=
  change-me-too` (:268). With the example plus `CAPE_API_TOKEN=a`, `GUEST_CONTROL_TOKEN=b`, `docker
  compose config` succeeds (F5). guest-control then refuses < 32 chars at runtime
  (cape/bin/guest-control:101-102), but CAPE_API_TOKEN has no length check anywhere. `make preflight`
  checks only the control token length (preflight.sh:135).
- Where they land: compose `environment:` (not Docker secrets/`_FILE`), so `docker inspect` shows
  POSTGRES_PASSWORD, CAPE_DB_PASSWORD, both tokens and the backend DATABASE_URL (anyone with docker
  access already is root; info). Not in images: Dockerfiles take no secrets (only the public CAPE_REF
  build arg); `.dockerignore`s keep `.env` out of every build context (backend/frontend contexts are
  subdirs, cape context is `*` minus cape/ guest/). Not in logs: `docker logs` of backend and cape
  grepped for token/password patterns: nothing. cape's supervisord children inherit every secret in
  their environment, including processes that parse malware output (F3).
- The cape HEALTHCHECK (cape/Dockerfile:185-187) expands `${CAPE_API_TOKEN}` at run time; visible only
  in the container's process list. Info.
- Postgres passwords are applied once, on an empty `pg-data` volume (init script); editing `.env`
  later does not rotate them. Info, document.
- `smoke.sh:29` hands the full `docker compose config --format json` (all resolved secrets) to
  python as an argv argument: readable via `/proc/<pid>/cmdline` by other local users (F8).

## Area 4 - Container hardening

| service | user | read_only | cap_drop | no-new-privileges | privileged/devices | mounts | healthcheck | limits |
|---|---|---|---|---|---|---|---|---|
| postgres | image default (postgres) | no | none | no | no | pg-data, init dir ro | yes | none |
| opensearch | 1000 | no | none | no | no (memlock ulimit) | os-data | yes | JVM heap only |
| backend | 1000 (tartarus) | no | none | no | no | cape-storage ro, rules ro, samples/exports/imports rw | yes | none |
| frontend | root master, nginx workers | no | none | no | no | none | yes | none |
| cape | root + cape users | no | none | label=disable (privileged) | PRIVILEGED, /dev/kvm | cape-storage, guest-images rw, imports ro, data/iso ro | yes | none |

No docker.sock mount anywhere, no `network_mode: host`, no host-path rw mounts (host paths are only
`./docker/postgres/init:ro`, `./rules/sigma:ro`, `./data/iso:ro`); enforced by smoke.sh. Shared volumes
are right: backend gets cape-storage read-only, sample-store is backend only. Gaps: F3, F9, F11.

## Area 5 - Images and downloads

Base images: `python:3.12-slim`, `node:24-alpine`, `nginx:alpine`, `postgres:16`, `ubuntu:24.04`,
`ghcr.io/astral-sh/uv:0.12`: floating tags, no digests. Only OpenSearch (3.9.0) and CAPE (full 40-char
SHA, enforced by cape/Dockerfile:4) are pinned. Verified downloads: guacamole-server tarball has a
sha256 check (cape/Dockerfile:39,47); Volatility3 wheels use `--require-hashes` (:79); npm uses `npm ci
--ignore-scripts` with lockfiles; uv uses `--frozen`. Unverified: `community.py -waf -cr` (:75) fetches
the CAPE community content (detection/processing code that CAPE executes) from GitHub's moving branch;
`cape2.sh suricata` and `suricata-update` (:127-128) pull a PPA and the ET ruleset; `kvm-qemu.sh`
(CAPE's own script, pinned only through CAPE_REF) downloads QEMU/SeaBIOS sources; `apt-get download
ovmf` (:109) is apt-signed but unpinned (F12). No `curl | sh` anywhere in the Dockerfiles or build
scripts (curl is used with `-o` then sha256sum -c). The `sed` patches to INetSim and the analyzer fail
the build if the anchor is missing. Checked, nothing found for curl|sh.

## Area 6 - nginx (frontend/nginx.conf)

- TLS: none, plain HTTP on `127.0.0.1` only. Acceptable for v1 if documented ("remote access: SSH
  tunnel, never re-publish the port"); the bind is hard-coded in compose.
- Headers: none of CSP, X-Content-Type-Options, X-Frame-Options/frame-ancestors, Referrer-Policy,
  Permissions-Policy (F13). `server_tokens` is on (`nginx/1.31.2` is reported).
- Host/Origin: `server_name _` accepts any Host; `/ws/` and `/api/` forward any Origin (F1).
- `/api/` proxied with `Host $host`, `X-Forwarded-For $proxy_add_x_forwarded_for` (appends to a
  client-supplied value; harmless unless the backend trusts it for decisions, which it does not appear
  to). WebSocket upgrade map correct, `proxy_read_timeout` 3600s on `/ws/`.
- Limits: 512 MB on `/api/`, 5 GB on `/api/analyses/import/memory-image` (exact-match location, so the
  tighter limit cannot be bypassed by path variants like `//` because nginx normalises first), request
  buffering off so the backend must enforce its own limits: it does (imports/upload.py:136). No
  `client_header_buffer_size`/`client_body_timeout`/rate limits: fine for a loopback single-user tool.
- Cache locations: `add_header` inside `location` blocks resets inherited server-level headers, so
  when F13's headers are added they must go in an `include` repeated per location (or use
  `add_header ... always` in each).

## Area 7 - OpenSearch / Postgres

- OpenSearch: `DISABLE_SECURITY_PLUGIN=true` (docker-compose.yml:35); no auth, no TLS; reachable by
  every container on `tartarus-internal`, including cape (privileged, malware-adjacent) and frontend.
  Not published in prod. Runs as uid 1000. (F4.)
- Postgres: `pg_hba` is `trust` for local socket/127.0.0.1 only and `scram-sha-256` for all other
  hosts; password auth is enforced from other containers. One server holds both the Tartarus and the
  CAPE databases under separate roles (cape role cannot read the Tartarus DB by default). Not
  published in prod. Password quality is the weak point (F5).

## Findings

### F1 - high - No Host/Origin validation: a web page in the analyst's browser can drive the API and the live/desktop WebSockets
frontend/nginx.conf:12 (`server_name _`), :22-63; backend has no auth, no CORS and no origin check
(backend/app/ws/live.py:81, ws/system.py:87, ws/desktop.py:130 call `accept()` without looking at
`Origin`). Loopback publishing does not stop the browser: any site the analyst opens (this user
browses malware infrastructure) can (a) send CSRF multipart POSTs to `http://127.0.0.1:8080/api/...`
(submit/ import jobs), (b) open `ws://127.0.0.1:8080/ws/...` cross-site (CSWSH) and read live events or
attach to a guest desktop, (c) with DNS rebinding, read everything incl. sample downloads and reports
because the rebound Host is accepted.
Fix (smallest): in nginx, return 421 unless `$host` is `127.0.0.1`/`localhost`, and for `/ws/` and
non-GET `/api/` return 403 unless `$http_origin` is empty or equals `http://$host`. Add a backend test
or a smoke assertion for it.

### F2 - high (needs runtime confirmation) - tt-guest has no INPUT drop: a guest can reach the cape container's other addresses (unauthenticated guacd)
cape/supervisord.conf:144 (guacd on the internal IP:4822, no auth), :213 (CAPE API on internal IP:8000),
:155 and entrypoint (guest-control on the control IP:8002); live `iptables-save` of the cape container:
`:INPUT ACCEPT` with only libvirt's 53/67 rules, and `ss -ltn` confirms the listeners on 172.19.0.6 /
172.18.0.3. A packet from a guest to 172.19.0.6:4822 is locally delivered; `FORWARD DROP` and
`reject_segments` do not apply to it. Whether it is rescued depends on rooter's PREROUTING DNATs
(inetsim route redirects guest traffic; routes none/drop/internet may not). If reachable, guacd lets
the guest ask for a VNC connection to `127.0.0.1:59xx` = the consoles of other guests (no VNC
password), breaking the guest-to-guest isolation that verify-isolation.sh proves only for guest IPs,
and the API/control ports are exposed to attacker traffic (token-protected).
Fix: in the entrypoint (after the bridge exists) add `iptables -A INPUT -i tt-guest ! -d
$GUEST_GATEWAY_IP -j DROP` (DHCP/DNS rules from LIBVIRT_INP come earlier in the chain), and extend
verify-isolation.sh with probes from a guest to the cape container's eth0/eth1 addresses on
4822, 8000 and 8002 under each route. Also see F3.

### F3 - medium - cape is privileged, and its unprivileged `cape` user is root-equivalent
docker-compose.yml:141 (`privileged: true`, label=disable), cape/Dockerfile:123 (`cape ALL=NOPASSWD:
/usr/bin/tcpdump`: `sudo tcpdump -z <script>` runs arbitrary commands as root), guest-control runs as
root, every supervised process inherits all four secrets (supervisord env). The `cape` user runs
processing/reporting code over data produced by malware; a parser bug there is root in a privileged
container, i.e. host root (mount host block devices, cgroup escape). Same for a QEMU escape from a
guest. The design decision is documented (cape-integration.md) and `verify-cape.sh` guards libvirt's
TCP port; the sudo rule is the avoidable part.
Fix: record as accepted risk in docs/security.md; replace the sudo rule with `setcap
cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump` (upstream's own alternative) and start cape/processor
children with only the env they need (`environment=` per program, no GUEST_CONTROL_TOKEN or DB password
for cape-web/cape-processor where unneeded). Post-v1: replace `privileged` by `cap_add` +
explicit `devices` (`/dev/kvm`, `/dev/net/tun`, loop devices).

### F4 - medium - Flat, non-internal data network: cape and frontend can reach unauthenticated OpenSearch, and everything has internet egress
docker-compose.yml:176-179, :35, services listing `networks:`. frontend (nginx, the only service
a browser talks to) and cape (privileged, parses malware output) share a network with OpenSearch
(security plugin off), Postgres and guacd. A compromised frontend/cape can read, rewrite or delete every
event index and all reports; postgres/opensearch/backend can also exfiltrate (egress is open).
Fix: three networks: `tartarus-web` (frontend, backend), `tartarus-data` with `internal: true`
(backend, postgres, opensearch) and the existing `tartarus-control` (backend, cape; move cape's CAPE-DB
access to a `tartarus-cape-db` internal network with postgres + cape only). Cape keeps the egress
network the rooter needs (`internet = ${CAPE_INTERNAL_IFACE}`).

### F5 - medium - Default/weak credentials accepted; no validation beyond non-empty
.env.example:263,268 (`change-me`, `change-me-too`), docker-compose.yml:9,12,70,74. Compose only
rejects empty values; the example passwords are accepted silently (verified), `CAPE_API_TOKEN` has no
length check (`a` is accepted), `preflight.sh` checks only the control token. The databases are not
published in prod, but in dev (`127.0.0.1:5432`) and for any pivot inside the stack the password is the
only barrier.
Fix: make `.env.example` leave all four secrets empty (compose already refuses empties), or ship
`make init-env` that writes `openssl rand -hex 32` values at mode 600; extend `preflight.sh` to fail
on `change-me*` or < 32 chars for CAPE_API_TOKEN and both DB passwords (the URL-safe hex alphabet fits
the stated "letters, digits" constraint).

### F6 - low - Documentation promises `data/secrets.env`, which nothing creates
.env.example:1, docs/specs/backend.md:605. Misleading: users may expect auto-generated secrets and keep
the placeholders. Fix: delete the sentence, or implement F5's generator and keep the sentence true.

### F7 - low - `.env` holds all secrets and is world-readable (mode 644)
Observed on this host (`-rw-r--r--`); any local user reads the DB passwords and both tokens. Fix: the
F5 generator does `umask 077`; `preflight.sh` warns if `.env` mode is looser than 600.

### F8 - low - smoke.sh puts the resolved compose config (with secrets) on a command line
scripts/smoke.sh:29 (`python3 -I - "$1" "$2"`; $2 is `docker compose config --format json`). Other
local users see it in `ps`/`/proc/<pid>/cmdline` while the script runs. Fix: pass the JSON on stdin or
via an environment variable and keep the program in `-c`/a file; or run `config` with
`--no-interpolate`-free redaction of `environment`.

### F9 - low - No cap_drop / no-new-privileges / read_only / limits on any service; nginx master is root
docker-compose.yml (all services), frontend/Dockerfile:67. Fix: for postgres, opensearch, backend,
frontend add `security_opt: ["no-new-privileges:true"]` and `cap_drop: [ALL]` (postgres needs
CHOWN/SETUID/SETGID/DAC_OVERRIDE/FOWNER at init; nginx needs CHOWN/SETUID/SETGID/NET_BIND_SERVICE, or
switch to `nginxinc/nginx-unprivileged` on 8080), `read_only: true` + `tmpfs` for backend/frontend.
For cape add `mem_limit`/`cpus`/`pids_limit`: libvirt's cgroup controllers are off (qemu.conf:10), so
a runaway guest or build is bounded only by the host; an unbounded cape can starve OpenSearch and the
host.

### F10 - low (dev only) - Dev compose publishes unauthenticated OpenSearch and a `change-me` Postgres on loopback; Vite dev server accepts any Host
docker-compose.dev.yml:3-9, frontend/quasar.config.ts:41 (`host: '0.0.0.0'`, no `allowedHosts`).
DNS rebinding from a web page can reach OpenSearch (`http://127.0.0.1:9200`, no auth) and the dev
server. Fix: document that dev must not run on a machine used to browse hostile sites, or publish
OpenSearch/Postgres only when `--profile dev-tools` is given.

### F11 - low - cape's `siteauth.sqlite` and process environment: token hash file is 0644
`/opt/CAPEv2/web/siteauth.sqlite` is world-readable inside cape (stores the hash of CAPE_API_TOKEN,
not the token). Low impact; mention only for completeness. Fix: `chmod 600` in the api-token program.

### F12 - low - Floating base images and unverified build-time downloads
cape/Dockerfile:2,13,37,60,85 (`ubuntu:24.04`), :65, backend/Dockerfile:1,3, frontend/Dockerfile:1,
:44 (`nginx:alpine`), docker-compose.yml:4 (`postgres:16`); cape/Dockerfile:75 (community content from a
moving branch), :127-128 (PPA + ET rules), :109. A rebuild can change behaviour or pull a compromised
upstream, and the community content is code CAPE executes in the privileged container.
Fix: pin base images by digest (`image:tag@sha256:...`, updated by Renovate/Dependabot); pin
community.py to a commit/tarball with a sha256, or record the risk. Release build should be
reproducible from the lock files.

### F13 - low - nginx sends no security headers and advertises its version
frontend/nginx.conf (server block). Fix: `server_tokens off;` plus `add_header` (with `always`) for
`X-Content-Type-Options nosniff`, `Referrer-Policy no-referrer`, `X-Frame-Options DENY` (or CSP
`frame-ancestors 'none'`), and a CSP such as `default-src 'self'; connect-src 'self' ws: wss:;
img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'` (the Quasar PWA and the report iframes, if
any, need testing). Remember nginx drops inherited `add_header` in any location that sets its own
(the `Cache-Control` locations), so repeat via an `include`.

### F14 - info - Items checked, nothing found
- Published ports: only the frontend, on 127.0.0.1; enforced by smoke.sh (also in CI static mode).
- No docker.sock, no host network, no rw host-path mounts; ISOs read-only; cape-storage read-only in
  backend.
- guest-control on an `internal: true` network with constant-time bearer check and a minimum length.
- libvirt TCP endpoint is off; unix socket restricted to group libvirt.
- Dockerfiles: no secrets as ARG/ENV/COPY, backend runs as uid 1000, no curl|sh, hash-checked
  guacamole and Volatility wheels, `npm ci --ignore-scripts`.
- Healthchecks defined for every service. Logs contain no tokens or passwords.
- Postgres `pg_hba`: scram-sha-256 for non-local clients; trust only on loopback/socket.
- preflight.sh parses `.env` with `sed`, never `source`s it (no code execution from `.env`).

## Severity-sorted table

| id | sev | where | one line | fix |
|---|---|---|---|---|
| F1 | high | frontend/nginx.conf:12,22-63 | no Host/Origin check: CSRF, CSWSH, DNS rebinding from the analyst's browser | 421 on foreign Host, 403 on foreign Origin for /ws and unsafe /api |
| F2 | high* | cape/supervisord.conf:144,213; cape INPUT ACCEPT | guest can reach guacd/API/control on cape's own IPs unless rooter DNAT catches it (*confirm per route) | `iptables -A INPUT -i tt-guest ! -d $GATEWAY -j DROP` + verify-isolation probes |
| F3 | medium | docker-compose.yml:141, cape/Dockerfile:123 | privileged cape; `cape` user to root via `sudo tcpdump`; all secrets in every child env | setcap tcpdump, per-program env, accept in docs/security.md |
| F4 | medium | docker-compose.yml:176-179 | flat non-internal network; frontend/cape reach unauthenticated OpenSearch; open egress | split web/data(internal)/control/cape-db networks |
| F5 | medium | .env.example:263,268; compose:9,12,70 | `change-me` and 1-char tokens accepted | empty examples, generator, preflight checks |
| F6 | low | .env.example:1; backend.md:605 | data/secrets.env promised, not implemented | fix doc or implement |
| F7 | low | .env (644) | secrets world-readable | umask 077 / preflight warning |
| F8 | low | scripts/smoke.sh:29 | resolved config with secrets in argv | pass on stdin |
| F9 | low | docker-compose.yml, frontend/Dockerfile:67 | no cap_drop/no-new-privileges/read_only/limits; nginx master root | add per-service hardening, cape mem/pids limits |
| F10 | low | docker-compose.dev.yml:3-9, quasar.config.ts:41 | dev publishes OpenSearch/Postgres; Vite any Host | profile or doc |
| F11 | low | cape siteauth.sqlite | token-hash file 0644 | chmod 600 |
| F12 | low | all Dockerfiles, cape/Dockerfile:75,127-128 | floating tags, unpinned community/PPA/ET downloads | digests, pin community |
| F13 | low | frontend/nginx.conf | no security headers, server_tokens on | headers + `server_tokens off` |
| F14 | info | various | checked, nothing found (list above) | - |
