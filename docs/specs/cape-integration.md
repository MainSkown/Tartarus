# CAPE integration and guest VM

How Tartarus runs, configures and drives CAPEv2, and how guests are built, cloned and kept.

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
| Process supervisor | supervisord, no systemd: `virtlogd`, `libvirtd`, `cape-rooter`, `cape` (scheduler and ResultServer), `cape-processor`, `cape-web` (gunicorn serving CAPE's whole Django app, reachable only on the internal network and loopback), `suricata`, `inetsim`, `guacd`, `guest-control` (the guest control service, control address only, which also ends runs early). |
| libvirt | Local UNIX socket only, for CAPE inside the container. The TCP endpoint is **off** (`libvirtd` runs without `--listen`): it has no authentication, and the guest wizard does not need it, because it goes through the [control service](#the-control-service) instead (see Findings). `security_driver = "none"` and `cgroup_controllers = [ ]` in `qemu.conf`. |
| Guest network | `tt-guest` is a transient libvirt network rebuilt on every start: isolated (no forward), each guest NIC a `<port isolated='yes'/>` so guests cannot reach each other (the gateway's ResultServer and INetSim stay reachable), libvirt's DNS off so INetSim owns port 53, DHCP offering the pool `.100` to `.119` with router and DNS `.1`, for guests that cold-boot; registered guests have static addresses from `.10` to `.99`, because the rooter's INetSim route DNATs DHCP renewals. |
| INetSim | Ubuntu's 1.3.2, patched at build time because its DNS service dies with the Net::DNS in Ubuntu 24.04 (`main_loop` becomes `loop_once`); the build fails if the patch stops applying. |
| Analyzer patch | CAPE zips `analyzer/windows` and uploads it to the guest for every task, so the image patches it (`cape/patches/skip-packaged-apps.py`, run by the Dockerfile; it fails the build if CAPE's code moved) to not inject the monitor into Store apps in an interactive analysis, see "Store apps" under Interactive desktop, and (`cape/patches/leave-dcom-launch-alone.py`) to not inject the DCOM launcher service in an interactive analysis, see "The DCOM launcher" under Interactive desktop. No change to the guest or its snapshot. |
| Databases | The `cape` database on the `postgres` service. No Mongo: `web.conf [web_reporting]` and `reporting.conf [mongodb]` stay disabled. `pymongo` stays installed because CAPE imports `bson` unconditionally. The entrypoint creates the schema once before any process starts, because CAPE's processes race on `CREATE TYPE`. |
| Volumes | `cape-storage` at `/opt/CAPEv2/storage` (the backend mounts it read-only). `guest-images` at `/var/lib/libvirt`, with `/etc/libvirt/qemu` symlinked into it, so domain XML, disks, snapshots, the registry of guests (`tartarus/guests/`) and their CAPE registration survive recreating the container. `./data/iso` is bind-mounted read-only at `/data/iso`. |
| Compose | Part of the default stack (`make up`, `make dev`); `backend` waits for its health check. Publishes no ports. It is on two networks: `tartarus-internal` and `tartarus-control`, which only it and `backend` share. Without `/dev/kvm`, start the rest with `docker compose up -d --no-deps postgres opensearch backend frontend`. |
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
| `kvm.conf` | Holds **no machine**. The control service writes `/var/lib/libvirt/tartarus/kvm.conf.d/guests.conf` (a `[kvm] machines = a,b,c` section plus a `[<label>]` section per `testing` or `ready` guest with `platform`, `ip`, `snapshot`, `arch`, `interface = tt-guest`, `tags`: the profile's, plus the one its `cape.tag_rules` pick for the guest's media build) and restarts `cape`; it is the only file in that directory (see [Several guests](#several-guests)). The `cape` program waits until a registered machine is defined, because `cuckoo.py` exits with "No machines available". |
| `routing.conf` | `route = inetsim`; `no_local_routing = no` (`yes` needs a VRF and the host's `vrf` module); `internet = eth0`; RFC1918 and Docker `reject_segments`. Only the inetsim route is verified; `internet` is configured but unexercised. |
| `api.conf` | Token auth on; `cuckoostatus` and `machinelist` enabled (both ship off); `[taskdelete] enabled = yes`, because `tasks/delete` answers "Task Deletion API is Disabled" by default; `ratelimit = no`, since token auth otherwise throttles the backend to 5 requests a minute. |
| `web.conf` | `[guacamole] enabled = yes` so CAPE records each guest's VNC port. `guacd` binds the internal address only. The backend uses `cape:4822` itself; CAPE's own Guacamole view is unused. |
| `auxiliary.conf` | `[sniffer] interface = tt-guest`, and `[event_logs] enabled = yes` for the host-side [event logs module](#event-logs-module). The guest-side `[auxiliary_modules]` list and `sysmon_windows = no` are left alone: Sysmon's log is exported by the module, not by CAPE's own `sysmon` auxiliary (which clears the log before it installs). The ETW modules are dropped from v1 ([M8 plan](../plans/m8-event-sources.md)); `QemuScreenshots` is unchanged. Sysmon's events are a final-phase source with no live forwarder (decided 2026-10-17, [v1 open question 3](../features/tartarus-v1.md#open-questions)). |
| `processing.conf`, `memory.conf` | CAPE's own memory module stays off; Volatility3 is installed in CAPE's venv and run by the [control service](#the-control-service) instead ("Memory analysis"). `virustotal` stays off (no sample data leaves the host); the one outbound request is the symbol fetch, which sends only a PDB id ("Symbols"). |
| `reporting.conf` | `jsondump` on (its default), `mongodb` off, and the `callback` module enabled with `url = http://backend:8000/internal/cape/callback`. The module runs after the report is written, sets the task to `reported` itself, and catches its own failures: an unreachable backend is logged and changes neither the task nor the report (checked with the backend stopped and with a 404). `scripts/verify-guest.sh` layers a temporary listener over it through `reporting.conf.d/callback.conf`; CAPE loads that later, and the script removes only that file. |

### Event logs module

`cape/auxiliary/event_logs.py` is a CAPE auxiliary that runs on the host (in the `cape` container, copied by
the Dockerfile to `/opt/CAPEv2/modules/auxiliary/`, enabled by `[event_logs]` above). It asks the guest agent
(`:8000`, `/execute`) to export two Windows event logs, so it still works when the guest analyzer dies before
it starts its own modules, which is what Defender does to it on a detected sample.

| Channel | Lands in the analysis folder as | How it is exported |
|---|---|---|
| `Microsoft-Windows-Sysmon/Operational` | `sysmon/sysmon.xml` | `wevtutil`, decoded with the guest's ANSI code page (read from the registry) and written as UTF-8 |
| `Microsoft-Windows-Windows Defender/Operational` | `aux/defender.xml` | PowerShell `Get-WinEvent ... ToXml()` as UTF-8 |

Both are `<Events>` documents of the events as the guest wrote them. The channels are one table in the module;
a channel is added with one line. Sysmon is optional: a guest without it (an adopted guest) gets no
`sysmon.xml` and no error.

- **Baseline, not a clear.** `start()` records each channel's newest `EventRecordID`; `stop()` exports only
  records after it. The log is never cleared: a clear at the start would erase the sample's own Defender
  detection, which Defender writes before the analyzer starts. `start()` first waits up to 90 s for the agent's
  `/status`, because a slow guest after its revert would otherwise lose the export silently. A channel whose
  baseline still cannot be read (agent unreachable, channel missing, code page unreadable) is skipped, never
  exported whole, and is named in `aux/event_logs.json`, which the ingest turns into `summary.missing_exports` and the plain-words `summary.warnings`.
- **Sysmon config.** At `start()` the module pushes `guest/profiles/windows/sysmon-config.xml` (the image keeps it
  at `/usr/local/lib/tartarus/profiles/windows/`) to the guest through the agent and applies it with
  `Sysmon64.exe -accepteula -c`, then removes the file, before reading the baseline, so Sysmon's own
  config-change event is not exported. A guest built with an older config needs no rebuild.
- **Settle wait.** For Defender, `stop()` re-exports every 3 s until each detection (event 1116) has a closing
  event (1117, 1118 or 1119) with the same `Detection ID`, up to 30 s: Defender quarantines a file about 10 s
  after it detects it (worst seen 17.5 s). Sysmon never waits.
- **Always a file.** An export that ran but found nothing is written as an empty `<Events>` document, which says
  "Defender had nothing to say", as opposed to a missing file, which says "no export". Output that is not a
  well-formed `<Events>` document is not written; control characters XML forbids are dropped first.
- **Never raises.** CAPE aborts the task on an exception out of `start()` or `stop()`, so every failure is logged
  and the channel skipped. Every agent call has a short timeout (5 s to connect, 15 s for the baseline steps, 30 s
  to read Defender, 120 s to read Sysmon) and `stop()` as a whole is capped at 180 s.

**API token.** `CAPE_API_TOKEN` comes from `.env`; the entrypoint refuses to start without one,
and compose requires it too (`make up` fails with a message if `.env` lacks it). On every start
it is provisioned into CAPE's `ApiKey` model (which stores a SHA-256 hash) for the Django user
`tartarus`, in a container-local SQLite file, so rotating the token revokes the old one.

**Start order matters.** CAPE's Django `settings.py` calls `init_rooter()` and `init_routing()`,
so `cape-web`, `cape-processor` and token provisioning all wait for the rooter and `tt-guest`
(`cape/bin/wait-then-exec`). And `cape` powers off any running registered machine when it starts or
stops (S0b), so a guest is registered only after its snapshot is taken and it is powered off: the build
defines the domain, installs, provisions, snapshots, and only then registers it and restarts `cape`. The domain
must exist before it is registered, and a guest is unregistered before it is undefined.

### Findings that need action

| Finding | Why it matters | Resolve |
|---|---|---|
| **libvirt's TCP endpoint has no authentication, so it is off.** **Resolved in M6.** | M0a ran it on the internal network: any container there (nginx, OpenSearch, Postgres) would get full control of libvirt, could define a VM that passes a host disk through, and because the container is privileged, that is host root. | `make verify-cape` requires that nothing listens on `16509` and that another container's `qemu+tcp://cape/system` is refused. The wizard did not need the endpoint: a narrow, token-authenticated [control service](#the-control-service) inside `cape`, on a network only `cape` and `backend` share, does the building, and libvirt-python is not used. The endpoint stays off and the two checks stand; the verifier gained the control-service checks. |
| **The guest's SMBIOS still says QEMU.** `sys_vendor=QEMU`, `product_name=Standard PC (i440FX + PIIX, 1996)`. `kvm-qemu.sh` doesn't patch these. | A basic sandbox-detection check. | The guest's domain XML sets `<sysinfo>` and hides the hypervisor CPUID bit (done by the `define` step). |
| Other anti-VM gaps. | SeaBIOS keeps its "SeaBIOS (version …)" banner and some unused legacy `BXPC` ACPI blobs. | Accepted for now. pafish was meant to be run as information only; it is not built. |
| **Unpinned inputs at build time.** | `kvm-qemu.sh` doesn't verify the QEMU tarball (gpg reports "No public key" and continues); CAPE's community signatures come from master; the Suricata rules are a snapshot. Guacamole and Cirros are pinned by sha256. | Pin or verify when hardening the build. |
| `yara-python` comes from the wheel, not rebuilt with `--enable-cuckoo`/`magic` as `cape2.sh` does. Missing optional CAPE dependencies: httpreplay, regex, DIE, de4dot, Volatility3. `/opt/CAPEv2/.git` is removed, so `analysisinfo` logs an error. | Possible gaps in analysis output. | Check during M0b; fix what matters. |
| **The cape container can reach the internet, and one request now uses that.** | `tartarus-internal` is not `internal: true`, so `cape` has a default route (found in S3). The symbol fetch (`POST /symbols`, the `symbols` build step) sends one HTTPS request to Microsoft's symbol server with only a kernel's GUID and age; no sample or guest data leaves, and a failure is logged without failing a build. | Accepted for M8. The M11 security review decides whether `cape` should lose its route; the ISF can then be made elsewhere and copied into `symbols/windows/`. |
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
- The domain uses Q35 and UEFI, SATA disk, e1000e and VGA, so no virtio drivers are needed. Its two
  CD-ROMs are attached in install mode only: a run-mode domain has none (see [Self-test](#self-test)). The libvirt element is `<baseBoard>`; lowercase `<baseboard>` is silently dropped.

**Snapshots are external.** libvirt 10.0 refuses internal snapshots of UEFI domains, so
`tartarus-clean` is an external disk-and-memory snapshot (`--memspec`/`--diskspec`): a memory file
plus an overlay. Each revert replaces the overlay, so overlays don't pile up. Revert takes about
1.6 seconds and the agent answers 1 second later. The CPU must be `migratable='on'`, or the exposed
`invtsc` flag blocks any memory save. **The base `win.qcow2` becomes a backing file and must never
be written directly.** libvirt 10.10 or later would allow internal snapshots.

**One registered guest at a time (lifted in M6).** M0b registered the guest in `kvm.conf.d/win.conf`;
each file sets `[kvm] machines` and the last file read wins, so two files cannot list two guests. M6 replaced
the per-guest files with one `guests.conf` listing every guest, and the control service deletes every other
`*.conf` (see [Several guests](#several-guests)). `make verify-cape` still stashes every `*.conf` around its
throwaway probe guest.

**Provisioning results.** Scripted: the local admin `Analyst` with autologon, OOBE skipped, static
IP, Windows Update off, UAC off, firewall off with port 8000 open, sleep and hibernate off,
SmartScreen off, 32-bit Python 3.11.9 with Pillow, and CAPE's agent as a logon task. Caveats:
`AllowTelemetry=0` is honoured only on Enterprise and Education, so Pro keeps "Required"
telemetry; Sysmon was skipped (M6 installs it, option on). **Defender and Tamper Protection cannot be turned
off by any documented script**; `Set-MpPreference` reports success and changes nothing. M0b did not try methods
that bypass Tamper Protection; M6 turns it off with a scripted click on its toggle (see
[Defender](#defender)). Defender did not block the analysis or capemon.

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
The M0b guest's password `Tartarus1!` is in the repo and in plain text for autologon; it is a
throwaway account in an isolated guest. Guests the wizard builds get a random password (still in plain text
for autologon), so only the adopted `win` has this one.

**M1 can rely on:** a registered machine `win` (tags `windows,win11`) at 192.168.150.10 with the
snapshot `tartarus-clean`; tasks submitted with `machine=win`, `route=inetsim`, `package=exe`;
status going pending, running, completed, reported; capemon logs in `storage/analyses/<id>/logs/`
while it runs; `reports/report.json` afterwards; and a working `callback` reporting module (M1
should set the backend's URL in `reporting.conf`).

## How the backend talks to CAPE

| Need | Mechanism |
|---|---|
| Submit | `POST apiv2/tasks/create/file/` with `file`, `timeout`, `route`, `package`, `options` (the profile's interactive options), `machine=<guest label>`, always sent, and further form fields from the guest's profile (`enforce_timeout` for Linux) and from the analysis (`memory=1` when it asked for a memory dump). `memory=1` is a **form field, never part of the `options` string**: `options=memory=1` was measured to take no dump ([S3](../plans/m8-spikes/S3-findings.md)). CAPE answers an unknown machine with HTTP 200 and `{"error": true, "error_value": "Machine 'x' does not exist..."}` and creates no task, so the backend reads `error`, not the status |
| Status | `GET apiv2/tasks/status/{id}/`, polled every 2 s while active, plus the callback when reporting finishes |
| Stop early | `POST http://cape-control:8002/tasks/{id}/finish` with `{"guest": "<name>"}` to the guest control service (bearer token, `tartarus-control` network). The guest network exists only inside the `cape` container, so the service does what the backend cannot: it looks up that guest's address, agent port and finish folder in its own record and profile (the backend never supplies an address, so there is nothing to validate and no path to inject) and asks the guest agent (`POST /mkdir`) to create `<finish folder>/<md5("cape-<task id>")>` (`C:\Windows\Temp` for Windows). CAPE's analyzer (`analyzer.py`, `analysis_loop`) ends the analysis as soon as a folder of that name exists in `%TMP%` or `%SystemRoot%\Temp`, then uploads its results as for a timeout; the agent's `mkdir` is `os.makedirs(exist_ok=True)`, so asking twice is harmless. It answers `200 {"finished": true}`, `502 {"error"}` when the agent is unreachable or refuses, `422` for a bad guest name, `400` for a task id that is not digits, `404` for an unknown guest. |
| Extend | Interactive runs only, and not a CAPE feature. **Built in M7** ([M7 plan](../plans/m7-foundations.md), decision 5): the task is submitted with CAPE's maximum timeout (1200 s), and the backend ends the run at the analyst's deadline through the finish call. The deadline is the oldest `logs/*.bson` modification time plus the analyst's timeout, set once the monitor has started, and is capped at `started_at` + 1200 s, which keeps the backend ahead of CAPE's own timer (measured in S1: no earlier than `started_at` + 1222 s). `POST /analyses/{id}/extend` moves it later by up to 600 s at a time. |
| Live data | Files in `storage/analyses/{id}/` (shared volume): `logs/*.bson`, `aux/*.json` |
| Final data | `storage/analyses/{id}/reports/report.json`, `files/`, `CAPE/`, `procdump/`, `memory.dmp`, `dump.pcap`, `shots/`, `sysmon/`, `evtx/` |
| File access | The backend mounts the storage read-only as another user. CAPE saves uploaded files (`files/`, `procdump/`, `shots/`) through Python's temporary-file API, always mode `0600`, so `cape/bin/share-storage` (a supervisord program in the `cape` container) adds read and directory-search bits for others within seconds of a file appearing. Found on the real stack by `make e2e`: before it, artifact downloads answered 500 and screenshots broke mid-response. |
| Delete | `GET apiv2/tasks/delete/{id}/` (removes CAPE DB rows and storage) |
| Desktop | Backend ↔ `guacd` (`cape:4822`, internal network) with a VNC connection to the guest's QEMU display |
| Health | `GET apiv2/cuckoo/status/`, `GET apiv2/machines/list/` |

## Guest VM build wizard

Built and run for real in M6 ([plan](../plans/m6-guest-wizard.md), including what each wave proved and what
is still open). The analyst builds, clones, checks and deletes guests from the GUI with no shell on the host;
there can be several guests, and the analyst picks one for every detonation. **What is Windows-specific is a
guest profile**; everything else on this page is generic and driven by it. How to add an operating system is
in [guest profiles](guest-profiles.md).

### The control service

The backend must not hold libvirt or Docker credentials, so it asks a narrow service inside `cape`.
`guest-control` (`cape/bin/guest-control`, a supervisord program) is a stdlib HTTP server over the guest
engine (`cape/guest_engine/`). It replaces the plan to expose libvirt over TCP: **libvirt's TCP endpoint stays
off and the Docker socket is never mounted.**

- **Network.** It listens only on the `tartarus-control` network (port 8002), an `internal: true` compose
  network that only `cape` and `backend` join. `cape` has the aliases `cape-internal` and `cape-control` on its
  two networks, and the backend reaches the service as `cape-control`; the entrypoint tells the interfaces
  apart by the address each alias resolves to.
- **Authentication.** Every route but `GET /healthz` needs `Authorization: Bearer <GUEST_CONTROL_TOKEN>`
  (`.env`, 32 characters at least, compared in constant time); without it the answer is `401`, and the
  service will not start with a short or missing token. The request log never holds a header or a body.
- **Narrow, validated operations only.** Routes: `GET /profiles`, `GET /media`, `GET /guests`, `GET` and
  `DELETE /guests/{name}`, `POST /guests/{name}/check`, `POST /guests/{name}/clone`, `POST /guests/{name}/selftest` (run a failed guest's self-test again: it answers the
  id of the guest's finished build), `GET
  /guests/{name}/display`, `GET /guests/{name}/selftest/sample`, `POST /guests/{name}/selftest/checks`,
  `POST /builds`, `GET /builds/{id}` and `/log?tail=`, `POST /builds/{id}/resume|restart|continue|complete|cancel`,
  `POST /tasks/{id}/finish`, the memory routes `POST /memory/{id}/analyse` and `DELETE /memory/{id}/dump`, and
  `POST /symbols` (below). A refusal is `404` (unknown guest, build or profile), `409` (the current
  state refuses, with a message for the analyst), `422` (a parameter is wrong, with `fields`), or `400` for a
  guest name or build id that does not match its pattern; a sample that cannot be built is `500` and checks
  that cannot run `502`, each with its message; anything else is a generic `500` with the detail in the log.
  Values reach a step through files and the environment, never a command line.
- **What it still is.** The container is privileged, so the service is root-equivalent on that namespace. A
  compromised backend can build and delete guests; it cannot run anything else. `make verify-cape` proves the
  control service answers the backend with the token, refuses a request with none or a wrong one, is on a
  network only `cape` and `backend` are on, listens only on its control address, and cannot be reached from
  `frontend`, `opensearch` or `postgres`; and that nothing listens on libvirt's `16509`.
- **Lifetime.** The service owns the truth of every build. When it starts it removes loop mounts a killed
  predecessor left, stops a step process the predecessor left running, marks that build `failed` (with a
  "resume it" message), and adopts guests it finds registered but not recorded. When it is stopped (SIGTERM;
  supervisord waits up to 30 s) it stops the running step, 5 s of grace and then a kill, and fails that build
  so the next start can resume it. A paused build stays paused.

The same engine is reachable from a shell: `docker compose exec cape guest-build` (what `make build-guest`
wraps, with the `GUEST_*` variables of `.env`) starts a build through the running service and prints the log. A
guest it builds is accepted without the backend's self-test, so `make verify-guest` is what proves it.

**Memory dump (S3).** With the form field `memory=1` CAPE dumps the guest's RAM after the guest reports the run finished and before it
stops the machine: libvirt's `coreDump` with `VIR_DUMP_MEMORY_ONLY`, written as `storage/analyses/<id>/memory.dmp` by `cape`. It is an
ELF64 core file (`ET_CORE`, x86-64) that Volatility3 reads without conversion, never compressed, and as big as the guest's RAM:
4,294,776,995 bytes (4.0 GiB) for a 4096 MB guest (`memballoon` none). The dump takes 1 to 2 s with the guest paused and does not change
the analysis (same score, same signatures, same guest run time). CAPE skips the dump, logging `Not enough free disk space! Could not
dump ram` and still ending the task `reported`, when the storage has less than `cuckoo.conf freespace` (50,000 MB) free, so the
backend checks the room before it accepts an analysis that asks for one ([backend spec](backend.md)). CAPE's own `memory` processing
module stays off: it scans all processes (136 to 154 s), cannot be limited to the sample's pids, and leaves `cape-processor` holding
the dump open after it is deleted.

**Memory analysis.** `POST /memory/{task_id}/analyse` runs Volatility3 (`cape/bin/memory_logic.py`, command line in
`cape/bin/volatility.py`) on `storage/analyses/<id>/memory.dmp`, in place, as the `cape` user, with `--offline`
and the ISF files under `/var/lib/libvirt/tartarus/symbols/windows/` (on the `guest-images` volume). It runs
`windows.pslist` and `windows.cmdline` over the whole dump and `windows.malware.malfind` and
`windows.malware.hollowprocesses` with `--pid` of `behavior.processes[].process_id` from `reports/report.json`, and
leaves one `<plugin>.json` per plugin and a `run.json` in `storage/analyses/<id>/memory/`, which the backend reads.
`200` carries `{"plugins": {name: rows}, "errors": {name: text}, "seconds", "pids"}` (a plugin that fails, or
missing symbols, is an entry in `errors`, never a download); `404` no dump, `409` already running, `502`
`vol` cannot be started, `500` the results cannot be written. `DELETE /memory/{task_id}/dump` removes the dump
(`204`, `404`, `409` while it is being read): the backend has the storage read-only, so only this service can.
Why Volatility runs here and not in CAPE's own memory module: [S3 findings](../plans/m8-spikes/S3-findings.md).
When `windows.info` fails because no ISF matches the dump's kernel, `analyse` also reads the kernel's PDB id from
Volatility's INFO log (`windows.info` is the only plugin run with `-v`; with `--offline` the line is the URL of the
PDB it declined to fetch, `.../symbols/ntkrnlmp.pdb/<GUID><age>/ntkrnlmp.pdb`, as seen in the M8 real run) and adds `"missing_symbols": {"guid": "...", "age": n}` to the
`200` body and to `run.json`; the key is absent when symbols are fine or the id could not be read. That id is what
`POST /symbols` needs.

**Symbols (the one outbound connection of the memory pipeline).** Volatility needs an ISF per Windows kernel,
made from the kernel's PDB, which only Microsoft's symbol server has. `cape/bin/symbols_logic.py` does it:
`ensure_symbols(guid, age, symbols_dir, fetch, convert)` checks the id (32 hex digits and a 32-bit age, nothing
else), builds `https://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/<GUID, upper case><age, hex>/ntkrnlmp.pdb`
(the host and path are constants; no URL ever comes from outside), downloads it with a 50 MB cap and a 120 s
limit, converts it with Volatility's own `pdbconv --file ... --pattern ntkrnlmp.pdb` as the `cape` user, checks
that the result is the ISF of exactly that GUID and age, and writes
`/var/lib/libvirt/tartarus/symbols/windows/ntkrnlmp-<GUID><age>.json.xz` (mode 0644) in one rename, so a failure
leaves nothing behind and an existing valid file means no fetch at all. About 30 s the first time, 0.7 MB on disk.

- **What leaves the host.** One HTTPS `GET` to `msdl.microsoft.com`, which carries the kernel's GUID and age in the
  URL and nothing of the guest or the sample. The symbol server answers with a redirect to Microsoft's content
  host; a redirect is followed only to `https` and to `*.microsoft.com` or `*.blob.core.windows.net`, and refused
  (with the host named) anywhere else. Volatility itself still runs `--offline`.
- **The container is not offline today.** `tartarus-internal` is a plain bridge (not `internal: true`), so this
  request works because the container has a default route. The M11 security review decides whether the cape
  container should lose it; if it does, an operator makes the file where there is a network and copies it into
  `symbols/windows/`, and nothing else changes.
- **Two callers.** `POST /symbols` with `{"guid": "<32 hex>", "age": <number or up to 8 hex digits>}` and the bearer
  token: `200 {"file": "windows/ntkrnlmp-<GUID><age>.json.xz", "created": true|false}`, `400` for an id that is
  not one (or a body with other keys), `502 {"error": "..."}` when the file could not be made (no network, the
  server has no PDB for the build or is down, a download over the cap, a redirect elsewhere, the converter
  failed), each with a readable message. It takes about 30 s the first time. The Windows profile's `symbols`
  build step is the other caller.
- **The build step.** `symbols` is a step of the Windows profile (`guest/profiles/windows/steps/symbols`) that
  runs after the last Windows step and just before `snapshot`, in the build and the clone pipelines: the guest is
  still running there and its agent answers, and `snapshot` is what shuts it down. It fetches the guest's own
  `C:\Windows\Sysnative\ntoskrnl.exe` through the agent (the agent is 32-bit, so `System32` would be
  redirected), reads the PDB name, GUID and age from its debug directory (`steps/lib/pdb_id.py`, standard library
  only), and runs `guest-symbols ensure <GUID> <age>`, which is `symbols_logic` called directly: a step is a process
  of its own with a stripped environment and no token, so it cannot call the route. **It never fails the build**:
  without a network, with Microsoft's server down, or with an image it cannot read it logs
  `symbols: unavailable (reason)` and ends well. The guest then has no memory findings and `analyse` says
  `no symbols for this Windows build`. A clone of a guest with the same build finds the file and fetches nothing.
- **Fixing a guest built before this existed, or after a failed fetch.** Run `analyse` on a task with a dump, read
  `missing_symbols` in its answer, and post that id (the age is a number there):

  ```sh
  docker compose exec cape sh -c 'curl -fsS -X POST http://cape-control:8002/symbols \
    -H "Authorization: Bearer $GUEST_CONTROL_TOKEN" -H "Content-Type: application/json" \
    -d "{\"guid\": \"24DE61DB3A27C5B383DFF181CB51F7E1\", \"age\": 1}"'
  ```

  then analyse the dump again. Not tested against a real guest yet (the real-run proof of M8 does it).

### Several guests

- **The registry.** Each guest has a directory on the `guest-images` volume,
  `/var/lib/libvirt/tartarus/guests/<name>/`: `guest.json` (profile, media, options, identity, resources,
  address, hardware identity, state, last self-test) is the one source of truth, and the libvirt domain, the
  CAPE registration and the backend's view are derived from it; `builds/<id>/` holds each build's
  `build.json`, `log` and `context.json`. Disks, the memory file of the snapshot and the nvram are under
  `images/` and `nvram/`. A guest's **name** is a slug (2 to 32 lower-case letters, digits and hyphens, not ending in `-clean`, because that is how the snapshot files of another guest are named: `<name>` would give the disk `images/<name>.qcow2`, which is `<other>-clean`'s overlay); it is
  the libvirt domain name and CAPE machine label and exists nowhere inside the guest.
- **States.** `building` while a build or clone runs, `testing` once it has finished (registered with CAPE,
  but not offered for analyses) until the backend's self-test gives its verdict, then `ready`, or `failed`
  (unregistered, files kept so a step can be retried). A guest that failed its self-test after every build step passed
  can have the self-test run again (`POST /guests/{name}/selftest`): the control service registers it with CAPE again,
  the same way the build's `register` step does, and sets it `testing`; the backend runs the same self-test and the
  verdict makes it `ready` or `failed` again. A guest that failed during a step has no snapshot and is refused: its
  build is restarted or resumed instead. Only `ready` guests run analyses. A record that cannot be
  read is listed as `broken` so it can be deleted.
- **At most five guests** that are building, testing or ready. A `failed` guest does not count: it keeps its name and
  its address until it is deleted, but it never blocks a new build or clone. Each is a full, independent disk of about 22 GB (17 to 18 GB
  of disk and 3 GB of memory image for Windows 11): nothing is shared, so deleting any guest is safe. A
  linked clone would save the space and tie two guests' lifetimes; it is not built.
- **Addresses.** Every guest gets its own static address, the lowest free one from `.10` to `.99` of the guest
  /24, set at provisioning. The libvirt DHCP range is a separate pool, `.100` to `.119`, for guests that
  cold-boot on DHCP (every clone does): a second cold-booting client got no reply while the first held the
  single address the range used to be (S0b). CAPE accepts two machines with the same address without a
  warning and then cannot tell them apart (its ResultServer maps a connection to a task by the guest's source
  address), so the engine refuses duplicates itself.
- **One registration.** The engine renders a single `kvm.conf.d/guests.conf` (`[kvm] machines = a,b,c` and
  a section per guest) from every `testing` and `ready` guest and restarts `cape`; an empty list renders
  `machines =`, which makes `cape` wait for a guest. S0b proved CAPE serves two registered machines and
  routes each task by label, with its own revert, ResultServer connection, rooter rules, PCAP and callback.
  Rules the engine keeps, each learned the hard way:
  - it owns the **whole directory**: CAPE merges every `*.conf` in sorted order and the last `machines` key
    wins, so a leftover `win.conf` would silently un-register the rest, and it deletes every other `*.conf`;
  - **define the domain, then register, then restart `cape`, then check CAPE's `machines/list`**; never
    trust `supervisorctl`, because a registered machine libvirt does not know leaves `cape` "RUNNING" with
    every task pending; on deletion unregister before undefining, then remove the files the guest's build laid down under their fixed
    names (`images/<name>.qcow2`, `images/<name>-clean.mem`, `images/<name>-clean.qcow2`, `nvram/<name>_VARS.fd`),
    even when the domain is already gone, because undefining forgets them;
  - the backend keys on the **label**: CAPE recreates its machine rows and ids on every start, and the backend
    always sends `machine` because CAPE alternates between machines when it is left out.
- **Adoption.** The guest M0b built (`win`, `.10`) is adopted when the service first starts: its record is
  written from the domain XML and the registration file, and nothing is rebuilt. It keeps the account
  `Analyst`, the folder `C:\tartarus`, a firewall rule and other names that say what the machine is; the
  card lists them. A clone of it keeps all of them except the computer name. Rebuild for a clean one.

#### Building, checking, deleting and analysing exclude each other

Registering or deleting a guest restarts `cape`, and S0b measured what that does: a graceful restart destroys
the running guest 0.2 s after the signal, a kill is handled at the next start, and either way the task ends
`failed_analysis` with no report and no callback; a task queued for a machine the new registration removes
is failed too, and the sniffer's `tcpdump` can leak across the restart (the control service kills strays
after it). So:

- while a guest is `building` or `testing`, `POST /analyses` is `409` ("A guest is being built");
- a build, clone, resume, restart, continue, delete, `[RE-RUN SELF-TEST]` and `[RUN CHECKS]` (which reverts a snapshot) are `409`
  while an analysis is queued, starting or running on any guest; the `409` names those analyses and their guests;
- the engine runs one thing at a time: one build or clone (a paused one included), and no check or self-test
  check beside it.

The cost is that no sample can be detonated for the minutes a build takes. Analyses run one per guest and
several guests at once; a build, clone, resume, restart, continue, delete or check waits for every analysis on
every guest, because the restart it causes reaches all of them.

### Supported guests

Two guests are verified, each built and cloned with its self-test: Windows 11 25H2 x64 from the user's
`Win11_25H2_Polish_x64_v2.iso` (Pro, build 26200, pl-PL) and **Windows 10 22H2 x64 from
`Win10_22H2_EnglishInternational_x64v1.iso`** (Pro, build 19045, en-GB; M10). The GUI does not say which is which
beyond the edition name the media gave. What differs on Windows 10, found by building it:

- Setup stores the first-logon command in the `RunOnce` key and **Windows 10 silently skips a long one**, so the
  command carries only the media drive and `provision.ps1` reads its other parameters from `provision\parameters.json`
  on the same disc.
- Windows Security exposes its four switches **without an `AutomationId`** (Windows 11 gives all five `settingToggle`),
  so the switches are found by toggle behaviour; Tamper Protection is the last on both versions.
- Tamper Protection reads **off** on a fresh Windows 10 guest even with Defender on.
- The first network connection opens the "Networks: allow your PC to be discoverable" prompt and, through INetSim's
  fake page, an Edge window (a captive-portal check). Nothing answers them and neither blocks provisioning.
- Windows' own English service names contain "Antivirus", which the giveaway scan allows (see Names and giveaways).
- Not verified: a PowerShell sample on Windows 10 stalls the guest agent after the analyzer ends and the run loses
  its Sysmon and Defender events (see [M10 findings](../plans/m10-guest-proofs.md)). The CAPE tag follows the
  media: the profile's `cape.tag_rules` map the media's build to `win10` (from 10240) or `win11` (from 22000)
  next to the always-on `windows`, so a Windows 10 guest registers as `windows,win10`.

### Inputs (the Windows profile)

- **Installation media** in `./data/iso/`, mounted read-only into `cape`. The wizard lists what the scan
  finds: for each file, which profile recognised it and, for Windows, its editions, build and language. The
  scan mounts the image on a loop device and reads `sources/install.wim` with `wiminfo` (the `wimtools`
  package in the image): about 4.6 MiB read and a few hundredths of a second, with nothing extracted. (The
  first design extracted the 7 GB image, 6.4 s and 7 GiB of scratch; S0a showed that is unnecessary.)
  Microsoft's retail ISOs are UDF, which the loop mount handles. The container has only `/dev/loop-control`,
  so the scan makes the next free loop node itself, detaches in a `finally`, and clears mounts left by a
  killed service at start. There is no cache: a scan costs less than a lookup. Not an ISO, a truncated or
  damaged image and an image with no `install.wim` or `install.esd` are listed with a readable error. Not
  tested: a real Microsoft ESD, another language, a host without the `udf` module.
- **Edition:** any index of the image; Pro by default. **Product key:** optional, `XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`;
  installing without one works. **Language** is the image's own (an ISO carries one); the **keyboard layout**
  is a separate setting chosen from a table of 13 layouts (Polish Programmers and 214, US, UK, German,
  French, Spanish, Czech, Italian, Portuguese, Brazilian ABNT, Russian, Ukrainian).
- **Identity** (see [Names and giveaways](#names-and-giveaways)): the Windows account, the computer name and
  the password, each generated when left blank. **Resources:** vCPUs (2), RAM (4 GB) and disk (80 GB thin
  qcow2, 64 GB at least).
- **Options:** Defender (on), "make it look used" decoys (off), Sysmon (on).

### Build steps (an installer build)

Each step is shown with progress and a log tail; the pipeline is `preflight`, `fetch`, `define`, `install`,
`provision`, `tamper-off` (only when Defender is off), `symbols`, `snapshot`, `register`, and then the backend's
self-test. Steps are idempotent, so a failed build can be resumed at the step that failed or restarted from
the first.

1. **preflight:** `/dev/kvm` and the CPU flags, free space for disk + scratch (20 GB) + 20 GB reserve (the
   message gives the numbers), the media readable, a domain left by an earlier attempt of this very guest
   removed, the address not held by another guest.
2. **fetch:** downloads the pins of `manifest.sha256` (Python 3.11.9 32-bit, Pillow's Win32 wheel, Sysmon)
   into a cache, each checked against its hash; nothing unverified is kept.
3. **define:** the libvirt domain, from the profile's hardware block and the shared SMBIOS persona:
   - `host-passthrough` CPU with the `hypervisor` feature disabled and KVM state hidden, `migratable='on'`
     (an exposed `invtsc` blocks any memory save);
   - SMBIOS (system, baseboard, chassis, BIOS) with a Dell OptiPlex persona, a disk serial and a NIC MAC with a
     Dell prefix, all generated per guest; the patched QEMU covers BIOS, ACPI and device strings but not
     SMBIOS;
   - Q35, UEFI with Secure Boot (Microsoft keys), TPM 2.0 with its own state, SATA disk and e1000e NIC (no
     virtio drivers needed), two optical drives in install mode (the run-mode domain has none), VNC bound
     inside the container.
4. **install:** builds a disc holding `autounattend.xml` (rendered from `guest/profiles/windows/autounattend.xml.tpl`
   with the edition index, the optional key, the keyboard, the account and the computer name, XML-escaped) and
   the provisioning files, boots the installer with it as the second CD, sends Enter for the first 20 seconds
   (see the silent failures below), resets and retries up to three times if the disk is still empty, and waits
   for the guest to finish provisioning itself at first logon. The step may take up to 90 minutes; a build takes
   about 16 minutes.
5. **provision** (the guest's first-logon script, logged back to the build): static IP from the guest's
   record, gateway and DNS `.1`; Windows Update, UAC prompts, firewall (with port 8000 open), telemetry
   where the edition allows, sleep and hibernate and SmartScreen off; 32-bit Python 3.11.9 and Pillow; CAPE's
   `agent.py` as a scheduled task at logon with the highest privileges; the Defender policy keys when Defender
   is off; decoys and Sysmon when asked (Sysmon is checked by its running service and log entries). The host
   then copies the log off the guest and removes the installers; the working folder keeps the agent, the done
   marker and the log.
6. **tamper-off** (Defender off only): see Defender below.
7. **symbols** (never fails the build): makes the Volatility3 symbol file of the guest's kernel while the agent
   still answers; see "Symbols" under the memory analysis above.
8. **snapshot:** ACPI shutdown (never `virsh destroy`, which loses unflushed writes), boot the clean guest,
   wait for the agent on `:8000`, idle 60 s, then take the external disk-and-memory snapshot
   `tartarus-clean` and power off. Revert takes about 1.6 s.
9. **register:** the engine writes `guests.conf`, restarts `cape`, and checks `machines/list`. The guest is
   `testing`.
10. **self-test** (the backend's, on the new guest): see Self-test below.

### Clone steps

`[CLONE]` makes a new guest from a `ready` one in minutes instead of a full build: `preflight`, `copy`,
`define`, `reconfigure`, `tamper-off` or `defender-on` (by the Defender option), `symbols`, `snapshot`, `register`,
then the same self-test. `preflight`, `define`, `snapshot` and `register` are the build's own step files.

- **copy** takes the source's **base disk, never its snapshot**: the snapshot's memory image holds the
  emulated hardware's state and cannot be restored under a new identity. The base is found through the
  backing chain of the source's current disk (a revert leaves `win.<epoch>` on top and no `win-clean.qcow2`)
  and converted sparsely with `qemu-img convert`, with the nvram copied beside it. The source must be powered
  off; it is not written. A new swtpm state is created, never copied.
- **define** gives the copy a new UUID, MAC, SMBIOS and board and disk serials, the next free address and, with
  the Windows rules of a build, a new computer name (never the source's).
- **reconfigure** cold-boots the copy, finds it by its new MAC in libvirt's DHCP lease table (a source's
  base disk boots on DHCP, not on the static address it was given; an already-configured copy is found at its
  final address) and, through the agent's **64-bit** PowerShell (`C:/Windows/Sysnative/...`: the agent's own is
  32-bit and lacks `manage-bde` and the 64-bit registry view), sets the static address, the new computer name, a
  fresh `MachineGuid`, empties the event logs, adds the decoys if asked, and reboots; the IP-changing call is
  made asynchronously because it ends the agent's connection, and the host reads what it did from a log the
  script writes. It then checks the hostname, address and `MachineGuid` at the final address.
- **What a clone shares with its source:** the machine SID, the install date and ProductId, and what lived in
  the disk (the account and its profile folder, which is why the username is inherited and a different one needs a
  build). The hardware identity, which sandbox checks read, is new.
- What S0d settled: the crash-consistent copy cold-boots with no repair screen, activation or Secure Boot
  complaint; the fresh TPM is re-owned by Windows within about 45 s (no BitLocker key protector exists, so it
  cannot lock the clone out); the adapter keeps its name and GUID across the MAC change; the new name and
  address survive reboots and a snapshot revert. A clone takes about 5 minutes (convert 11 s, cold boot to agent
  53 s, reconfigure and reboot under 50 s, shutdown 7 s, boot 24 s, idle 60 s, snapshot 2 s, then the
  self-test).

### Names and giveaways

A sample must not recognise the sandbox by a name, so the username and computer name are the analyst's, or a
realistic random one (a first name; `DESKTOP-` or `LAPTOP-` and seven letters or digits) by default, and
nothing Tartarus puts in a guest carries the product's name.

- **Refused names.** The Windows rules (an account `[A-Za-z][A-Za-z0-9_-]{0,19}`, not `Administrator`, `Guest`,
  `DefaultAccount`, `SYSTEM` or `WDAGUtilityAccount`; a computer name of 1 to 15 letters, digits and hyphens, not
  all digits, `localhost` reserved) and a list of words that tell a sample what the machine is: `tartarus`,
  `sandbox`, `malware`, `virus` and `cuckoo` anywhere in the text; `cape`, `test`, `admin` and words starting
  `analy` only as a whole word or path component (`cape` is inside `landscape`). One list
  (`cape/guest_engine/giveaways.py`) serves the build, the clone, the generators and the guest-side scan.
  Words that are ordinary on a real machine but contain one of the first list (`antivirus`, which English
  Windows uses in its own Defender service names, "Microsoft Defender Antivirus Service") are listed as
  legitimate in the same file and removed from the text before it is searched, so `antivirus` passes while
  `myvirus` and `antivirus virus` do not.
- **Neutral names inside the guest.** The per-guest working folder is `C:\ProgramData\<8 random letters>`; the
  firewall rule, scheduled task, install-disc label and marker file, the first-logon description, the done marker
  and the log file take neutral names from one table (`names.json`: "Windows Remote Assistance Service" and
  similar). The install disc is ejected before the snapshot. The password is a random 16 characters unless
  chosen, kept in `guest.json`, shown on the card so the analyst can log into the desktop, and in plain text in
  the guest for autologon.
- **The gate.** A test scans every file the profile ships, case-insensitively, for the words (with a short
  allow-list: the sample's source, Microsoft's EICAR text, the adoption block), and the self-test runs the
  facts script inside the guest, which looks for them in the computer name, accounts, scheduled tasks,
  services, firewall rules, `Run` keys, installed programs and the top-level folders; any hit fails the build.
- **What this does not remove:** CAPE's own traces during a run (its analyzer folder in `%TEMP%`, the agent
  process and its `Server: CAPE Agent` header), the display adapter, timing. It removes the cheap checks, not
  all of them; the list is one file, so it grows as tells are found.

### Defender

Defender is a per-guest option, **on by default**, and the state is baked into the guest's snapshot, so
"Windows 11, Defender on" and "Windows 11, Defender off" are two guests and the analyst picks one at
submission. Left on, a sample meets Defender the way it would on a real machine; off suits samples Defender
would remove before they run or that behave differently when it is running. Several guests, rather than one,
settled the old question of choosing per submission.

- **Off is scripted.** With Tamper Protection on, the documented policy keys and `Set-MpPreference` are
  silently ignored (M0b), and `Set-MpPreference` stays useless while a policy key is present: policy wins, both
  ways. S0c found that one scripted click on Windows Security's Tamper Protection toggle (UI Automation through
  the agent, in the logged-in user's session) turns Tamper Protection off, that the policy keys `provision.ps1`
  already writes then take effect (real-time protection and behaviour monitoring off, a test file kept), and
  that the state survives a memory save and restore and a reboot.
- **The `tamper-off` step**, after provisioning and before the snapshot, so the state is in it, runs in the
  64-bit PowerShell through the agent: (1) write the Defender policy keys; (2) open
  `windowsdefender://threatsettings` (it opens only outside a monitored analysis, which a build is); (3) find
  the page's switches by toggle behaviour (every element with the UI Automation `TogglePattern`, because
  Windows 10 exposes them without an `AutomationId` and Windows 11 gives all five the same one), then the
  Tamper Protection switch among them by its known localized names (Polish, English), else the last switch,
  which Tamper Protection is on both versions; (4) switch it off and **verify with `IsTamperProtected = False`**,
  which is language-independent, rereading once; (5) make sure real-time protection is off; (6) **prove it by
  file, not by flag**: write the EICAR test string (two halves, joined at run time so no scanner on a dev machine
  quarantines the repo), require the file to survive, then run a quick scan over its folder and require it to
  survive again. One shared helper, `security-ui.ps1`, finds the window and the toggle; each script used to
  carry its own copy, and the first real run of `defender-on` found the lookup bug that `tamper-off` had
  already fixed.
- **The pause is only the fallback.** If the window or toggle cannot be found, the step first reads
  `IsTamperProtected`, the language-independent state it trusts anyway. Only when that is not already the
  wanted state (exit 10) does it print instructions and exit 75: the build is `paused`, the page shows them
  with the guest's desktop, and `[CONTINUE]` runs the step again. Because the step reads the state first when
  it cannot operate the window, a switch the analyst made by hand is accepted (`RESULT toggle_skipped=...`)
  and still verified by flag and by file: real-time protection is checked and the test file is written (or
  removed) as usual. A failed verification or proof (exit 20, 30) fails the build with the evidence. This path ran for real on Windows 10 (M10): with the switch lookup forced to find nothing the build paused with the instructions and the desktop, the analyst switched Tamper Protection off by hand, and `[CONTINUE]` finished the step (before the state was read first, the same sequence looped).
- **Defender on in a clone** of a Defender-off guest is the reverse step, `defender-on`: remove the policy
  keys, switch Tamper Protection on, require real-time protection and that the test file is removed. It
  passed on a real clone (`lab5` from the Defender-off `lab3`, 5.5 minutes, the toggle found by its Polish
  name).
- **Not run:** another UI language (the toggle's name, whether it is still the fifth), Windows Update or a
  later Defender platform update turning Tamper Protection back on, and "report what Defender did in an
  analysis", which touches the ingest and the normalisers and is outside the wizard.

### Self-test

A built guest stays `testing` until the backend runs the profile's benign sample on it **as an ordinary
analysis through Tartarus** (tag `self-test`, INetSim route, 60 s) and judges it (see
[backend](backend.md#guests)). The sample (`benign.c`) is compiled by mingw in the `cape` image, served by the
control service, and spawns a child process, writes a file, sets a registry value and resolves
`tartarus-selftest.example`. Judged:

- **from the analysis's own data:** a process (and its child), a file event, a registry event, a report, and the
  DNS lookup. The lookup is required but its **answer is not**: INetSim answers every lookup in the packet
  captures, while CAPE's report sometimes records `answers: []`, so a missing answer is reported, not failed.
  This is CAPE's reporting, not a Tartarus bug;
- **inside the guest,** by the profile's check step after restoring the snapshot: the facts script's
  `FACT` lines (the verdict keeps the hostname, the user and the three Defender flags), its `GIVEAWAY` lines (none allowed),
  and the Defender proof: the EICAR string is **removed within 15 s on a Defender-on guest and kept on a
  Defender-off one**. A mismatch fails the guest.

**Anti-VM tells (M7).** A run-mode domain has no optical drive, because an empty one is a tell. Guests built before
M7 keep their drives: their memory snapshot was taken with that hardware, and the domain is not redefined under it
(not tried, kept as a rule). A clone of such a guest is rendered from the current template and takes its own snapshot,
so cloning is the way to a guest without drives. Windows keeps a
device node and an `Enum\SCSI\CdRom` key for each drive the install saw, and a sample can still read them, so the
Windows profile's `agent.pre_snapshot` step, `remove-ghost-drives`, removes every non-present CD-ROM device before the
snapshot is taken; the removal survived a snapshot and a revert in the real-guest proofs. The facts script
(`guest-facts.ps1`) reports two giveaways: `optical drive` for a CD-ROM drive that is still present, and
`display adapter` for a display device from a hypervisor vendor (`PCI\VEN_1AF4`, `VEN_1B36`, `VEN_15AD`, `VEN_80EE`,
`VEN_1013`) or one whose `ConfigManagerErrorCode` is not 0. The inbox Basic Display Adapter and the QEMU standard VGA
(`PCI\VEN_1234&DEV_1111`) are reported as known tells, not giveaways, because every guest reads them, and `video.name`
is localised, so it is reported and never judged. These facts run in a new build's or clone's self-test, not in
`[RUN CHECKS]`.

A failed self-test ends the guest `failed`, unregistered from CAPE (which keeps the others), with the reasons
on its card; nothing else is disturbed. pafish, which the first design ran after the self-test as
information only, is not built.

### Restart and shutdown behaviour

A step runs in a process group of its own with a minimal environment (no token of the service), is killed
with its group at its timeout, and has its exit code read: 0 done, 75 waiting for the user, anything else
failed. `[RESUME]` runs a failed or paused build again from the step that stopped it, `[RESTART]` from the
first, `[CONTINUE]` carries on a paused one. When the control service is stopped mid-step, that step is
stopped (no process is left) and the build is `failed` with "resume it"; resuming then finished the build and
its self-test in a real run. Restarting the backend mid-build reattaches the build under a new job (see
[backend](backend.md#guests)). A resume of a clone's `reconfigure` never applies on top of an earlier run's
apply: that apply leaves a log in the guest, and the resumed step, finding it, waits for the reboot it announced and
checks the result against the identity the copy came with, which the first run saved in the build directory
(M6 saw a resume during the apply fail with "did not start its reboot within 90 s"; the M7 drills resumed 3 s after
an interruption and after a finished apply, and both clones reached `ready`). `[CANCEL BUILD]` stops the running
step's process group and ends the build `failed` with "the build was cancelled"; a paused build can be cancelled
too, the sequencer stays open, and the build stays resumable and its guest deletable. The request answers once the
step is gone, which can take about 15 s.

### Guest health (shown in the header and on the Guests page)

| Check | OK when |
|---|---|
| VM defined | libvirt domain exists |
| Snapshot | `tartarus-clean` exists |
| CAPE registration | the machine is listed by `apiv2/machines/list` |
| Agent | the snapshot is restored and the agent answers (on demand only: CAPE reverts the snapshot before every task, so checking before each analysis would do it twice; the guest is left off) |

The header dot is the aggregate of every guest's state: green when all are `ready`, amber when some are not
(for example `lab4 is building` or `lab6 is failed`), red when none is.

## Interactive desktop

- The analyst turns it on per submission (on by default). CAPE's `interactive=1` option keeps the
  analysis running until the timeout and injects the monitor into the desktop shell; with
  `nohuman=yes` (passed together) CAPE's mouse mover and dialog closer are switched off, so the
  analyst stays in control.
- The backend opens a Guacamole VNC connection through `guacd` and tunnels it over
  `WS /ws/analyses/{id}/desktop`. The GUI renders it with `guacamole-common-js`, with keyboard
  and mouse enabled. The same tunnel serves a guest's screen while a build is at a step that shows
  one (`WS /ws/guests/{name}/desktop`, see [backend](backend.md#ws-wsguestsnamedesktop)); a build has no
  monitor in the guest.
- Available only while the task is `running`. When the task stops, the panel switches to the
  last screenshot.
- Clipboard sync between the host and the guest is **disabled**, both ways. Drag-and-drop and
  file transfer are disabled too.

### Store apps are not monitored in an interactive analysis, and Windows Security cannot be used

Opening a text file from the desktop starts the packaged Windows 11 Notepad
(`C:\Program Files\WindowsApps\Microsoft.WindowsNotepad_...\Notepad.exe`; `HKCU\...\FileExts\.txt\UserChoice`
names it, so even the legacy `notepad.exe` ends up there). With CAPE's monitor injected the process
stops after loading `AppxDeploymentClient` (a stack dump shows the main thread and two others blocked
in ntdll lock waits): 7 threads instead of about 20, no window, no taskbar button, every time. The same app opens normally without the monitor.

- **Fix:** in an interactive analysis the analyzer does not inject into a process whose image is
  under `\Program Files\WindowsApps\` (the image path CAPE reads is an NT path, so the match is on
  the part after the volume). It logs `Interactive mode: not injecting into packaged app ...`; the
  process is not counted as injected and is not waited for. The patch is applied to the pinned
  analyzer when the `cape` image is built.
- **Not skipped:** non-interactive analyses, and any analysis whose package is `msix`, because that
  package runs the sample itself as a Store app.
- **Cost:** a Store app the analyst opens is not in the process tree or the event stream, and neither
  are its children. Processes whose image is outside `WindowsApps` are still injected, including
  `backgroundTaskHost.exe` (`System32`), which also fails to initialise the monitor; that one is not
  addressed and does not block anything visible.
- **Windows Security cannot be opened from the desktop of a monitored interactive run** (S0c). Opened from
  the Start menu or through the agent, `SecHealthUI.exe` runs and answers but **never draws a window**; the
  shell then froze (the Start menu would not open) and ending the run hung in process termination for about
  four minutes, until the guest was shut off. The analyzer logged that it was not injecting into the packaged
  app, so the M1 patch skips the injection and the app still does not show; the monitor in the surrounding
  processes is the likely cause (not proven). The same page opens normally in a guest restored from a snapshot
  outside CAPE, with no monitor, which is why the scripted Tamper Protection step works at build time. Not
  fixed: do not use Windows Security in a monitored run.
- **Why not a monitor option:** `zerohook=1` (no hooks except the essential two) lets Notepad open
  with the monitor injected, so the hooks are what stops it, but it also leaves the sample
  unmonitored. No option that keeps the hooks was found (only `zerohook=1` was tried, on one run), so
  `INTERACTIVE_OPTIONS` stays `interactive=1,nohuman=yes`.

### The DCOM launcher is not monitored in an interactive analysis

The monitor in Explorer reports COM activity (Windows Terminal, Edge, Store apps) and CAPE's analyzer answers by
injecting `svchost.exe -k DcomLaunch`. The monitor stays loaded there when the analyzer exits, and from then on every
new process the guest agent starts hangs (even `cmd /c echo hi`; `/status` and `/store` still answer, slowly). The
host-side event-log export is such a process, so it waited out its read timeouts (120 s Sysmon, 30 s Defender): the run
reported 2.5 minutes late with no `sysmon.xml` and a `missing_exports` note (spike P3 finding F7, task 3.8).

- **Fix:** in an interactive analysis the analyzer counts the launcher as monitored already (`MONITORED_DCOM`, the
  switch its interop, WMI and BITS handlers test), so it never injects it. Measured, solo on one guest, ended by
  `/finish` 30 to 60 s into the run: with the launcher injected 4 of 4 runs hung (159 to 161 s from `/finish` to `done`,
  no `sysmon.xml`; a fifth, ended before the launcher was injected, did not); without it 5 of 5 took 20 s and exported.
- **Cost:** a process that COM activation starts in an interactive analysis is not followed through the launcher, and
  the launcher's own API calls are not in the event stream. Non-interactive analyses are unchanged.

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
