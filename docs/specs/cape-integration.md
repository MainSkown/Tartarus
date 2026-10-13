# CAPE integration and guest VM

How Tartarus runs, configures and drives CAPEv2, and how the Windows guest gets built.

## `cape` container

Built and proven by milestone M0a ([plan](../plans/m0-cape-spike.md)): all seven acceptance checks
pass with a throwaway Linux guest on KVM, so the host-libvirt fallback is not needed. Rerun them
with `make verify-cape`.

| Aspect | As built |
|---|---|
| Base | `ubuntu:24.04` |
| CAPE version | Pinned by `CAPE_REF` to a full commit SHA (default in `docker-compose.yml`, overridable in `.env`). CAPE has no releases and changes daily, so bump it deliberately and rerun `make verify-cape`. |
| Install | QEMU 9.2.2 and SeaBIOS 1.16.3 built by CAPE's `kvm-qemu.sh`, with the anti-VM strings passed as build args (`cape/build/kvm-config.sh`). libvirt is Ubuntu's 10.0.0 package with matching libvirt-python, not built from source. CAPE itself is installed by hand with **uv** from its `uv.lock`; `cape2.sh` is used only for Suricata, because its `sandbox` step hardcodes a localhost database, cron, a libvirt-python version and systemd sudoers. |
| Privileges | `privileged: true` and `/dev/kvm`. A narrower set looks feasible (see Findings) but is untested. |
| Network namespace | Its own namespace, never the host's. `tt-guest` (192.168.150.1/24), the rooter's iptables rules and QEMU's tap devices all live inside it. A `net.ipv4.ip_forward=1` sysctl is set on the container. |
| Process supervisor | supervisord, no systemd: `virtlogd`, `libvirtd`, `cape-rooter`, `cape` (scheduler and ResultServer), `cape-processor`, `cape-web` (gunicorn serving CAPE's whole Django app, reachable only on the internal network and loopback), `suricata`, `inetsim`, `guacd`. |
| libvirt | Listens on TCP `16509`, bound to the container's internal address only so the guest cannot reach it. **No authentication yet** (see Findings). `security_driver = "none"` and `cgroup_controllers = [ ]` in `qemu.conf`. |
| Guest network | `tt-guest` is a transient libvirt network rebuilt on every start: isolated (no forward), libvirt's DNS off so INetSim owns port 53, DHCP offering only `.10` with router and DNS `.1`. The Windows guest uses a static IP instead, because the rooter's INetSim route DNATs DHCP renewals. |
| INetSim | Ubuntu's 1.3.2, patched at build time because its DNS service dies with the Net::DNS in Ubuntu 24.04 (`main_loop` becomes `loop_once`); the build fails if the patch stops applying. |
| Databases | The `cape` database on the `postgres` service. No Mongo: `web.conf [web_reporting]` and `reporting.conf [mongodb]` stay disabled. `pymongo` stays installed because CAPE imports `bson` unconditionally. The entrypoint creates the schema once before any process starts, because CAPE's processes race on `CREATE TYPE`. |
| Volumes | `cape-storage` at `/opt/CAPEv2/storage` (the backend mounts it read-only). `guest-images` at `/var/lib/libvirt`, with `/etc/libvirt/qemu` symlinked into it, so domain XML, snapshots and the guest's registration survive recreating the container. |
| Compose | Behind the `cape` profile until M1: `docker compose --profile cape up -d cape`. Publishes no ports. |
| Idle cost | About 1 GiB of memory and 63 processes with no guest running; image 3.08 GB; a full build takes about 10 minutes (QEMU 7), a config-only rebuild about 17 seconds. |

## CAPE configuration

There are no Jinja templates. CAPE already layers `custom/conf/<name>.conf` over its defaults and
expands `%(ENV:NAME)s`, so `cape/conf/` holds plain files, credentials come from the compose
environment, and the one derived value (the gateway IP, from `GUEST_SUBNET`) is rendered with
`envsubst` into `custom/conf/{cuckoo,routing}.conf.d/guest-network.conf`. It is rendered by the
entrypoint into files because processes started with `docker compose exec` don't see variables
the entrypoint exports.

| File | Settings |
|---|---|
| `cuckoo.conf` | `machinery = kvm`; ResultServer on `192.168.150.1:2042`; timeouts; database connection to the `cape` database. |
| `kvm.conf` | Holds **no machine**. Registering a guest writes `/var/lib/libvirt/tartarus/kvm.conf.d/<label>.conf` (a `[kvm] machines = <label>` section plus a `[<label>]` section with `platform`, `ip`, `snapshot`, `arch`, `interface = tt-guest`, `tags`) and restarts `cape`. The `cape` program waits until a registered machine is defined, because `cuckoo.py` exits with "No machines available". |
| `routing.conf` | `route = inetsim`; `no_local_routing = no` (`yes` needs a VRF and the host's `vrf` module); `internet = eth0`; RFC1918 and Docker `reject_segments`. Only the inetsim route is verified; `internet` is configured but unexercised. |
| `api.conf` | Token auth on; `cuckoostatus` and `machinelist` enabled (both ship off); `ratelimit = no`, since token auth otherwise throttles the backend to 5 requests a minute. |
| `web.conf` | `[guacamole] enabled = yes` so CAPE records each guest's VNC port. `guacd` binds the internal address only. The backend uses `cape:4822` itself; CAPE's own Guacamole view is unused. |
| `auxiliary.conf` | Sysmon, ETW modules and `QemuScreenshots`: **deferred to M0b/M1**, they need a Windows guest. |
| `processing.conf`, `memory.conf` | **Deferred.** Volatility3 and its symbol tables are not installed yet. `virustotal` stays off (no data leaves the host). |
| `reporting.conf` | **Deferred.** `jsondump` on, `mongodb` off, plus the `callback` module pointing at the backend (M1). |

**API token.** `CAPE_API_TOKEN` comes from `.env`; the entrypoint refuses to start without one,
while compose doesn't require it, so `make up` works without the `cape` profile. On every start
it is provisioned into CAPE's `ApiKey` model (which stores a SHA-256 hash) for the Django user
`tartarus`, in a container-local SQLite file, so rotating the token revokes the old one.

**Start order matters.** CAPE's Django `settings.py` calls `init_rooter()` and `init_routing()`,
so `cape-web`, `cape-processor` and token provisioning all wait for the rooter and `tt-guest`
(`cape/bin/wait-then-exec`). And `cuckoo.py` powers off any running registered machine when it
starts, so the wizard's order is: define the domain, register it, restart `cape`, only then boot
and snapshot.

### Findings that need action

| Finding | Why it matters | Resolve |
|---|---|---|
| **libvirt on TCP has no authentication.** | Any container on `tartarus-internal` (nginx, OpenSearch, Postgres) gets full control of libvirt. It could define a VM that passes a host disk through, and because the container is privileged, that is host root. | Before M1 uses `qemu+tcp://`: authentication (SASL or TLS client certificates) and/or a network shared only by `cape` and `backend`. See the open question in [tartarus-v1](../features/tartarus-v1.md). |
| **The guest's SMBIOS still says QEMU.** `sys_vendor=QEMU`, `product_name=Standard PC (i440FX + PIIX, 1996)`. `kvm-qemu.sh` doesn't patch these. | A basic sandbox-detection check. | The guest's domain XML must set `<sysinfo>` and hide the hypervisor CPUID bit (already in wizard step 2). |
| Other anti-VM gaps. | SeaBIOS keeps its "SeaBIOS (version …)" banner and some unused legacy `BXPC` ACPI blobs. | Check with pafish in the self-test; accepted for now. |
| **Unpinned inputs at build time.** | `kvm-qemu.sh` doesn't verify the QEMU tarball (gpg reports "No public key" and continues); CAPE's community signatures come from master; the Suricata rules are a snapshot. Guacamole and Cirros are pinned by sha256. | Pin or verify when hardening the build. |
| `yara-python` comes from the wheel, not rebuilt with `--enable-cuckoo`/`magic` as `cape2.sh` does. Missing optional CAPE dependencies: httpreplay, regex, DIE, de4dot, Volatility3. `/opt/CAPEv2/.git` is removed, so `analysisinfo` logs an error. | Possible gaps in analysis output. | Check during M0b; fix what matters. |
| **`privileged: true` is probably broader than needed.** | Reasoned, not tested: libvirt/QEMU need the devices `/dev/kvm`, `/dev/net/tun`, `/dev/vhost-net` and capabilities `NET_ADMIN`, `SYS_ADMIN`, `SYS_RESOURCE`, `IPC_LOCK`, with seccomp (and AppArmor on such hosts) unconfined; the rooter and tcpdump need `NET_ADMIN` and `NET_RAW`. | Try `cap_add` plus those devices later; it would drop host block devices, `SYS_MODULE`, `SYS_RAWIO` and `SYS_PTRACE`. |
| The host auto-loads kernel modules on demand (`tap`, `tun`, `vhost_net`, `xt_*` and others). | They stay loaded until reboot and can't be unloaded without root. A host-side libvirt would load the same ones. | Accepted. `make verify-cape` prints them as `[INFO]`. |

Not verified in M0a: the `internet` route, that the domain and snapshot persist across
recreating the container, that the ResultServer binds `192.168.150.1:2042` (it starts only with a
registered guest), the `/dev/kvm` group-alignment code, and any Ubuntu or AppArmor host.

## How the backend talks to CAPE

| Need | Mechanism |
|---|---|
| Submit | `POST apiv2/tasks/create/file/` with `file`, `timeout`, `route`, `package`, `options` (`interactive=1`, `memory=1` as chosen), `machine=win` |
| Status | `GET apiv2/tasks/status/{id}/`, polled every 2 s while active, plus the callback when reporting finishes |
| Stop early | `GET apiv2/tasks/status/{id}/` + CAPE "stop" via the `tasks/delete` / machine stop path (exact call confirmed during the spike) |
| Extend | Interactive mode only. Implementation depends on CAPE support; if unavailable, "extend" is only offered before submission via the timeout. See open questions. |
| Live data | Files in `storage/analyses/{id}/` (shared volume): `logs/*.bson`, `aux/*.json` |
| Final data | `storage/analyses/{id}/reports/report.json`, `files/`, `CAPE/`, `procdump/`, `memory.dmp`, `dump.pcap`, `shots/`, `sysmon/`, `evtx/` |
| Delete | `GET apiv2/tasks/delete/{id}/` (removes CAPE DB rows and storage) |
| Desktop | Backend ↔ `guacd` (`cape:4822`, internal network) with a VNC connection to the guest's QEMU display |
| Health | `GET apiv2/cuckoo/status/`, `GET apiv2/machines/list/` |

## Guest VM build wizard

The goal is a hardened Windows guest built from an ISO the user supplies, with no manual CAPE
configuration.

### Supported guests
Windows 10 22H2 x64 and Windows 11 23H2+ x64. Only one guest is registered at a time.
Rebuilding replaces it after the new one passes its checks.

### Inputs
- An ISO placed in `./data/iso/`. The wizard lists the ISOs it finds and shows each one's
  edition and version (read from `sources/install.wim` metadata).
- Edition, product key (optional; evaluation ISOs work without a key), locale and keyboard
  (default: en-US), local username (default: a realistic random first name) and password.
- Resources: vCPUs (default 2), RAM (default 4 GB), disk (default 80 GB thin qcow2).
- Optional: "make it look used" decoys (documents, browser history, recent files, installed
  common apps) to defeat sandbox-detection checks for fresh systems.

### Steps (each shown with progress, log tail and status)
1. **Preflight:** `/dev/kvm` present, CPU virtualization flags, free disk ≥ disk size + 20 GB,
   ISO readable.
2. **Define VM:** libvirt domain from `guest/domain.xml.j2`:
   - `host-passthrough` CPU with the `hypervisor` feature disabled and KVM state hidden.
   - SMBIOS (`<sysinfo>`: system and board vendor, product name, serial), disk-serial and NIC
     strings set to realistic vendor values. The patched QEMU covers the BIOS, ACPI and device
     strings but not SMBIOS (see Findings).
   - A MAC address with a real vendor prefix (OUI).
   - Q35/UEFI with emulated TPM for Windows 11.
   - VNC display bound inside the container only.
3. **Unattended install:** generate `autounattend.xml` (`guest/autounattend.xml.j2`) and attach it
   with the provisioning scripts on a second ISO. Windows installs with no prompts.
4. **Provision** (first-logon PowerShell, logged back to the wizard):
   - Disable Windows Update, UAC prompts, the firewall, telemetry, sleep/hibernate and
     SmartScreen.
   - Disable Defender, including Tamper Protection. Tamper Protection can block a scripted
     disable. If it does, the wizard pauses and shows one manual step in the live desktop, then
     continues.
   - Install 32-bit Python 3.12 and Pillow.
   - Install CAPE `agent.py` as a scheduled task that starts at logon with highest privileges.
   - Install Sysmon with `guest/sysmon-config.xml`.
   - Set a static IP of `192.168.150.10` with gateway and DNS `192.168.150.1`.
   - Apply the decoys if that option was chosen.
5. **Snapshot:** reboot, wait for the agent on `:8000`, let the system idle for 60 s, then take a
   live snapshot (with memory) named `tartarus-clean`.
6. **Register:** write `kvm.conf.d/<label>.conf`, restart `cape` and check `apiv2/machines/list`.
7. **Self-test:**
   - Run a bundled benign test sample. It spawns a child process, writes a file, sets a registry
     value and resolves a domain. Check that live events, the final report and the INetSim DNS
     answer all arrive.
   - Run pafish and show its results as information only. This does not fail the build.

The build can be **resumed** from the last completed step and **restarted** from scratch. A
failed step shows its log and a Retry button.

### Guest health (shown in the header and on the Guest page)
| Check | OK when |
|---|---|
| VM defined | libvirt domain exists |
| Snapshot | `tartarus-clean` exists |
| Agent | Snapshot restore + agent `GET /status` succeeds (checked on demand and before each analysis) |
| CAPE registration | Machine listed by apiv2 |

## Interactive desktop

- The analyst turns it on per submission (on by default). CAPE's `interactive=1` option keeps
  the agent from auto-closing dialogs, so the analyst stays in control.
- The backend opens a Guacamole VNC connection through `guacd` and tunnels it over
  `WS /ws/analyses/{id}/desktop`. The GUI renders it with `guacamole-common-js`, with keyboard
  and mouse enabled.
- Available only while the task is `running`. When the task stops, the panel switches to the
  last screenshot.
- Clipboard sync between the host and the guest is **disabled**, both ways. Drag-and-drop and
  file transfer are disabled too.

## Windows hosts (post-v1, experimental)

The compose stack stays the same. Only the host prerequisites change:
1. Windows 11, with virtualization enabled in firmware.
2. An Ubuntu WSL2 distro with `nestedVirtualization=true` in `.wslconfig` and enough memory
   allotted (≥ 16 GB).
3. **Docker Engine installed inside that WSL2 distro, not Docker Desktop.** Docker Desktop's VM
   probably doesn't pass `/dev/kvm` to containers.
4. The preflight check verifies `/dev/kvm` and the vmx/svm CPU flags inside WSL2 and refuses to
   start with a clear message if they're missing.

Microsoft does not support third-party hypervisors nested in Hyper-V. Performance and
anti-VM stealth will be worse than on bare-metal Linux, and the docs must say so.
