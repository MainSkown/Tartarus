# CAPE integration and guest VM

How Tartarus runs, configures and drives CAPEv2, and how the Windows guest gets built.

## `cape` container

| Aspect | Spec |
|---|---|
| Base | `ubuntu:24.04` (CAPE's reference OS) |
| CAPE version | Pinned via build arg `CAPE_REF` (git commit of `kevoreilly/CAPEv2`). CAPE has no releases and changes daily, so bump it deliberately and re-run the self-test. |
| Install | CAPE's own `installer/kvm-qemu.sh` (patched QEMU/SeaBIOS with anti-VM strings; `<WOOT>` placeholders replaced at build time from build args) and `installer/cape2.sh` (CAPE, poetry env, Suricata, tcpdump perms) |
| Privileges | `privileged: true`, `devices: [/dev/kvm]`. The container needs its own iptables, bridge and tun management for the rooter and libvirt. |
| Network namespace | Its own namespace (**not** `network_mode: host`). The guest bridge `tt-guest` lives only in this namespace. |
| Process supervisor | supervisord (no systemd): `virtlogd`, `libvirtd` (also listening on TCP `16509` for the backend's `qemu+tcp://cape/system` connection, bound to the internal compose network only), `cape-rooter`, `cape` (scheduler + ResultServer), `cape-processor`, `cape-web` (gunicorn, apiv2 only), `suricata`, `inetsim`, `guacd` |
| Databases | `postgres` service, database `cape`. No Mongo: `web.conf [web_reporting]` and `reporting.conf [mongodb]` stay at their shipped-disabled defaults, since Tartarus reads `report.json` instead of CAPE's Mongo-backed report viewer |
| Shared volume | `/opt/CAPEv2/storage` = `cape-storage` volume (backend mounts it read-only) |
| Health | `HEALTHCHECK` calls `apiv2/cuckoo/status/` and `virsh list` |
| Python deps | `pymongo` stays installed (CAPE's `apiv2/views.py` imports `bson.objectid.ObjectId` unconditionally), but no Mongo connection is ever opened since `web_reporting` is off |

**Prototype first (open question):** running libvirtd, the rooter's iptables and guacd inside a
privileged container is unverified. Milestone 0 is a spike that boots a guest and completes one
analysis in this setup. The fallback, if the spike fails, is libvirt on the host with only CAPE
userland in the container. That fallback would require a host-side `kvm-qemu.sh`, which ties
Tartarus to Ubuntu hosts.

## CAPE configuration overrides (`cape/conf/`)

Generated at container start from `.env` (Jinja templates), overriding CAPE's defaults:

| File | Settings |
|---|---|
| `cuckoo.conf` | `machinery = kvm`; `[resultserver] ip = 192.168.150.1, port = 2042`; `[timeouts] default = 180, critical = 120`; `[database] connection = postgresql://…/cape`; `freespace` threshold matches the Tartarus disk warning |
| `kvm.conf` | `machines = win`; `[win] label, platform = windows, ip = 192.168.150.10, snapshot = tartarus-clean, arch = x64, interface = tt-guest, tags = win10` or `win11` |
| `routing.conf` | `route = inetsim` (default); `[inetsim] enabled = yes, server = 192.168.150.1`; `internet = <container uplink>`; vpn/wireguard/socks5 sections from `.env` if configured; `[routing] reject_segments` for RFC1918 + Docker subnets |
| `auxiliary.conf` | `sysmon = yes` (Windows), ETW modules (`dns_etw`, `network_etw`, `wmi_etw`, `amsi_etw`) on, `QemuScreenshots` on |
| `processing.conf` | `behavior`, `network`, `suricata`, `CAPE`, `procmemory`, `strings`, `trid`, `die` on; `memory` (Volatility3) on but only runs when the task has `memory=1`; `virustotal` **off** (no data leaves the host) |
| `memory.conf` | Volatility3 plugins: pslist, pstree, malfind, netscan, handles, ldrmodules, hollowprocesses, processghosting, suspiciousthreads, unhookedsyscalls |
| `reporting.conf` | `jsondump = on`; `mongodb = off` (default; no Mongo service exists); `callback = on, url = http://backend:8000/internal/cape/callback`; everything else off |
| `web.conf` | `[guacamole] enabled = yes, guacd_host = 127.0.0.1` (Tartarus proxies guacd itself; CAPE's own guac web view is not exposed) |
| `api.conf` | Token auth on (token generated at first start and shared with the backend via the env file); `[taskstatus] enabled = yes` |

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
   - SMBIOS, BIOS, disk-serial and NIC strings taken from realistic vendor values (the
     `kvm-qemu.sh` placeholders).
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
6. **Register:** write `kvm.conf`, reload CAPE and check `apiv2/machines/list`.
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
