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
| libvirt | Local UNIX socket only, for CAPE inside the container. The TCP endpoint is **off** (`libvirtd` runs without `--listen`): it has no authentication, and nothing needs it before the guest wizard (see Findings). `security_driver = "none"` and `cgroup_controllers = [ ]` in `qemu.conf`. |
| Guest network | `tt-guest` is a transient libvirt network rebuilt on every start: isolated (no forward), libvirt's DNS off so INetSim owns port 53, DHCP offering only `.10` with router and DNS `.1`. The Windows guest uses a static IP instead, because the rooter's INetSim route DNATs DHCP renewals. |
| INetSim | Ubuntu's 1.3.2, patched at build time because its DNS service dies with the Net::DNS in Ubuntu 24.04 (`main_loop` becomes `loop_once`); the build fails if the patch stops applying. |
| Databases | The `cape` database on the `postgres` service. No Mongo: `web.conf [web_reporting]` and `reporting.conf [mongodb]` stay disabled. `pymongo` stays installed because CAPE imports `bson` unconditionally. The entrypoint creates the schema once before any process starts, because CAPE's processes race on `CREATE TYPE`. |
| Volumes | `cape-storage` at `/opt/CAPEv2/storage` (the backend mounts it read-only). `guest-images` at `/var/lib/libvirt`, with `/etc/libvirt/qemu` symlinked into it, so domain XML, snapshots and the guest's registration survive recreating the container. |
| Compose | Part of the default stack (`make up`, `make dev`); `backend` waits for its health check. Publishes no ports. Without `/dev/kvm`, start the rest with `docker compose up -d --no-deps postgres opensearch backend frontend`. |
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
| `api.conf` | Token auth on; `cuckoostatus` and `machinelist` enabled (both ship off); `[taskdelete] enabled = yes`, because `tasks/delete` answers "Task Deletion API is Disabled" by default; `ratelimit = no`, since token auth otherwise throttles the backend to 5 requests a minute. |
| `web.conf` | `[guacamole] enabled = yes` so CAPE records each guest's VNC port. `guacd` binds the internal address only. The backend uses `cape:4822` itself; CAPE's own Guacamole view is unused. |
| `auxiliary.conf` | Sysmon, ETW modules and `QemuScreenshots`: **deferred to M0b/M1**, they need a Windows guest. |
| `processing.conf`, `memory.conf` | **Deferred.** Volatility3 and its symbol tables are not installed yet. `virustotal` stays off (no data leaves the host). |
| `reporting.conf` | `jsondump` on (its default), `mongodb` off, and the `callback` module enabled with `url = http://backend:8000/internal/cape/callback`. The module runs after the report is written, sets the task to `reported` itself, and catches its own failures: an unreachable backend is logged and changes neither the task nor the report (checked with the backend stopped and with a 404). `scripts/verify-guest.sh` layers a temporary listener over it through `reporting.conf.d/callback.conf`; CAPE loads that later, and the script removes only that file. |

**API token.** `CAPE_API_TOKEN` comes from `.env`; the entrypoint refuses to start without one,
and compose requires it too (`make up` fails with a message if `.env` lacks it). On every start
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
| **libvirt's TCP endpoint has no authentication, so it is off.** Resolved for now. | M0a ran it on the internal network: any container there (nginx, OpenSearch, Postgres) would get full control of libvirt, could define a VM that passes a host disk through, and because the container is privileged, that is host root. | `make verify-cape` now requires that nothing listens on `16509` and that another container's `qemu+tcp://cape/system` is refused. **Re-enabling it for the wizard (M6) needs** authentication (SASL or TLS client certificates) and a network shared only by `cape` and the backend, and the verifier's two checks changed to match. |
| **The guest's SMBIOS still says QEMU.** `sys_vendor=QEMU`, `product_name=Standard PC (i440FX + PIIX, 1996)`. `kvm-qemu.sh` doesn't patch these. | A basic sandbox-detection check. | The guest's domain XML must set `<sysinfo>` and hide the hypervisor CPUID bit (already in wizard step 2). |
| Other anti-VM gaps. | SeaBIOS keeps its "SeaBIOS (version …)" banner and some unused legacy `BXPC` ACPI blobs. | Check with pafish in the self-test; accepted for now. |
| **Unpinned inputs at build time.** | `kvm-qemu.sh` doesn't verify the QEMU tarball (gpg reports "No public key" and continues); CAPE's community signatures come from master; the Suricata rules are a snapshot. Guacamole and Cirros are pinned by sha256. | Pin or verify when hardening the build. |
| `yara-python` comes from the wheel, not rebuilt with `--enable-cuckoo`/`magic` as `cape2.sh` does. Missing optional CAPE dependencies: httpreplay, regex, DIE, de4dot, Volatility3. `/opt/CAPEv2/.git` is removed, so `analysisinfo` logs an error. | Possible gaps in analysis output. | Check during M0b; fix what matters. |
| **`privileged: true` is probably broader than needed.** | Reasoned, not tested: libvirt/QEMU need the devices `/dev/kvm`, `/dev/net/tun`, `/dev/vhost-net` and capabilities `NET_ADMIN`, `SYS_ADMIN`, `SYS_RESOURCE`, `IPC_LOCK`, with seccomp (and AppArmor on such hosts) unconfined; the rooter and tcpdump need `NET_ADMIN` and `NET_RAW`. | Try `cap_add` plus those devices later; it would drop host block devices, `SYS_MODULE`, `SYS_RAWIO` and `SYS_PTRACE`. |
| The host auto-loads kernel modules on demand (`tap`, `tun`, `vhost_net`, `xt_*` and others). | They stay loaded until reboot and can't be unloaded without root. A host-side libvirt would load the same ones. | Accepted. `make verify-cape` prints them as `[INFO]`. |

Not verified in M0a: the `internet` route, that the domain and snapshot persist across
recreating the container, that the ResultServer binds `192.168.150.1:2042` (it starts only with a
registered guest), the `/dev/kvm` group-alignment code, and any Ubuntu or AppArmor host.

## Findings from M0b: the Windows 11 guest

Built and proven by milestone M0b ([plan](../plans/m0-cape-spike.md)): checks 8 to 12 pass with
the user's `Win11_25H2_Polish_x64_v2.iso` (Windows 11 Pro, build 26200, pl-PL). **capemon works on
build 26200**: a benign sample ran to a finished report with 249 and 224 hooked API calls in its two
processes, its file write, registry write and command line, a DNS lookup answered by INetSim,
screenshots and a callback. No fallback image is needed. Rerun with `make build-guest`
(about 13.6 minutes, no input) and `make verify-guest` (about 100 seconds).

**What the guest reports about itself.** Dell OptiPlex SMBIOS and BIOS, Samsung disk, Intel
82574L NIC with a Dell MAC prefix, an AMD Ryzen CPU with `HypervisorPresent=False`, TPM 2.0,
Secure Boot on. No QEMU strings: the SMBIOS finding from M0a is closed. Remaining tells: the
display adapter is "Microsoft Basic Display Adapter", two empty optical drives, and KVM's rdtsc
timing around a forced VM exit. A pafish run outside a CAPE task found no identity tells.

**Image and domain changes it needed**
- Secure Boot with Microsoft keys comes from only the two OVMF files of Ubuntu's `ovmf` package;
  installing the package conflicts with the custom `qemu.deb`. The OVMF files are not pinned.
- libvirt 10.0 rejects every firmware lookup because of QEMU's loongarch64 descriptor, so only
  x86_64 descriptors are kept. swtpm runs as user `swtpm`.
- The domain uses Q35 and UEFI, SATA disk and CD-ROMs, e1000e and VGA, so no virtio drivers are
  needed. The libvirt element is `<baseBoard>`; lowercase `<baseboard>` is silently dropped.

**Snapshots are external.** libvirt 10.0 refuses internal snapshots of UEFI domains, so
`tartarus-clean` is an external disk-and-memory snapshot (`--memspec`/`--diskspec`): a memory file
plus an overlay. Each revert replaces the overlay, so overlays don't pile up. Revert takes about
1.6 seconds and the agent answers 1 second later. The CPU must be `migratable='on'`, or the exposed
`invtsc` flag blocks any memory save. **The base `win.qcow2` becomes a backing file and must never
be written directly.** libvirt 10.10 or later would allow internal snapshots.

**One registered guest at a time.** Each `kvm.conf.d/<label>.conf` sets `[kvm] machines` and the
last file read wins. Supporting several guests later (post-v1) means one registration listing all
machines; `make verify-cape` works around it for now.

**Provisioning results.** Scripted: the local admin `Analyst` with autologon, OOBE skipped, static
IP, Windows Update off, UAC off, firewall off with port 8000 open, sleep and hibernate off,
SmartScreen off, 32-bit Python 3.11.9 with Pillow, and CAPE's agent as a logon task. Caveats:
`AllowTelemetry=0` is honoured only on Enterprise and Education, so Pro keeps "Required"
telemetry; Sysmon was skipped. **Defender and Tamper Protection cannot be turned off by script**
by any documented means; `Set-MpPreference` reports success and changes nothing. The agent did
not try methods that bypass Tamper Protection. Defender did not block the analysis or capemon.

**Silent failures the wizard inherits** (none reported an error)
1. A malformed answer file (an undeclared `wcm:` prefix): Setup exits silently and WinPE reboots
   to the CD prompt in a loop, which looks like a black screen. A well-formedness test covers it.
2. "Press any key to boot from CD": with no key the firmware falls through to the empty disk. A key
   sent too late lands on Setup's "Cancel" button. The build sends Enter for the first 20 seconds.
3. `virsh destroy` right after provisioning lost unflushed writes; use an ACPI shutdown.
4. Windows applies the pl-PL time zone to an RTC in UTC, so the clock jumps 2 hours; CAPE sets
   the guest clock per task.
5. CAPE's agent `/execute` splits commands POSIX-style and removes backslashes: use `C:/` paths.
6. One API is not hooked on this build (`Unable to create trampoline for LockResource`).

**Fragile points.** The 20-second key window depends on firmware timing. The external-snapshot
setup assumes libvirt 10.0's revert behaviour. swtpm's state on the volume is owned by uid 102.
The default guest password `Tartarus1!` is in the repo and in plain text for autologon; it is a
throwaway account in an isolated guest.

**M1 can rely on:** a registered machine `win` (tags `windows,win11`) at 192.168.150.10 with the
snapshot `tartarus-clean`; tasks submitted with `machine=win`, `route=inetsim`, `package=exe`;
status going pending, running, completed, reported; capemon logs in `storage/analyses/<id>/logs/`
while it runs; `reports/report.json` afterwards; and a working `callback` reporting module (M1
should set the backend's URL in `reporting.conf`).

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
  editions, build and language, read from the metadata of `sources/install.wim` (`wiminfo`).
  Microsoft's retail ISOs keep their files in a UDF filesystem, and the ISO9660 view holds only a
  README, so the reader must handle UDF (7-Zip does; `bsdtar` does not). Reading the metadata
  means extracting the 7 GB image once, to scratch space inside a throwaway container.
- Edition: any index of the image (a retail ISO has eight or more: Home, Pro, Education and their
  N variants). Pro is the default. Product key is optional; installing without one works.
- Language: the image's own. An ISO carries one language (e.g. pl-PL), so the guest's display
  language is the ISO's and the wizard offers no other; the keyboard layout is a separate
  setting. Local username (default: a realistic random first name) and password.
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
   - Defender is **the user's choice, on by default** (a wizard option). Left on, the build needs
     no manual step. If the user chooses off: with Tamper Protection on (the default) the
     documented policy keys and `Set-MpPreference` are silently ignored, so the wizard pauses for
     a **manual step**: the user turns Tamper Protection off in Windows Security on the live
     desktop, then the wizard re-applies the settings (see M0b findings). Why it is a choice:
     samples may check whether Defender runs and behave differently when it doesn't, and leaving
     it on shows how a sample gets past Defender; turning it off helps when Defender would remove
     a sample before it runs.
   - Install 32-bit Python 3.12 and Pillow.
   - Install CAPE `agent.py` as a scheduled task that starts at logon with highest privileges.
   - Install Sysmon with `guest/sysmon-config.xml`.
   - Set a static IP of `192.168.150.10` with gateway and DNS `192.168.150.1`.
   - Apply the decoys if that option was chosen.
5. **Snapshot:** shut down with ACPI (never `virsh destroy`, which loses Windows' unflushed writes),
   boot the clean guest, wait until the agent answers on `:8000` and `C:\tartarus\provision.done`
   exists, let it idle for 60 s, then take an external disk-and-memory snapshot named
   `tartarus-clean` (see M0b findings).
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
