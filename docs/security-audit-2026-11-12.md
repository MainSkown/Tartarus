# Security hardening review — isolation posture

Date: 2026-11-12. This is the independent review named as pending in
[docs/security.md](security.md#the-v1-review). It is an internal review of Tartarus's own isolation
code, run to drive the v1.1 hardening work; every item below is a configuration or packaging weakness
in this repository with a concrete fix.

Method: static read of the cape container, the guest firewall, the guest domain, the desktop tunnel
and the backend boundaries; inspection of the built `tartarus-cape:latest` image and the host's
device-node groups; and a verification pass against the full stack brought up with
`docker compose up`. Verification observations are recorded per finding as "Verified" (the weakness
is present) or, for the controls that held, under [Controls confirmed sound](#controls-confirmed-sound).
All throwaway objects created during verification were removed; the real `win` guest was left
untouched.

## Scope

The question is where Tartarus's isolation is thinnest. The guest→gateway network boundary holds (see
the isolation proof below). The weakest layer is the `cape` container's own privilege and packaging
posture — the surface an escaped sample would land on — so the findings concentrate there, plus the
backend's HTTP boundary.

## Findings

### 1. High — the `cape` container's privilege posture makes the container the trust boundary, not the `cape` user

- The container runs `privileged: true` ([docker-compose.yml:141](../docker-compose.yml#L141)) with
  the full capability set and no seccomp/LSM confinement, and the in-container libvirt socket has no
  authentication (`auth_unix_rw = "none"`, [cape/templates/libvirtd.conf](../cape/templates/libvirtd.conf)),
  with `cape` in the `libvirt` group ([cape/Dockerfile:122](../cape/Dockerfile#L122)).
- libvirtd runs as root, so any principal that can reach the socket can ask it to act on host-visible
  resources (define a domain against a host block device, manage storage pools on arbitrary host
  paths). The `cape` user is the one that parses hostile input — the ResultServer on port 2042
  (reachable from a guest on every route), `utils/process.py` over the sample and dropped files,
  Volatility3 over an attacker-supplied memory image, and `gunicorn` — so code-exec as `cape`, not
  only container root, is sufficient to reach that socket.
- Net effect: the security boundary is the container edge, and inside it `cape` is as capable as
  container root for host-visible resources. The accepted-risk table frames this as "a root
  compromise inside it"; the review's point is that the bar is lower (unprivileged `cape`), because of
  the unauthenticated socket plus the privileged container. Dropping `cape` from `suricata`
  (already done) narrowed the device surface but not this path.
- **Verified:** inside the running container, `CapEff` is the full set, seccomp is off, no LSM profile
  is applied, and host block-device nodes are present. As the `cape` user, the libvirt socket accepts
  requests that operate on host-owned paths and can define a domain referencing a host block device.
  (The defined domain was never started and was removed; no host data was read or modified beyond a
  self-created throwaway canary that was deleted.)
- **Fix (priority 1):** complete the planned v1.1 work — add `<port isolated>` in the qemu hook, then
  drop `privileged` and enumerate the exact devices the container needs (`/dev/kvm`, the tap/bridge
  plumbing) instead of all of `/dev`. Until that lands, add a libvirt access-control policy that
  restricts `cape` to start / revert / stop / dumpxml of the *existing* registered domains and denies
  domain-define, disk-path edits and arbitrary storage-pool creation.

### 2. Medium — self-built QEMU 9.2.2 has no security-update path

- The image ships QEMU 9.2.2 (built from CAPE's `kvm-qemu.sh`), so it does not receive distribution
  security fixes for the device models a guest drives.
- `security_driver = "none"` ([cape/libvirt/qemu.conf](../cape/libvirt/qemu.conf)) plus the privileged
  container means a hypothetical device-model flaw would be reached with no AppArmor/SELinux
  confinement and no Docker seccomp around QEMU.
- Mitigating factors already present: QEMU's own seccomp sandbox is linked in, the device set is small
  (no guest-agent channel, shared folders, SPICE or memory balloon), and the NIC is the only
  guest-reachable device path.
- **Fix:** track a maintained QEMU stable series and rebuild on its point releases; add a version
  check that flags an aged QEMU build so the staleness is visible in CI.

### 3. Medium — image group ids collide with host device groups

- `cape` has gid 995 in the image; gid 995 on this host is `audio`, which owns `/dev/snd/*`. Because
  the ids coincide inside the privileged container, the `cape` user is treated as a member of the
  host's audio group and can open the host sound devices (microphone included).
- `libvirt-qemu` is in gid 107 (`kvm` in the image); the host device gids differ today, but the class
  of problem is the same — image service-user gids are not reserved against host collisions the way
  `pcap` already is (`groupmod --gid 64010 pcap`).
- [scripts/verify-cape-hardening.sh](../scripts/verify-cape-hardening.sh) checks only block devices
  and only the `cape` user, so the audio collision is not caught by the existing gate.
- **Verified:** as the `cape` user, `open()` succeeds on `/dev/snd/controlC0` and `/dev/snd/pcmC1D0c`
  (and on `/dev/dri/renderD128`, `/dev/nvidiactl`, `/dev/fuse`); `/dev/kmsg` is refused (EPERM). This
  is reachable without container root. The earlier disk-group fix holds — `cape` cannot read
  `/dev/nvme0n1p2`, `/dev/sda` or `/dev/sdb1` (gid 993).
- **Fix:** assign every image service user a fixed high gid with no host-device collision (as done for
  `pcap`), and extend `verify-cape-hardening.sh` to assert that neither `cape` nor `libvirt-qemu` can
  open any node under all of `/dev` beyond the ones they legitimately need.

### 4. Medium — the cape container has unrestricted egress

- The nftables ruleset constrains only traffic entering from `tt-guest`. Processes in the container
  (including the unprivileged `cape` user) can reach the LAN, the host, the public internet, and the
  backend API on `tartarus-internal`.
- The M11 review recorded this as I2 and left it open.
- **Verified:** from the `cape` user the backend API (`http://backend:8000/api/guests`), the LAN
  router (`http://192.168.0.1/`), a public host (`https://example.com/`) and `postgres:5432` are all
  reachable; `opensearch` is correctly off cape's networks and host `:22` is closed.
- **Fix:** add an nft output chain in the container keyed on process uid, allowing only the egress each
  program needs (the symbol-fetch host for the debug-symbol step, and the routed guests' own egress),
  and dropping the rest by default.

### 5. Low–Medium — the `internet` route does not block the host's own public address

- The blocked set is the reserved private ranges plus the networks observed at start
  ([cape/guest_engine/firewall.py:33](../cape/guest_engine/firewall.py#L33) and `networks_behind`).
  A host public IPv4 is not in that set, so a guest on the `internet` route could reach host services
  bound to `0.0.0.0` via the host's public address, and on some home networks the router's WAN
  address and admin page.
- **Verified (does not bite on this host):** the host has a public IPv4, but from the LAN side its WAN
  ports 80/443/8080/22/23 are closed and the WAN address returns no HTTP; the router admin answers only
  on the LAN address. The mechanism is valid for hosts whose edge does answer on the WAN, so the fix
  is worth shipping as optional hardening.
- **Fix:** an optional "extra blocked addresses" setting folded into the `@unreachable` set, plus a
  note in the safety guide for operators whose host has a reachable public or router address.

### 6. Low — Tartarus does not own the default-deny for forwarded guest traffic

- The inet `forward` chain is `policy accept`
  ([cape/guest_engine/firewall.py:168](../cape/guest_engine/firewall.py#L168)); forwarded traffic from
  an unexpected source address is stopped by libvirt's own iptables chains rather than by the Tartarus
  table. The inet `input` chain accepts every port on the gateway, not only ResultServer, INetSim and
  DHCP.
- In practice the boundary holds (the isolation proof passes, and `iptables -P FORWARD` is `DROP` with
  libvirt's `LIBVIRT_FWO` rejecting `tt-guest` egress). This finding is about Tartarus owning its own
  default-deny rather than depending on libvirt's chains — defence in depth, not a live gap.
- **Fix:** set the Tartarus `forward` chain to drop forwarded traffic whose source is not a bound guest
  address, and enumerate the allowed gateway ports in the `input` chain instead of accepting all.

### 7. Low — clone firmware handling (revert path is sound; clone path needs confirmation)

- The clean snapshot covers disk and memory ([guest/steps/snapshot](../guest/steps/snapshot)).
- **Verified — revert restores NVRAM.** Writing a UEFI variable inside a throwaway clone changed its
  `VARS.fd` on disk; after `snapshot-revert … tartarus-clean` the file returned to the clean hash and
  the variable read back at its default. So the libvirt internal snapshot does capture and restore
  NVRAM on revert on this libvirt/QEMU — the "firmware is outside the revert" concern does **not**
  apply to the revert path.
- **Open — clone path.** `guest/steps/copy` ([guest/steps/copy](../guest/steps/copy)) copies the
  source's current on-disk `VARS.fd`, so firmware variables present on the source at clone time would
  carry into the clone's first boot. This was not exercised (it would require dirtying the real `win`
  guest's firmware).
- **Fix:** keep a pristine NVRAM copy taken at snapshot time and clone from that; add a check that the
  clone's `VARS.fd` matches the pristine copy, not the source's live file.

## Controls confirmed sound

Verified against the running stack (or by read where noted); no change needed.

- **Guest → network isolation.** `make verify-isolation GUESTS="win auditb"` passed all 18 checks: two
  live guests on every route (`raw`, `none`, `inetsim`, `internet`), plus the three evasions the suite
  covers (a guest using an address of its own invention, a guest claiming the other guest's address,
  and traffic aimed at the other guest through the gateway MAC). A guest reaches only its route's
  allowed targets and never the compose networks, the LAN, guacd, the control service, the backend,
  postgres, opensearch, the docker host, off-route internet, or the other guest. (The second guest was
  a clone of `win` built through the public API for the test and deleted afterwards.)
- **Guest firewall internals.** The bridge table defaults to drop, binds MAC + address per port, and
  drops IPv6 and non-IP frames; the qemu hook fails closed (an unrecorded port has no connectivity).
- **Guest domain.** No host channel beyond the NIC and loopback-bound VNC; no virtio-serial, guest
  agent, shared folders, USB redirection, clipboard or SPICE.
- **Desktop tunnel.** Clipboard disabled at guacd; browser→guacd opcodes allow-listed
  ([backend/app/desktop/tunnel.py](../backend/app/desktop/tunnel.py)).
- **Backend HTTP boundary** (through the published `127.0.0.1:8080` nginx):
  - Download endpoints (artifact / screenshot / job / ioc): encoded `..%2f…` returned 404 and raw
    `../` forms normalised to the SPA index — no file disclosure on any route tried.
  - FastAPI schema/Swagger is not exposed through nginx (`/docs`, `/redoc`, `/openapi.json`,
    `/apiv2/…` all serve the SPA index).
  - Host/Origin guard: foreign `Host` → 421; cross-origin, `null`, and look-alike origins on POST →
    403 (DNS-rebinding and look-alike origins covered).
  - Zip member listing (`/api/analyses/archive-members`): rejects >1000 members, an over-large central
    directory, and a declared-size lie patched to 3 GiB — all before any extraction; an honest 64 MiB
    member lists fine; traversal/absolute member names are flagged `unsafe` and never extracted; an
    upload over nginx's 512m cap → 413.
  - Events search size is capped server-side at 500.
- **CAPE database role.** The `cape` Postgres role is non-superuser, sees only its own `cape` database
  (17 tables), and sees zero tables when pointed at the `tartarus` or `postgres` databases.
- **Event-log export.** Size caps, deadlines, no redirects
  ([cape/auxiliary/event_logs.py](../cape/auxiliary/event_logs.py)).
- **Zip submission backend.** Members are listed and the password checked without extraction
  ([backend/app/samples/archive.py](../backend/app/samples/archive.py)).
- **Artifact downloads.** Confined to the analysis directory (`is_relative_to`), served as
  password-protected (`infected`) zips.
- **Browser boundary.** nginx and backend origin guards hold; no `v-html` sink in the frontend.
- **`keep-secrets`.** Per-program secret scoping is correct (`verify-cape-hardening.sh` passes).

## Per-container privilege posture

| container | pid-1 user | privileged | capabilities | NoNewPrivs | seccomp |
|---|---|---|---|---|---|
| postgres | 999 | no | none | 0 | default |
| opensearch | 1000 | no | none | 1 | default |
| backend | 1000 | no | none | 0 | default |
| frontend | 0 (nginx master) | no | nginx default set | 0 | default |
| **cape** | **0** | **yes** | **full** | 0 | **off** |

Only `cape` is privileged and unconfined — consistent with findings 1–4 being the whole high-value
surface. Every other service runs unprivileged with the default seccomp profile and no added
capabilities.

## Not covered

- CAPE's upstream code at the pinned commit, and QEMU internals.
- The guest→container hop itself (would need a live guest plus a genuine VM-escape primitive); this
  review assumes a guest escape is possible and assesses what it would reach.
- Backend ingest parsers and the frontend beyond the spot checks above (relied on the C1/C4 reviews).
- The two untracked draft specs (`docs/features/fake-lan.md`,
  `docs/features/tunnel-routes-and-tls-interception.md`);
  both change the isolation rules and need their own review before being built.

## Remediation order

1. **Finding 1** — the container-edge privilege posture (drop `privileged` + enumerate devices, or the
   interim libvirt ACL). Highest impact; everything else is secondary to it.
2. **Finding 3** — fixed high gids for image service users + extend the hardening check. Small and
   self-contained; closes the audio exposure that needs no container root.
3. **Finding 4** — per-uid egress chain in the container.
4. **Finding 2** — QEMU update path and staleness check.
5. **Findings 6, 7, 5** — Tartarus-owned forward default-deny; clone-from-pristine NVRAM; optional
   extra-blocked-addresses setting.

## Remediation (2026-11-13)

What was done about each finding, and how it was proven. The proofs ran against the rebuilt stack with
the real `win` guest and a clone of it (`auditb`, built through the public API for the purpose).

| # | Finding | What changed | Proof |
|---|---|---|---|
| 1 | The `cape` user is as capable as container root | The container is no longer privileged: `cap_drop: ALL` plus a measured capability list, and only `/dev/kvm`, `/dev/net/tun`, `/dev/vhost-net` and loop devices. The bridge port flag `isolated` is set by the qemu hook over netlink, and no domain carries `<port isolated>`. libvirt's polkit access driver leaves `cape` four read actions. A root broker (`cape/bin/machine-broker`) reverts a registered guest to its recorded snapshot, powers it off and dumps its memory into the task's folder; CAPE's machinery is patched to ask it | `make verify-cape-hardening` (20 checks), `scripts/verify-guest.sh`, an analysis with a memory dump, `make verify-isolation` |
| 2 | QEMU has no update path | Tartarus pins the QEMU version and the tarball's SHA256 (9.2.4, the last 9.2 release); `scripts/check-qemu-age.py`, `make check-qemu-age` and a workflow of its own flag an aged or outdated pin | Unit tests; the image builds and runs guests on 9.2.4. **Open:** the 9.2 series has ended, so the check is red until a maintained series is adopted (see below) |
| 3 | Image group ids collide with host device groups | Every group a program runs with has a reserved gid (64020 and up); dnsmasq no longer runs with Debian's `dip`. The hardening check opens every node under `/dev` as `cape` and `libvirt-qemu` and reads every program's gids | `make verify-cape-hardening` |
| 4 | Unrestricted egress from the container | An nftables output chain of its own, default deny, keyed on the process user: `cape` reaches the CAPE database and nothing else, root reaches https on public addresses (the symbol fetch). CAPE's callback to the backend, and its VirusTotal and whois lookups, are switched off | `make verify-cape-hardening`; analyses complete without the callback |
| 5 | The `internet` route does not block the host's public address | `GUEST_BLOCKED_ADDRESSES` (optional) is folded into the blocked set; a bad value stops the container | Unit tests |
| 6 | Tartarus does not own the forward default-deny | Only a bound guest's own address is forwarded; the gateway accepts only the ports that listen there; the bridge carries no frame between ports | `make verify-isolation GUESTS="win auditb"`: 13 probes per scenario on every route, the invented and claimed addresses, and the gateway MAC trick |
| 7 | Clones copy the source's live firmware | The clean snapshot keeps a pristine firmware copy, and a clone is made from it and compared with it. A source without one is reverted once to make it: a running revert writes the snapshot's firmware back to the file (measured on `win`; a paused revert does not) | Step tests; `auditb` cloned from `win`, which had no pristine copy |

Found along the way:

- **The proposed interim fix for finding 1 was not enough.** `domain.snapshot`, which a revert needs, also
  lets its holder redefine a snapshot with an edited domain inside it and so start QEMU as root, and
  `core-dump` writes a root-owned file at any path. libvirt's permissions cannot separate these, which
  is why `cape` has neither and the broker exists.
- **VirusTotal and whois lookups were on.** CAPE's defaults sent each sample's hashes and URLs out; the
  spec said they were off. They are now off in `cape/conf/processing.conf` and blocked by the egress chain.
- **`scripts/verify-isolation.sh` checked its targets from inside the cape container**, which the egress
  chain now stops. Targets outside the container are tried from a throwaway container on the same networks.

Still open:

- Root inside the container keeps `SYS_ADMIN` (libvirt's mount namespace, the ISO scan's loop mount). See
  the accepted risks in [security.md](security.md#accepted-risks).
- QEMU has to move to a maintained series. 10.0.x and 11.1.x are the candidates; 11.1.3 was built with
  every anti-VM patch applying. What is missing is the proof that existing guests' memory snapshots restore.
