# G1: guest network isolation (F2, F3, F5, F9 of C2; F2 of C3)

Status: DONE (steps 0 to 4). Nothing committed.

Initial state of the stack: cape/backend/frontend/opensearch/postgres up and healthy; `virsh list --all`:
lab1, w10-q, win2 all `shut off`. Restore to that at the end (win2 is never touched).

## Log

- Done: read C2 (F2, F3, F5, F9), C3 F2, verify-isolation.sh and its test, entrypoint, supervisord, wait-then-exec, rooter.
- Done: STEP 0 baseline (below).
- Done: design + code for steps 1-3 in one Tartarus-owned nftables ruleset (below), unit-tested
  (cape/tests/test_guest_firewall*.py, 51 tests, red first: ImportError, then green), validated by hand on the running container
  with `nft -c`/apply (probes in raw/internet/inetsim/spoof all as intended).
- Done: wiring (entrypoint `guest-firewall init`, `/etc/libvirt/hooks/qemu`, Dockerfile, Makefile lint list); cape rebuilt with
  `docker compose up -d --build cape` (healthy after ~15 s). Hook verified live (below).
- Done: scripts/verify-isolation.sh rewrite + scripts/tests/test_verify_isolation.sh (24 tests, mutation-checked), scripts/lib/isolation-probe.ps1,
  scripts/lib/rooter-route.py. Two bugs of the script found only by the real run and given tests: `compose exec -T` ate the
  stdin of the catalogue loop (controls silently skipped after the first target), and `head -c` lost the reply of servers that keep
  the connection open.
- Done: make lint, make test-cape (2139 passed), make test-scripts, make smoke all green; verify-isolation green; negative proof done.
- Done: STEP 4: real analyses through POST /api/analyses (benign.exe + random tail): lab1/inetsim 480 done, 754 events, 6 DNS rows,
  2 HTTP, simulated; w10-q/inetsim 481 done, 576 events, DNS answered 192.168.150.1 (INetSim), 1 HTTP; lab1/internet 482 done,
  763 events, simulated false. The rooter rules captured during the real inetsim and internet tasks equal what
  scripts/lib/rooter-route.py produces. The three analyses and a failed one (479) were deleted again.
- Done: guests stopped (`virsh list --all`: lab1, w10-q, win2 shut off), host canary on :18080 killed, stack up.
- Next: nothing; review the diff and commit by explicit path.

Note for whoever runs this next: if a guest is left RUNNING when CAPE tries to start it, CAPE marks the machine dead and drops it
from its pool (`machines/list` empty, tasks fail with 'no matching machine'); `supervisorctl restart cape` in the container
re-registers it. Power guests off (`virsh destroy`) after manual probes.

Unverified: a clone/build (boots on its source's address or a DHCP pool address; the design lets both through, not run here),
IPv6 from a guest (dropped by rule, not probed), DHCP discovery from 0.0.0.0 on a cold boot, OpenSearch (not reachable from the cape container
either, so the probe is skipped with an INFO line).

## Facts found in the container (not from the report)

- iptables is the nf_tables variant (1.8.10); `nft` 1.0.9 and `ebtables`/`arptables` exist; br_netfilter is not loaded
  (no /proc/sys/net/bridge), so bridged frames never reach iptables.
- CAPE's `cuckoo.py` calls `rooter("cleanup_rooter")` at every start (lib/cuckoo/core/startup.py:743) and the rooter itself
  at start; both re-insert `-I FORWARD -j CAPE_REJECTED_SEGMENTS` then `-I FORWARD -j CAPE_ACCEPTED_SEGMENTS`, so any
  fix that lives in the iptables FORWARD order has to be re-asserted after every cape restart.
- Compose subnets: internal 172.19/16, control 172.18/16 (internal), web 172.21/16, db 172.23/16 (internal),
  search 172.22/16 (internal), cape-db 172.20/16 (internal). cape is on internal (eth2), control (eth1), cape-db (eth0).

## STEP 0: baseline (before any change)

Method. Guests started with `virsh snapshot-revert <g> tartarus-clean` (as verify-isolation does). The routes CAPE
sets per task were replayed through CAPE's own rooter socket with the exact calls `AnalysisManager.route_network`
makes (`inetsim`: `inetsim_enable` + `libvirt_fwo_enable` + `forward_enable tt-guest tt-guest`; `internet`:
`libvirt_fwo_enable`, `forward_enable tt-guest eth2`, `forward_reject_enable` with the configured segments,
`srcroute_enable`; `none`: `drop_enable`). `raw` = no rooter rules for the guest (the seconds between revert and
`route_network()`, guest builds, the self-test). Probes ran inside the guest through its agent with
`scripts/lib/isolation-probe.ps1`: connect, send a protocol-specific payload, and require a marker from the REAL
service in the reply. A bare connect proves nothing on the inetsim route: the rooter DNATs every TCP SYN to INetSim's
dummy listener, which accepts any port (measured: every port "connected" until markers were added).
Host side canary: `python3 -m http.server 18080 --bind 0.0.0.0` on the docker host (stopped at the end).

Result per probe, guest lab1 (w10-q identical in every column; `yes` = a real answer from the target came back):

| probe | raw | none | inetsim | internet |
|---|---|---|---|---|
| gateway 192.168.150.1 :53 / :80 / :2042 | yes/yes/yes | no/no/yes | yes/yes/yes | yes/yes/yes |
| OpenSearch 172.22.0.2:9200 | no | no | no | no (cape is not on tartarus-search; Docker's bridge isolation holds) |
| Postgres 172.23.0.2 / 172.20.0.2 :5432 | no | no | no | no (eth0 is not the route's egress interface) |
| backend 172.19.0.3:8000 | no | no | no | **yes** |
| CAPE API/web 172.19.0.2:8000 (cape's own address) | **yes** | no | no | **yes** |
| guacd 172.19.0.2:4822 | **yes** | no | no | **yes** |
| guest-control 172.18.0.2:8002 | **yes** | no | no | **yes** |
| other guest agent, direct | no | no | no | no |
| docker host 172.19.0.1:18080 | no | no | no | **yes** |
| LAN host 192.168.0.110:18080 | no | no | no | **yes** |
| LAN router 192.168.0.1:80 | no | no | no | **yes** |
| internet 1.1.1.1:80 | no | no | no | yes (intended) |

Confirmed or refuted (by probe):
- F2 confirmed: with `internet` the guest reaches the backend, the docker host, a LAN host and the LAN router.
  Cause confirmed by experiment: moving `-j CAPE_REJECTED_SEGMENTS` above `-j CAPE_ACCEPTED_SEGMENTS` by hand
  made backend, docker host, LAN host and router `no` while 1.1.1.1 stayed `yes` (then restored). The report's
  claim that OpenSearch is reachable is refuted for this layout: 172.22.0.2 is not reachable (the guest egresses
  through eth2 only and Docker drops bridge-to-bridge forwarding); the backend and the docker host are.
- F3/F5 confirmed with the guest's own address in `raw` and `internet`: INPUT is ACCEPT for everything arriving
  on tt-guest, so cape's web/API, guacd (unauthenticated) and guest-control (token-protected) answer.
  Confirmed by spoofing on the `inetsim` route (guest address added with
  `netsh interface ipv4 add address Ethernet 192.168.150.200`, curl `--interface 192.168.150.200`): CAPE web/API
  `172.19.0.2:8000` -> HTTP 200 and guest-control `172.18.0.2:8002` -> HTTP 401 reached, where the guest's own
  address got DNAT'd to INetSim. The rooter's per-IP rules do not cover an alternate address.
- F9 confirmed and worse than reported: with `netsh interface ipv4 add neighbors Ethernet <other> 52-54-00-5a-01-53`
  (the gateway MAC) on BOTH guests, each reached the other's agent (`CAPE Agent!` in both directions) in `raw` and
  in `internet`. Direct L2 stays blocked by the isolated ports (the probe `other guest agent` = no).
  Inetsim route: its DNAT catches the TCP, so the report's one-way UDP path is the remaining case there.
- INPUT, rooter: the rooter's INPUT rules are `--source <guest ip>` only (inetsim: drop tcp/22; drop route: accepts
  to the guest), confirmed in `iptables -S`.
Guests restored after the probes: alternate address and neighbour entries removed; reverted to the snapshot again
before the next step.

## Design (steps 1 to 3)

One nftables ruleset in tables of their own (`inet tartarus_guest`, `bridge tartarus_guest`), rendered by
`cape/guest_engine/firewall.py`, applied by `cape/bin/guest-firewall`. Why nftables and not iptables ordering:
`cuckoo.py` calls the rooter's `cleanup_rooter` at EVERY start (startup.py:743) and it re-inserts the two FORWARD
jumps accept-first, so an iptables fix would have to be re-asserted after every cape restart. A base chain at
priority -10 (inet) / -200 (bridge) runs before iptables' filter chains whatever order they are in, and iptables-restore
never touches another table. No upstream CAPE file is patched.
- inet input: from `tt-guest` only `ip daddr <gateway>` and DHCP discovery (255.255.255.255:67) pass, the rest is dropped.
- inet forward: from `tt-guest`, `oifname tt-guest` drop (F9 hairpin through the gateway MAC), `ip daddr @unreachable`
  reject (RFC1918, link-local, CGNAT, loopback, multicast/reserved, plus every network and the default gateway read
  from `ip -4 route` at container start, so a compose network outside RFC1918 is covered), IPv6 drop.
- bridge prerouting (L2, native, no br_netfilter needed): a frame must come from a port whose (tap, MAC) is bound; ARP sender MAC
  must be the port's; source IPv4 must lie in the guest subnet; the gateway's address and the registered address of every
  RUNNING guest may be used only by the port (tap, MAC, ip) bound to that guest. Everything else (IPv6, VLAN, unknown
  ethertypes) is dropped. Chosen over libvirt's nwfilter `clean-traffic`: it would need `<filterref>` in every domain
  and every snapshot copy of it (a memory-snapshot revert starts the snapshot's copy of the XML) plus the guest address
  at define time, and clones boot with their SOURCE's address before `reconfigure`, which a per-domain IP parameter
  would break. Here an address of a guest that is not running is not protected, so a clone may use it.
- Binding: the libvirt qemu hook (`/etc/libvirt/hooks/qemu`, from `cape/libvirt/qemu-hook`) runs `guest-firewall hook`
  on `started` (records the tap + MAC from the domain XML on stdin) and `stopped`/`release` (forgets); the address
  comes from the guest registry (`/var/lib/libvirt/tartarus/guests`). The hook does not call libvirt (it holds the
  domain). The entrypoint runs `guest-firewall init` before supervisord (set -e: a failure stops the container).
  Until a guest's hook ran its frames are dropped (fail closed).

## Evidence after the rebuild (real stack, both guests running)

- `docker exec tartarus-cape nft list table inet tartarus_guest` shows input/forward chains and the unreachable set;
  `/run/tartarus/guest-firewall/policy.json` = gateway 192.168.150.1, networks 172.19.0.1/32, 172.18/16, 172.19/16, 172.20/16.
- Hook: `virsh snapshot-revert lab1 tartarus-clean` (shut off -> running) created `ports/lab1.json` {tap vnet0}; a second revert of
  the RUNNING guest moved it to vnet1 and the ledger followed (stopped/release forgot the old tap, started recorded the new
  one, in that order); w10-q on vnet2; both agents answered with the bridge table in place.
- Probe matrix (same probes as the baseline, both guests, routes raw/none/inetsim/internet): everything `no` except the
  gateway (`raw`, `inetsim`, `internet`: dns/http/resultserver `yes`; `none`: resultserver only) and, on `internet`,
  1.1.1.1:80 `yes`. Backend, CAPE web/API, guacd, guest-control, docker host, LAN host and LAN router are `no` on `internet`
  too. (Raw output kept in the scratchpad; the final proof is verify-isolation.sh below.)

## STEP 1-3 proof: `make verify-isolation GUESTS="lab1 w10-q"` (real stack)

Green, exit 0, 13 probes per scenario (opensearch skipped: it is on a network the cape container is not on, so the
cape container cannot reach it either and a "no" from a guest would prove nothing):
raw/none/inetsim/internet for each guest, each guest from an invented address (.250), each guest claiming the other's address,
and lab1<->w10-q through the gateway MAC on raw and internet, both directions. Output kept at
`<scratchpad>/vi3.log` (copied below in the final report).

Negative proof (the script can fail): `docker compose exec -T cape nft delete table inet tartarus_guest` and `... table bridge
tartarus_guest`, then the same command exited 1 with: raw: cape-web, guacd, guest-control yes; internet: + backend, docker-host,
lan-host yes (F2); invented address: cape-web/guacd/guest-control yes (F3/F5); claiming the other's address: gateway-dns... and
on w10-q the whole catalogue yes; hairpin raw and internet: other-guest-agent and ping yes in both directions (F9).
Restored with `guest-firewall hook <dom> started` for both running domains (tables back, ledger intact).
Positive-control note: the catalogue probes the real service with a marker, so INetSim's catch-all listener cannot pass for it.
