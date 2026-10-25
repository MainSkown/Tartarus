# C2: security review of the cape container and its control services

Status: DONE (all six areas reviewed). Read-only on source; nothing under `cape/`, `docker/`, `scripts/`
or `guest/` was edited.

| Area | State |
|---|---|
| 1. Guest-control HTTP service | done |
| 2. What the guest can do to the host | done |
| 3. Network isolation | done (two behaviours reproduced in throwaway network namespaces, see F2 and F5) |
| 4. Container privileges | done (live container inspected) |
| 5. CAPE API token / backend to cape | done |
| 6. Shell scripts under `scripts/` and `guest/` | done |

How this was verified. Source read in full for `cape/bin/*`, `cape/guest_engine/*`, `cape/auxiliary/event_logs.py`,
`cape/{Dockerfile,entrypoint.sh,supervisord.conf,conf,templates,libvirt}`, `guest/steps/*`, the Windows profile
steps, `scripts/*.sh`, `docker-compose.yml`. The running `tartarus-cape` container (up, healthy) was inspected with
read-only commands (`iptables -S`, `ss -ltnup`, `ps`, `ls -l`, `/proc/<pid>/environ` variable names only, GETs against
CAPE's web port). Two throwaway containers from the `tartarus-cape` image with `--network none` (removed on exit)
reproduced the bridge-isolation and FORWARD-chain-order behaviours; the scripts are in the session scratchpad, not in
the repo. Side effect on the live stack: one `GET /analysis/remove/999999999/` against CAPE's web port (id does not
exist; CAPE's web delete is disabled by default, `[delete] enabled = no`). One attempt to read a process list for
the healthcheck token was refused by the permission classifier and was not retried; F13 is therefore code-read only.

Labels used below: **verified** = observed on the live container or reproduced; **code-read** = follows from the code,
not exercised; **reasoned** = verified pieces combined, not run end to end with a live Windows guest.

---

## Findings

### F1. HIGH. The cape container is `privileged: true`, and the unprivileged `cape` user can write the host's raw disks

- Where: `docker-compose.yml:141` (`privileged: true`); `cape/Dockerfile:119-122` (`usermod -aG libvirt,kvm cape`);
  the `suricata` group created by `cape2.sh suricata` (Dockerfile:127).
- Verified live: `CapEff 000001ffffffffff`, `Seccomp: 0`, SecurityOpt `label=disable`; every host device node is in
  `/dev`, including `/dev/nvme0n1p2` and `/dev/sda`. On this host those nodes are `root:disk` with gid 993, and inside
  the container gid 993 is the `suricata` group with `cape` as a member:
  `runuser -u cape -- test -w /dev/nvme0n1p2` succeeds (also readable). `cape` also has groups `libvirt` (full libvirt
  control, `auth_unix_rw = "none"`) and `kvm`.
- Exploit scenario: the `cape` user runs everything that parses hostile data: the scheduler, `utils/process.py` over
  the sample, dropped files and guest results, `gunicorn`, `guacd`, and Volatility3 over a hostile memory image
  (`memory_logic.py` runs `vol` as `cape`). Any code execution in one of those parsers (or a QEMU escape that lands in
  the container) reads and writes the host's block devices directly (`dd`, `debugfs`) and owns the host. Even without
  the gid collision, root in the container can `mount /dev/nvme0n1p2`. `docs/specs/cape-integration.md:106` already
  flags "privileged is probably broader than needed"; the raw-disk access for `cape` is new.
- Smallest fix: replace `privileged: true` with `cap_add: [NET_ADMIN, NET_RAW, SYS_ADMIN, SYS_RESOURCE, IPC_LOCK, MKNOD]`,
  `devices: [/dev/kvm, /dev/net/tun, /dev/vhost-net, /dev/loop-control]`, `device_cgroup_rules: ['b 7:* rmw']`
  (loop devices for the ISO scan), and drop `security_opt: label=disable` if the host has no LSM trouble. Test with
  `make verify-cape` and a build. This removes the host disks, `SYS_MODULE`, `SYS_RAWIO`, `SYS_PTRACE` and the other
  host devices. Independently, delete `cape` from the `suricata` group (`gpasswd -d cape suricata`; check what
  Suricata's unix socket needs) so a gid collision cannot grant disk access if the container stays privileged.

### F2. HIGH. `reject_segments` never applies, so a guest on the `internet` route reaches Docker networks and the LAN

- Where: `cape/conf/routing.conf:9`; CAPE's `utils/rooter.py` `cleanup_rooter()` (inserts
  `FORWARD -j CAPE_REJECTED_SEGMENTS` and then `-I FORWARD -j CAPE_ACCEPTED_SEGMENTS`, so ACCEPTED is evaluated first);
  `lib/cuckoo/core/analysis_manager.py:740-760` (`forward_enable` has no destination, then `forward_reject_enable`).
- Verified: live `iptables -S FORWARD` shows `-A FORWARD -j CAPE_ACCEPTED_SEGMENTS` before `-j CAPE_REJECTED_SEGMENTS`.
  Reproduced in a throwaway namespace set-up with exactly the rooter's rules (accept `-i br -o eth1 --source G`,
  reject the same source to `10/8,172.16/12,192.168/16,169.254/16,100.64/10`): a UDP datagram from the "guest" to
  172.19.0.5 was delivered. After swapping the two FORWARD jumps it was not.
- Exploit scenario: an analyst picks `INTERNET` (the GUI warns only about the internet). The sample connects to
  `172.19.0.x`: OpenSearch (security plugin disabled, `DISABLE_SECURITY_PLUGIN: "true"`), Postgres, the backend API,
  the CAPE web UI on its Docker IP, the Docker host at `172.19.0.1`, and through the host's NAT every RFC1918 address
  on the host's LAN. The spec (`cape-integration.md:41`) says the internet route is "configured but unexercised"; the
  reject list is advertised as a guard and is dead configuration.
- Smallest fix: after the rooter has initialised (it re-creates the chains on every start), move the reject jump to
  the top: `iptables -D FORWARD -j CAPE_REJECTED_SEGMENTS; iptables -I FORWARD -j CAPE_REJECTED_SEGMENTS`, e.g. as a
  step in `start-guest-network`/a supervisord program that waits for the rooter (`wait-then-exec rooter`). Add a check
  to `verify-isolation.sh`: with route `internet`, a probe from the guest to a Docker-network address must fail. Until
  fixed, consider hiding the INTERNET option or documenting that it exposes the Docker host's networks.

### F3. HIGH (reasoned). Nothing restricts what a guest can reach on the container itself, and every per-guest rule is keyed on the guest's source IP

- Where: no INPUT policy in `cape/` (live `iptables -S`: `-P INPUT ACCEPT`, only `LIBVIRT_INP` accepts for
  53/67 and a RELATED,ESTABLISHED rule); `start-guest-network`; `cape/templates/tt-guest.xml` (no `<filterref>`);
  `guest/domain/domain.xml.tpl:69-74` (no anti-spoofing filter). The rooter's routes
  (`inetsim_enable`, `drop_enable`, `forward_enable`) all match `--source <guest ip>` or `--destination <guest ip>`.
- Verified pieces: (a) listeners reachable on the container's own addresses: CAPE web+API `172.19.0.6:8000`, guacd
  `172.19.0.6:4822`, guest-control `172.18.0.3:8002` (`ss -ltnp`); (b) INPUT accepts everything arriving on `tt-guest`;
  (c) the DNAT that sends a guest's traffic to INetSim only matches the guest's own address (`rooter.py:889-1060`),
  and the OUTPUT drop for route `drop`/`none` is `--destination <guest ip>`; (d) the CAPE web UI answers anonymously
  (F4). Nothing binds a guest to its address: the NIC has no `ip-spoofing` filter and the bridge learns any source.
- Exploit scenario: malware running as SYSTEM in an `inetsim` (or `drop`/`none`) analysis adds an unused address of
  the /24, e.g. 192.168.150.200, and connects from it to `172.19.0.6:8000`. The DNAT/drop rules do not match, INPUT
  accepts, the reply goes straight back over the bridge. It can then: use CAPE's anonymous web UI (F4) to submit a
  sample with `route=internet` (a fresh guest with real internet, defeating the INetSim guarantee); ask guacd (F5) to
  open the VNC console of any other running guest; probe the token-protected CAPE API and guest-control. During guest
  builds, the self-test and the seconds between snapshot revert and `route_network()` no rule exists at all, so no
  spoofing is needed. Not exercised end to end with a live guest.
- Smallest fix: (1) default-deny for the guest bridge on the container: `iptables -I INPUT 1 -i tt-guest ! -d $GUEST_GATEWAY_IP -j DROP`
  plus ACCEPT rules only for the gateway's 53, 67/68, 2042 and the INetSim ports (ARP is not affected); put it in
  `start-guest-network` so it survives the rooter's `cleanup_rooter` (which only removes rules tagged `CAPE-rooter`).
  (2) bind the NIC to its address: add `<filterref filter='clean-traffic'>` with `IP`/`MAC` parameters to
  `domain.xml.tpl`, or ebtables/nft `ip saddr` + `ether saddr` rules per registered guest. (3) Add both to
  `verify-isolation.sh` (a guest must fail to connect to the container's eth0/eth1 addresses).

### F4. MEDIUM. CAPE's whole Django web UI is served unauthenticated on `tartarus-internal`, with `DEBUG = True`

- Where: `cape/supervisord.conf:213` (`gunicorn web.wsgi:application ... --bind %(ENV_CAPE_INTERNAL_IP)s:8000`),
  with the comment on line 211 "apiv2 only"; `cape/conf/web.conf` (no auth; CAPE default `[web_auth] enabled = no`);
  `/opt/CAPEv2/web/web/settings.py:107` (`DEBUG = True`), `ALLOWED_HOSTS = ["*"]`.
- Verified live (GETs only, no token): `/` , `/submit/`, `/analysis/` (lists recent tasks with filenames and hashes),
  `/analysis/search/`, `/accounts/signup/`, `/apiv2/` answer 200; unknown URLs render Django's DEBUG 404 page that lists
  the URLconf; `/apiv2/*` data endpoints answer 401 as intended; `/analysis/remove/<id>/` is reachable (CAPE ships web
  delete off). The routes `/submit/` (POST creates tasks, route and machine selectable), `/analysis/reprocess/<id>/`,
  `/file/...` (sample, dropped files, memory) and `/full_memory/<id>/` are served by the same process.
- Exploit scenario: any container on `tartarus-internal` (OpenSearch has no authentication, Postgres, frontend) or the
  guest in F3 can submit analyses with any route, download samples and memory dumps, and read the analysis history,
  bypassing the backend's access model. DEBUG pages show URLconf and, on a 500, settings and traceback locals.
- Smallest fix: add `cape/conf/web/local_settings.py` (CAPE imports `web/web/local_settings.py`; ship it with the
  Dockerfile) with `DEBUG = False`, `ALLOWED_HOSTS = ["cape", "cape-internal", "127.0.0.1"]` and
  `ROOT_URLCONF = "tartarus_urls"` whose urlpatterns contain only `apiv2/`; or put a 15-line WSGI wrapper in front that
  404s every path not starting with `/apiv2/`. Add a `verify-cape.sh` check: `GET /submit/` from another container
  must not be 200.

### F5. MEDIUM (code-read). guacd listens unauthenticated on the shared internal network

- Where: `cape/supervisord.conf:144` (`guacd -f -b $CAPE_INTERNAL_IP -l 4822`, user `cape`);
  `docker-compose.yml:170-173`; `backend/app/config.py:28-29` (`guacd_host = "cape"`).
- Exploit scenario: guacd takes the VNC target from the client's `connect` instruction (`hostname`, `port`), and the
  VNC servers of all guests listen without a password on `127.0.0.1:59xx` inside the container (`libvirt/qemu.conf`
  `vnc_listen`, `domain.xml.tpl:79`). Any client that reaches 4822 (every container on `tartarus-internal`, or a guest
  via F3) gets keyboard/mouse and screen of any running guest (including one under analysis) and can use guacd as a
  TCP connect probe. The backend pins the target (`desktop/tunnel.py`), but guacd itself cannot. Not exercised.
- Smallest fix: move guacd to the control network (`-b $CAPE_CONTROL_IP`, backend `GUACD_HOST=cape-control`), which
  only cape and backend share; F3 (1) then also removes the guest path. Optionally give each guest's VNC a random
  password that only the control service knows.

### F6. MEDIUM. Every secret is in the environment of every supervised program, including network-facing ones

- Where: `cape/entrypoint.sh`, `cape/supervisord.conf` (no `environment=` filtering; supervisord children inherit
  the container environment), `docker-compose.yml:128-137`.
- Verified live (variable names only): `/proc/<pid>/environ` of `guacd` (user `cape`, network facing) and of `libvirtd`
  holds `CAPE_API_TOKEN`, `GUEST_CONTROL_TOKEN`, `CAPE_DB_PASSWORD`. (INetSim's service children and dnsmasq do not
  carry them.) `GUEST_CONTROL_TOKEN` is not needed by any CAPE process.
- Exploit scenario: a bug in guacd, gunicorn, the CAPE scheduler/processor or Volatility hands the attacker the
  control-service token (create/delete guests, run the root service's memory and symbol routes), the CAPE API token
  and the CAPE database password in one read of `/proc/self/environ`.
- Smallest fix: start each program with only what it needs, e.g. `command=env -u GUEST_CONTROL_TOKEN -u CAPE_API_TOKEN -u CAPE_DB_PASSWORD /usr/local/sbin/guacd ...`
  and `env -u GUEST_CONTROL_TOKEN` for all CAPE programs (the web/processor still need `CAPE_DB_*`; only
  `api-token` needs `CAPE_API_TOKEN`).

### F7. MEDIUM. `cape` may run `tcpdump` as root through sudo with arbitrary arguments

- Where: `cape/Dockerfile:123-124` (`cape ALL=NOPASSWD: /usr/bin/tcpdump`); verified present in the live container.
- Exploit scenario: `sudo tcpdump -i lo -G 1 -W 1 -w /tmp/x -z /path/to/script` runs `script` as root (tcpdump's
  post-rotate command), so any code execution as `cape` (F1 lists the parsers) is root in the container with a
  one-liner. The alternative routes (F8, F1) exist, which is why this is not higher.
- Smallest fix: drop the sudoers file and give the binary file capabilities: `setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump`
  with `chgrp cape` and mode `0750` (CAPE's `[sniffer] tcpdump = /usr/bin/tcpdump` and `sudo` use: set `[sniffer] tcpdump`
  to the binary and check CAPE's `Sniffer` call path), or pin the argument list in sudoers.

### F8. MEDIUM. `cape/auxiliary/event_logs.py` trusts a hostile guest's answers without limits and follows redirects

- Where: `cape/auxiliary/event_logs.py:135-144` (`requests.get/post` with `timeout=(5, read_timeout)`, default redirects
  on, no size cap), `:114` (`answer.json()["stdout"]`), `:417-424` (`target.write_bytes(document)`), `:231-236`.
- Code-read: during `stop()` the "agent" is whatever the sample left listening on guest port 8000 (malware can kill
  the real agent and bind it). It can (a) answer with a multi-GB JSON body: `requests` buffers it all in the CAPE
  scheduler's memory (OOM of the whole container, no memory limit in compose) or, if base64, write it into the analysis
  folder uncapped (disk fill on the shared `cape-storage` volume); (b) drip bytes so the per-read timeout never fires
  and the `STOP_BUDGET_S` budget (only used to size each timeout) never stops the call, holding the machine slot
  forever; (c) answer `POST /execute` with `307 Location: http://backend:8000/...` or `http://opensearch:9200/<index>/_close`:
  `requests` follows it with the method and body, so the CAPE host replays an attacker-chosen POST to any internal
  service. `expat` is only used for well-formedness, started at `<Events`, so a DTD cannot precede the root: good.
- Smallest fix: `allow_redirects=False`, `stream=True` with a hard cap (e.g. 256 MB) and a total deadline per call;
  refuse to write a document larger than the cap; test with a fake agent returning a redirect, a huge body, and a slow body.

### F9. LOW. Guest-to-guest traffic is reachable through the host's L3 forwarding (one-way)

- Where: `cape/guest_engine/isolation.py` (relies on `<port isolated='yes'/>` only); live `iptables -S`:
  `-A LIBVIRT_FWX -i tt-guest -o tt-guest -j ACCEPT`, `net.ipv4.ip_forward=1`.
- Reproduced in a throwaway namespace set-up (isolated veth ports on a bridge, same FORWARD rules): A cannot reach B
  directly (port isolation holds), but after `ip neigh replace B_IP lladdr <gateway MAC>` on A, A's datagram to B is
  delivered via the host's forwarding. With a rooter-style `DNAT --source A` for UDP the datagram was not delivered.
  `verify-isolation.sh` only tries the direct path.
- Impact is limited: B's replies go straight to A at L2 and are dropped by the isolation, so only one-way/blind traffic
  (single UDP datagrams, crafted packets) works; and the rooter's per-source DNAT stops TCP SYN/UDP/ICMP while a task
  runs (but see F3: the source address can be changed).
- Smallest fix: drop the hairpin: `iptables -I FORWARD 1 -i tt-guest -o tt-guest -j DROP` before libvirt's FWX
  accept, in `start-guest-network`; add a gateway-MAC variant to `verify-isolation.sh`.

### F10. LOW. The Windows answer-file ISO, with the account password and product key, stays on disk world-readable

- Where: `guest/profiles/windows/steps/install:206-215` (`build_answer_iso`: `xorriso -o answer.iso`, default umask,
  the file is never removed); `steps/lib/render_unattend.py:546-550` writes the staging copy `0600`, but the ISO does not.
- Verified live: `/var/lib/libvirt/tartarus/guests/lab1/builds/b2f48f9dcd08a/answer.iso`, mode `0644`
  (`libvirt-qemu:kvm`), `autounattend.xml` inside holds `<Password><Value>` in plain text (confirmed by listing and
  grepping for the element only, value not read out); the product key would be there when one is given. Any user in
  the container (`cape`, `inetsim`, `libvirt-qemu`, the parsers of hostile data) can read it. (The guest's own copy of
  the answer file under `C:\Windows\Panther` is not covered here; it was not inspected.)
- Smallest fix: delete `answer.iso` once the install step succeeds (and after a failure), or write it to `0600`/a `0700`
  directory and let libvirt chown it at start; note the build directory also holds `domain-install.xml` naming it.

### F11. LOW. The root control service writes into directories the `cape` user controls, following symlinks

- Where: `cape/bin/memory_logic.py:276-296` (`_write`: `rmtree`, `mkdir`, `write_text`, `chmod`), `:198` (`rmtree`),
  `:328-331` (`_give_to_owner_of` uses `os.chown`, which follows symlinks), `:179-191` (`unlink`).
- Code-read: `storage/analyses/<id>/` is owned by `cape` (created `install -d -o cape`), the service runs as root. A
  process running as `cape` (Volatility on a hostile image runs there) can swap `memory/` or its entries for symlinks
  between the service's mkdir and the writes/chown, making root overwrite or `chown` an arbitrary file to `cape`.
  Needs prior code execution as `cape` plus a race, and F1/F7 already give more, so it matters only once those are fixed.
- Smallest fix: do the writes as `cape` (`os.setresuid` in a child, or write via `run_command(user=CAPE_USER)`),
  or use `dir_fd`/`O_NOFOLLOW` and `os.chown(..., follow_symlinks=False)`.

### F12. LOW. Root-run code is loaded from a tree the `cape` user owns

- Where: `cape/Dockerfile:126` (`COPY --chown=cape:cape /opt/CAPEv2`); `cape/supervisord.conf:128-130` (rooter runs as
  root from `/opt/CAPEv2/utils/rooter.py` with `/opt/CAPEv2/.venv`).
- Verified live: `rooter.py` and the venv and `lib/` are `cape:cape` `755`/`644`. A compromised `cape` process edits
  `rooter.py` or any module it imports; root executes it at the next rooter or container start (and the rooter socket
  is `root:cape 0620`, so `cape` can already send rooter commands).
- Smallest fix: install CAPE as `root:root`, with only `storage/`, `log/` and the `custom/conf` dirs `cape`-writable.

### F13. LOW (code-read). The CAPE API token is on a command line every 15 s

- Where: `cape/Dockerfile:185-187` (`HEALTHCHECK ... curl -H "Authorization: Token ${CAPE_API_TOKEN}" ...`).
- Process command lines inside the container are visible to every user in it (e.g. `libvirt-qemu`, where a QEMU
  escape would land), and container processes appear in the host's process table to any local user. Not live-checked
  (see the note at the top).
- Smallest fix: `curl -K -` fed from a file, or a small python healthcheck that reads the env: `python3 -c "..."` with the token
  taken from `os.environ`.

### F14. LOW. `finish_logic.py` follows redirects from the guest agent

- Where: `cape/bin/finish_logic.py:22` (`DIRECT = build_opener(ProxyHandler({}))` keeps urllib's redirect handler).
- Code-read: the root service POSTs `/mkdir` to the guest's address; a hostile agent answers `302 Location: http://...`
  and urllib turns it into a GET from the root service's network position (blind: only the status is used). 307/308
  with a body are not followed. Impact: blind GET against internal services such as CAPE's reprocess URL or other
  non-authenticated GETs.
- Smallest fix: `build_opener(ProxyHandler({}), NoRedirect)` with a handler whose `redirect_request` returns `None`.

### F15. LOW. Secret hygiene on the host: `.env` is `0644`, and the CAPE token has no strength check

- Where: `/home/.../Tartarus/.env` (verified mode `644`, holds `POSTGRES_PASSWORD`, `CAPE_DB_PASSWORD`,
  `CAPE_API_TOKEN`, `GUEST_CONTROL_TOKEN`, `GUEST_PASSWORD`); `.env.example` ships `change-me` / `change-me-too`;
  `docker-compose.yml` uses `${VAR:?}` (rejects empty only); `scripts/preflight.sh:119-129` checks the length of
  `GUEST_CONTROL_TOKEN` only; `entrypoint.sh:6-8` accepts any non-empty `CAPE_API_TOKEN`; the stale comment
  "Secrets are generated into data/secrets.env" in `.env.example:2`.
- Smallest fix: `chmod 600 .env` in `make up`/preflight (and warn when group/other-readable), apply the 32-character
  minimum to `CAPE_API_TOKEN` and reject the `change-me*` placeholders in `preflight.sh` and the entrypoint.

### F16. LOW. Smaller hardening gaps around the guest network and media

- INetSim keeps whatever the guest sends (SMTP mail, FTP/TFTP uploads, logs, reports) under `/var/lib/inetsim`
  and `/var/log/inetsim` in the container's writable layer, unbounded and never cleared between tasks (verified the
  directories are writable and populated; no quota). A guest can fill the Docker host's disk.
- DHCP: 20-address pool, 10-minute leases (`tt-guest.xml`): a guest can exhaust it so a cold-booting clone gets no
  address; no MAC-spoofing filter (F3).
- `cape/guest_engine/media/mount.py:140` mounts the user's ISO with `-o ro` only (host kernel UDF/iso9660 driver):
  add `nosuid,nodev,noexec`. `guest/steps/define:136` and `copy:255` run `qemu-img convert` on user media/guest disks:
  a qcow2/vmdk in `data/iso` with a backing file reads any container file into the new guest's disk; pass `-f raw|qcow2`
  explicitly and `--image-opts`-free, or refuse backing files (`qemu-img info` first). Both inputs are the operator's own
  files, so this is hardening only.

### F17. LOW. Unpinned inputs at build time (known, `cape-integration.md:103`)

- `kvm-qemu.sh` does not verify the QEMU tarball (gpg "No public key" and continues), CAPE community signatures
  (`utils/community.py -waf -cr`) and Suricata rules come from the network at build time, `apt-get download ovmf` is unpinned,
  `ghcr.io/astral-sh/uv:0.12` and `ubuntu:24.04` are tags, not digests. Guacamole (sha256), Volatility3 (hashes)
  and `CAPE_REF` (full SHA) are pinned: checked, good. Fix: pin by digest and verify QEMU's signature with a vendored key.

### Info

- I1. The guest's account password is returned in plain text by `GET /guests` and `/guests/{name}`
  (`engine.py:502-509` masks only `options`), and by the backend to the GUI (`GuestCard.vue` reveal button). This is the
  documented design (`gui.md:361`). The product key is masked (`***`) in every view and redacted from build logs.
- I2. The cape container can reach the internet (it sits on a non-internal bridge, `docker-compose.yml:196-198`); `route=internet`
  and the symbol fetch depend on it. A compromised `cape` process can exfiltrate. Decision for the M11 review in
  `cape-integration.md:105`: keep, but once F1 and F3 are fixed consider an egress allow-list (symbols host only) for
  processes other than the rooter's routed guests.
- I3. `scripts/verify-guest.sh:17` and `scripts/e2e.sh:36` use a predictable `${TMPDIR:-/tmp}/tt-guest-verify`
  (`mkdir -p`, then a file inside is analysed); on a multi-user host another user can pre-create it. Use `mktemp -d`.
- I4. Control-service logging writes the raw request path (`control_http.py:189`, `log_message`) including control
  characters from the unauthenticated 401 path; no secrets are logged (no headers, no bodies); fix is cosmetic (`repr`).

---

## Checked, nothing found (what was checked)

**1. Guest-control HTTP service** (`bin/guest-control`, `bin/control_http.py`, `guest_engine/`)
- Authentication: `control_http.py:70-74` `hmac.compare_digest` on bytes, scheme compared case-insensitively; auth runs
  before routing (unknown paths and wrong methods answer 401 first); only `GET /healthz` is `public=True` (returns
  `{"ok": true}`); every route in the table (`guest-control:171-202`) goes through `_route` without `public`. The token
  is required and must be >= 32 characters (`settings_from`, exits otherwise); an empty token cannot be configured.
  Verified live: `ss` shows `172.18.0.3:8002` only, i.e. the control-network address, not the internal one; the control
  network is `internal: true`; `verify-cape.sh` checks that only backend and cape are on it.
- Input validation: guest names `[a-z][a-z0-9-]{1,31}` and build ids `[A-Za-z0-9_-]{1,64}` are fullmatch-validated on
  every route that uses them (`guest_name()`, `build_id()`); the path is matched raw (no percent-decoding), so `..` or `%2e`
  cannot reach a handler; task ids are `[0-9]{1,18}` (`parse_task_id`), memory `image` is confined to `/imports`
  (`normpath` + `parents` + `realpath` check + regular file), `tail` is bounded, symbols take only 32 hex digits and a bounded
  age, bodies are capped at 64 KB, chunked bodies refused, `Content-Length` must be digits, unknown build/clone fields
  are rejected (`_reject_unknown`), options are checked against the profile, media must be a file the scan listed.
  Names are re-validated by the registry (`SLUG`) and cannot start with `-`, so they cannot become option arguments.
- Command construction: no `shell=True` or `os.system` anywhere in `cape/`; `Host._virsh` / `run_command` / `run_step`
  use argument lists; steps get values via `TT_*` file paths (JSON read by `python3 -I`), never on a command line;
  `render_domain.py` and `render_unattend.py` XML-escape every substituted value and reject forbidden control characters;
  PowerShell script arguments built by `guest_agent.py` are single-quoted with `'` doubled and refuse line breaks (`guest_agent.py:_quoted`);
  `guest_agent` file names are `[A-Za-z0-9_.-]{1,64}` and the work folder a strict Windows path pattern;
  the `fetch` step accepts only a 64-hex hash, a plain file name and an http(s) URL from the profile manifest and
  verifies the SHA-256 before the final rename.
- Secrets: `step_environment` hands a step only `PATH LANG LC_ALL TZ HOME` plus `TT_*`
  (the service's own tokens never reach steps); Volatility and `pdbconv` run with a fixed 4-variable environment, as `cape`
  with supplementary groups cleared (`volatility.py:104-107`); `Redactor` masks the password and secret options in step
  output; `guest.json`, `context.json`, `build.json` and the build `log` are `0600` root (verified live); the
  libvirt XML temp file comes from `NamedTemporaryFile` (`0600`, random name).
- Randomness: generated passwords and machine identities use `random.SystemRandom` unless a test injects an rng.
- Symbols (`symbols_logic.py`): fixed https host, redirects only to `*.microsoft.com`/`*.blob.core.windows.net` over https,
  size and time caps, `lzma` decompression bounded, converter run as `cape`, result validated against the GUID/age
  before an atomic publish, no symlink followed on read: nothing found.
- Backend client: `httpx.AsyncClient` (no redirects by default), tokens held as `SecretStr`, header per request, the
  error text is not echoed.

**2. Guest to host.** The domain exposes no virtio-serial, qemu-guest-agent, shared folders, USB redirection, clipboard
or SPICE channel; devices are VGA, a tablet, an e1000e/virtio NIC, SATA disk and an emulated TPM; QEMU runs as
`libvirt-qemu` with libvirt's seccomp sandbox (`qemu.conf` comment; not changed). Host-side parsing of guest-controlled
data: the agent's stdout in `event_logs.py` (F8), the provisioning log (printed as `LOG` lines only; `log_guest_file`
prefixes every line so it cannot forge a protocol line), the `/execute` JSON in `guest_agent.py` (`json.loads` plus
regexes), the guest kernel's PDB id (fixed pattern), memory dumps (Volatility as `cape`, output capped at 64 MB,
timeouts per plugin and overall). CAPE's own ResultServer/BSON parsing is upstream code, pinned by `CAPE_REF`, not
reviewed here. Reachability from a hostile guest is covered by F3, F5 and F9; postgres and OpenSearch are not on the
guest's path (FORWARD is `DROP` and libvirt's `LIBVIRT_FWO` rejects `-i tt-guest`), except via the `internet` route (F2).

**3. Network isolation.** libvirt network `tt-guest` is a plain isolated network (no `<forward>`), DNS disabled so INetSim
owns 53 on the gateway only, DHCP from dnsmasq on the bridge only (live: `0.0.0.0%tt-guest:67`); INetSim, the
ResultServer (`192.168.150.1:2042`) and every INetSim service are bound to the gateway address (live `ss`); IPv6 forwarding
is `0` and the guest bridge has no global IPv6 address; `route_localnet=0` so loopback services (the 127.0.0.1 gunicorn bind and
the guests' VNC) are not reachable from the bridge; libvirt's TCP endpoint is off (`libvirtd.conf`, `verify-cape.sh`
checks it from another container). `verify-isolation.sh` proves only direct guest-to-guest reachability and the gateway
services; the gaps are F2, F3, F9.

**4. Container privileges** beyond F1/F6/F7/F12. No Docker socket is mounted; mounts (verified with `docker inspect`):
`imports:/imports:ro`, `./data/iso:/data/iso:ro`, volumes `cape-storage` and `guest-images` read-write; no host path is
mounted read-write. No ports are published for `cape`. Listeners (live): gunicorn `127.0.0.1:8000` and `172.19.0.6:8000`,
guacd `172.19.0.6:4822`, guest-control `172.18.0.3:8002`, INetSim/ResultServer/dnsmasq on the gateway; nothing on
`0.0.0.0` except dnsmasq's DHCP on `tt-guest`. supervisord has no inet_http_server; programs that run as root:
virtlogd, libvirtd, rooter, INetSim main, Suricata, guest-control (it needs root for libvirt, `qemu-img`, loop devices);
`cape` for the rest. `container_name`s and `restart: unless-stopped` are fine.

**5. CAPE API token.** `api.conf` `token_auth_enabled = yes`; the entrypoint refuses to start without the token; it is
provisioned as a SHA-256 hash for one Django user and rotating it revokes the old key (`provision-api-token.py`); the
`/apiv2/*` data endpoints answered 401 without it (verified: status, tasks/list, machines/list, exitnodes, report, pcap).
`ratelimit = no` is accepted since only the backend calls; the DB lookup is by hash. The web UI is the exception: F4.

**6. Shell scripts** (`scripts/*.sh`, `scripts/lib/*`, `guest/steps/*`, Windows profile steps, `cape/bin/*`, `cape/entrypoint.sh`,
`docker/postgres/init/01-databases.sh`): no `curl | sh` in the repo's own scripts, no `eval` of external text,
variables are quoted where they reach a command, secrets reach `build-guest.sh` through `docker compose exec -e` rather than
the command line, the Postgres init script passes the CAPE password to psql with `-v` and `:'cape_password'` (properly
quoted by psql), `start-guest-network` uses `mktemp`, `share-storage` only ever adds read bits (`chmod go+rX`) to files under
`storage/analyses`. Findings: F10, F15, I3. The only host-network action is `verify-cape.sh`'s read-only `docker run --network host
--cap-add NET_ADMIN ... nft list ruleset`.

---

## Severity-sorted table

| ID | Severity | Area | Where | One line | Smallest fix |
|---|---|---|---|---|---|
| F1 | High | 4 | `docker-compose.yml:141`, `Dockerfile:119-127` | privileged container; `cape` can write the host's raw disks (gid 993 collision, verified) | `cap_add` + explicit devices; remove `cape` from `suricata` |
| F2 | High | 3 | `routing.conf:9`, rooter chain order | `reject_segments` never applies (verified + reproduced); internet route reaches Docker nets and LAN | put `CAPE_REJECTED_SEGMENTS` jump above `CAPE_ACCEPTED_SEGMENTS` after rooter start |
| F3 | High (reasoned) | 3, 2 | no INPUT policy; rules keyed on guest IP | guest reaches CAPE web/API, guacd, control service; spoofing an unused IP dodges every rooter rule | INPUT default-deny for `tt-guest`; bind NIC to IP/MAC |
| F4 | Medium | 1, 5 | `supervisord.conf:213`, `settings.py:107` | whole CAPE web UI anonymous on `tartarus-internal`, `DEBUG = True` | `local_settings.py` DEBUG off + apiv2-only URLconf |
| F5 | Medium | 2, 4 | `supervisord.conf:144` | guacd unauthenticated on shared net: VNC of any guest, connect probe | bind to control network; VNC passwords |
| F6 | Medium | 4, 1 | `supervisord.conf`, `entrypoint.sh` | all tokens and DB password in every program's environment (verified for guacd, libvirtd) | `env -u` per program |
| F7 | Medium | 4 | `Dockerfile:123` | `sudo tcpdump` with free arguments = root | file capabilities instead of sudoers |
| F8 | Medium | 2 | `event_logs.py:114,135-144,424` | hostile agent: unbounded body, slow-drip stall, redirected POST | no redirects, size and deadline caps |
| F9 | Low | 3 | `isolation.py`, `LIBVIRT_FWX` | guest-to-guest via gateway MAC (reproduced, one-way) | `FORWARD -i tt-guest -o tt-guest -j DROP` |
| F10 | Low | 1, 6 | `steps/install:206-215` | `answer.iso` with password kept `0644` (verified) | delete after install / `0600` |
| F11 | Low | 1 | `memory_logic.py:198,276-331` | root writes/chowns inside a `cape`-owned tree, follows symlinks | write as `cape` or `O_NOFOLLOW` |
| F12 | Low | 4 | `Dockerfile:126` | root rooter loads code from a `cape`-owned tree (verified) | install CAPE root-owned |
| F13 | Low | 5 | `Dockerfile:185-187` | CAPE API token on the healthcheck command line | pass via env or file |
| F14 | Low | 2 | `finish_logic.py:22` | redirects followed from hostile agent (blind GET) | no-redirect opener |
| F15 | Low | 6, 5 | `.env` (644), `entrypoint.sh:6`, `.env.example` | secrets file world-readable, weak CAPE token accepted | `chmod 600`, length checks |
| F16 | Low | 3, 1 | INetSim dirs, `tt-guest.xml`, `mount.py:140` | unbounded INetSim data, DHCP exhaustion, mount flags, qemu-img backing files | quotas, `nosuid,nodev,noexec`, explicit `-f` |
| F17 | Low | 4 | `Dockerfile` | unpinned build inputs (known) | digests, signature check |
| I1-I4 | Info | various | see above | plain-text guest password by design; cape internet egress; `/tmp` paths; raw path logging | none required |

Counts: High 3, Medium 5, Low 9, Info 4.
