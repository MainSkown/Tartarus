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
decisions before M1: libvirt's TCP endpoint has no authentication, and the guest's SMBIOS still
says QEMU.

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
1. libvirtd and virtlogd run; `virsh list` works; libvirt also answers on TCP `16509` to another
   container on the internal network (the backend's future `qemu+tcp://cape/system` connection).
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

Needs a Windows 10 or 11 ISO. Decided: the user downloads a free evaluation ISO from Microsoft's
Evaluation Center into `./data/iso` (git-ignored). Pick Windows 10 or 11 Enterprise, 64-bit,
English (US), as an ISO rather than a VHD. CAPE's own docs name Windows 10 and Windows 11 23H2 as
the preferred guests, so an older build is the safer pick over the newest. Evaluation licences
expire after about 90 days, which is fine for a spike and is why the wizard also accepts a
user's own licensed ISO. This stage takes the hand-built guest the wizard will later automate.

- Install Windows in the guest by hand, add CAPE's agent, take the clean snapshot, register it.
- Run a benign test sample through CAPE and confirm: capemon's BSON logs appear in
  `storage/analyses/<id>/logs/` on the shared volume while it runs, `report.json` appears after,
  and the `callback` reporting module reaches a listener on the internal network.
- Note exactly which steps were manual, since each one is a step the guest-build wizard (M6) has
  to automate.

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
