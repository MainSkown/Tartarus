# Plan: M0, the CAPE container spike

Settles the biggest unknown in the design: can CAPE, libvirt/QEMU, CAPE's network rooter, INetSim
and Guacamole all run inside one privileged Ubuntu container, with the Windows guest on KVM? The
fallback if not (libvirt on the host) would tie Tartarus to Ubuntu hosts, so this is answered
before any feature depends on it. See [cape-integration](../specs/cape-integration.md).

Rated Opus-tier under rule 5 of [.claude/CLAUDE.md](../../.claude/CLAUDE.md): real ambiguity, and
a subtly wrong network or isolation setup costs a lot to find later. The spike is infrastructure,
so "test-first" means each acceptance check is a script that fails before the image can pass it.

## Stage M0a: the container, with no Windows involved

**Result: passed.** All seven checks pass (`make verify-cape`: 28 checks, about 100 seconds, run
independently twice with identical results), so the host-libvirt fallback is not needed. What was
built, what differed from the spec and what is still open is in
[cape-integration](../specs/cape-integration.md#findings-that-need-action). Two findings need
decisions before M1: libvirt's TCP endpoint had no authentication (now switched off until the
guest wizard needs it), and the guest's SMBIOS still said QEMU (closed by M0b).

Needs nothing from the user. A throwaway Linux guest stands in for Windows, so the whole host side
is proven independently.

**Deliverables**
- `cape/` with the Dockerfile (Ubuntu 24.04, CAPE pinned to a commit via `CAPE_REF`, QEMU/SeaBIOS
  built by CAPE's `kvm-qemu.sh`), a supervisord config, an entrypoint, and the generated CAPE
  config templates described in [cape-integration](../specs/cape-integration.md).
- A `cape` service in `docker-compose.yml`: privileged, `/dev/kvm`, its own network namespace, no
  published ports, on `tartarus-internal`, with `cape-storage` and `guest-images` volumes.
- `scripts/verify-cape.sh` and its tests, written first.

**Acceptance checks** (each inside the running container, from the host via `docker compose exec`)
1. libvirtd and virtlogd run; `virsh list` works. (As first written this also required libvirt to
   answer on TCP `16509` to another container; M0a showed that is unsafe, and the check now
   requires the opposite: nothing listens, and another container is refused.)
2. KVM acceleration works: `virsh capabilities` lists `kvm`, and a tiny Linux guest boots with it.
3. The bridge `tt-guest` (192.168.150.1/24) exists only in the container's namespace; the guest
   gets an address on it.
4. CAPE's rooter applies a route's iptables rules in the container's namespace, and the host's
   own rules and interfaces are unchanged afterwards.
5. INetSim answers DNS and HTTP for the guest; guacd runs and reaches the guest's VNC display.
6. CAPE's `cape`, `cape-processor` and `cape-web` start; `apiv2/cuckoo/status/` answers with the
   token auth on; it uses the `cape` Postgres database; no Mongo anywhere.
7. Stopping the container leaves nothing behind on the host (bridges, iptables rules, processes).

**Exit:** all seven pass, or a written finding that names what can't work and why, with the
fallback's cost. Either answer closes the question.

## Stage M0b: a real Windows analysis

**Result: passed (2026-10-13).** Checks 8 to 12 pass, run four times by the agent and once
independently by the planner (`make verify-guest`: 12 passed, 0 failed, a fresh task through to a
finished report with the callback received). **capemon works on Windows 11 build 26200**, so no
fallback image is needed. The unattended build takes about 13.6 minutes. Defender's Tamper
Protection cannot be turned off by script, so it stays a manual wizard step. The full findings,
including the silent Setup failures the wizard must handle, are in
[cape-integration](../specs/cape-integration.md#findings-from-m0b-the-windows-11-guest).

**Where things are left.** The working guest lives in the Docker volumes `guest-images` (22.5 GB),
`cape-storage` and `pg-data`; all containers are stopped. The git-ignored `.env` holds their
passwords and must not be regenerated, because the Postgres volume keeps the first password. To
use it again: `docker compose up -d`, then `make verify-guest`. To rebuild the
guest from nothing: `make build-guest`.

The ISO is the user's own `Win11_25H2_Polish_x64_v2.iso` in `./data/iso`: genuine Microsoft retail
media, build 26200 (Windows 11 25H2), pl-PL only, x64, eight consumer editions. Use **Windows 11
Pro** (image index 5, edition ID `Professional`), installed without a product key.

Two risks to settle here, because neither is covered by CAPE's docs:
- CAPE names Windows 10 and Windows 11 **23H2** as its preferred guests and says nothing about
  24H2 or 25H2 (build 26100/26200). Whether capemon hooks and CAPE's agent work on 26200 is
  exactly what this stage answers. If they don't, that is a finding, not something to patch
  around: the fallbacks are Windows 10 Enterprise LTSC 2021 (official evaluation ISO, no TPM)
  or a 23H2 image.
- Windows 11 setup requires a TPM 2.0 and Secure Boot, so the guest needs an emulated TPM
  (`swtpm`) and Secure Boot firmware, neither of which the M0a image has yet.

Install by script, not by clicking: an answer file on a second ISO (`autounattend.xml`, which
Windows Setup reads from removable media) plus provisioning scripts. That is what the wizard has
to do anyway, so the scripts become its seed rather than throwaway work.

**Deliverables**
- `guest/`: the libvirt domain template, the answer file and the provisioning scripts, as the
  seed of the wizard. Nothing from Microsoft or any large binary is committed; downloaded
  installers (32-bit Python, Pillow) are pinned by sha256 in a manifest.
- The `cape` image gains `swtpm`, Secure Boot firmware, and a way to build the answer-file ISO;
  `./data/iso` is mounted into it read-only.
- The guest's domain sets realistic `<sysinfo>` (closing the SMBIOS finding from M0a), a
  real-vendor MAC, a hidden hypervisor bit, a TPM 2.0, 2 vCPUs, 4 GB RAM and an 80 GB thin disk,
  with the VNC display bound inside the container only.

**Acceptance checks**
8. Windows 11 Pro installs unattended from the answer file, with the machine reachable at
   `192.168.150.10` and CAPE's agent answering on port 8000 from inside the container.
9. A running (memory) snapshot named `tartarus-clean` exists, and the guest is registered with
   CAPE: `apiv2/machines/list` shows it.
10. A benign test sample (built with mingw: starts a child process, writes a file, sets a
    registry value, resolves a name) submitted through `apiv2` runs to completion. capemon's
    BSON logs appear in `storage/analyses/<id>/logs/` while it runs, `report.json` appears after,
    and the `callback` reporting module reaches a listener on the internal network.
11. The ResultServer listens on `192.168.150.1:2042` while a guest is registered.
12. Recreating the container (without deleting volumes) keeps the domain, the snapshot and the
    registration.

**Exit:** all five pass, or a written finding that names what can't work and why. A failure of
check 10 on build 26200 specifically (hooks not loading, agent crashing) is a finding to report
with the evidence, and the decision on a fallback image is the planner's. Also record exactly
which steps could not be scripted: each is a step the wizard (M6) cannot automate either, and
Defender's Tamper Protection is the likeliest (open question 5 in
[tartarus-v1](../features/tartarus-v1.md)).

## Risks

| Risk | If it happens |
|---|---|
| `kvm-qemu.sh` builds QEMU from source: long and heavy | Split into a cached build stage, so only CAPE changes rebuild |
| CAPE's installers assume systemd, sudo and a full host | Run its steps by hand in the Dockerfile; supervisord replaces systemd |
| Rooter or libvirt need more than the container allows | Record exactly which capability, then decide between granting it and the fallback |
| Anti-VM patches don't survive the container build | Check the patched strings from inside a guest |

## Out of scope

The backend collector and report ingester (M1 and M2), the guest-build wizard (M6), and any
Tartarus UI for the guest.
