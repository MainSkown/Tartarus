# Fake LAN Step 2 notes: guest firewall, iptables accepts, routes

Resume file for an interrupted run (done / running / next). Scratch scripts live in
`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/3a2793e9-cb27-4633-8b90-6ad6ccbce585/scratchpad/step2/`
(`rig.sh`, `drive.py`, `checks.sh`, `probe.py`, `listener.py`, `rooter_rig.py`); they are throwaway, the evidence is below.
Baseline of the live stack before the run: `tables.before` (`nft list tables` in cape) and `ps.before` there.

## Done
- Sub-step 0: golden strings captured from the UNCHANGED `render_ruleset` (git showed `firewall.py` unmodified):
  `cape/tests/fixtures/guest_firewall_running.nft` (sha256 7f21745d...) and `guest_firewall_idle.nft` (0741eb7f...).
  Two tests in `test_guest_firewall.py` compare `render_ruleset` with them byte for byte.
- Sub-step 1 (tests first, seen failing with `ModuleNotFoundError`) and 2 (implementation):
  `guest_engine/lan_firewall.py` (new), `guest_engine/nft_text.py` (new: `nft_set`, `nft_chain`, `checked_address` moved out of
  `firewall.py` so `lan_firewall.py` need not import `firewall.py`; `firewall.py` still has the names, `egress.py` is unchanged),
  `firewall.py`, `bin/guest-firewall` (hook and init need the LAN ledger, otherwise a hook event would drop every session).
- Sub-step 3: `nft -c` in the cape image: PASS (below).
- Sub-step 4: replica rig, every route: results below.
- Sub-step 5: whole suite and lint: below.

- Sub-step 6: re-check from a clean state (rig destroyed and rebuilt, `checks.sh raw` and `checks.sh inetsim` run again: 34 PASS and
  0 FAIL each) and the golden tests plus the whole suite re-run after the last code edit (a rename and a docstring).
- Sub-step 7: cleanup done (below).

## Running
- nothing

## Next
- the planner reads the diff; Step 3 calls `GuestFirewall.open_lan_session` / `close_lan_session` (see "Interface for Step 3").

## Decisions
- **Module split.** `lan_firewall.py` (sessions, ledger, nft fragments, iptables/route/table reconcile) is a leaf: it imports
  `nft_text.py`, not `firewall.py`. `firewall.py` splices `LanFragments` into its two tables with no condition (all fields are empty
  without a session, so the golden string stays byte-identical).
- **Which values are validated, and where.** `LanTarget`/`LanSession` validate in `__post_init__` (IPv4 address as `str`, port an
  `int` 1-65535 and not a `bool`, key `[A-Za-z0-9][A-Za-z0-9-]{0,63}`); `fragments_for` validates again (frozen dataclasses can be
  bypassed with `object.__setattr__`) and then `check_fits(session, subnet)`: every target must lie inside `block_of(policy.subnet)`
  and the guest must be inside the subnet and outside the block. The last check is not in the brief and matters: without it a session
  naming `172.19.0.2` (CAPE's web) would put a guest-to-container pair into the input chain.
- **Ledger.** `LanLedger(directory)`, one `<key>.json` per session, `write_atomically`, unreadable or invalid files skipped (that
  session stays closed), a file whose key is not its name is skipped. In cape it is `/run/tartarus/guest-firewall/lan/`
  (`Paths.lan_sessions` in `bin/guest-firewall`), next to `ports/`.
- **`initialise()` clears the LAN ledger.** A session belongs to a `lan-sim` daemon and a backend analysis that died with the container;
  Step 3 closes leftover sessions at `guest-control` start anyway, and the backend opens a fresh one per analysis (fail closed).
  The same `apply()` then removes our iptables rules, routes and tables. Tested (`test_initialising_forgets_...`, and in the command
  test `test_init_closes_every_session_a_dead_container_left_...`). Consequence: "a reboot of the container reconstructs it from the
  ledger" holds for a hook event and a plain `apply()`, not for `init`.
- **No LAN ledger given (the default) means nothing but `nft -f` runs**, exactly the old calls: the existing tests and any caller that
  does not know about the fake LAN are unchanged. With a ledger every `apply()` also runs `nft list tables`, `iptables -w 5 -S OUTPUT`,
  `iptables -w 5 -S INPUT` and `ip -4 -o route show table local proto 77` (none of them creates anything: checked on a pristine
  container).
- **Order inside `apply()`.** nft first (one transaction: the two tables of ours are replaced together with `tartarus_guest`), then
  the reconcile of iptables and routes. Closing therefore closes the nft door first; opening opens it first and the iptables accepts
  and routes follow within the same call. If nft refuses, iptables and routes are not touched (tested).
- **Tables of ours:** `ip tartarus_lan_raw` (priority -300, `notrack` for `iifname "tt-guest" ip saddr . ip daddr @lan_pairs` in
  prerouting and `oifname "tt-guest" ip daddr . ip saddr @lan_pairs` in output: the output rule is by *pair* where the prototype
  `notrack.nft` used the set of fake hosts) and `ip tartarus_lan_ttl` (`type route hook output priority -150`, `ip ttl set 128`).
  When a session exists both are replaced by the `table X / delete table X / table X { ... }` idiom in the same file; when none
  exists the file is untouched (byte-identical) and `reconcile` lists `nft list tables` and runs `nft delete table ip X` for ours.
- **iptables:** per guest *address* (two sessions of one guest share the rules; closing one keeps them), exactly what `iptables -S`
  prints (`-d <guest>/32 -m iprange --src-range A-B -m comment --comment tartarus-lan -j ACCEPT` in OUTPUT, `-s <guest>/32 -m iprange
  --dst-range A-B ...` in INPUT), compared token by token, so a listing equals the wanted rule and a second apply changes nothing. A
  rule with our comment that is not wanted (or is duplicated) is deleted with the text iptables listed; a rule without our comment is
  never read as ours; the rooter's (`CAPE-rooter`) are never touched. Inserted with `-I <chain> 1`; later `-A` by the rooter stay
  behind ours. Commands use `-w 5` (wait for the xtables lock).
- **Routes:** `ip route replace local <addr>/32 dev lo table local proto 77`; listed with `ip -4 -o route show table local proto 77`,
  so only routes of protocol **77** are ever read or deleted. 77 is not in the image's `rt_protos` and no daemon uses it. Caveat:
  `replace` of a /32 that already exists with another protocol would re-mark it as ours; the block addresses carry no kernel route.
- **Bridge rules** are the prototype's (`firewall-sets.diff`), placed: ARP rules right after the port-MAC check (before the
  `0.0.0.0` accept and the protected/bound accept), IP rules right after the DHCP accept. No new `accept` appears in the bridge table
  (test compares the accept lines with and without sessions).
- **A session whose guest is not a registered running guest is applied anyway**: the firewall binds ports by running domain, so an
  address without a port is simply unused. Same for a target address with no listener.
- **Fail closed in `open_lan_session`:** an invalid session raises `ValueError` before anything is recorded or run; a failure while
  applying (nft, iptables or ip) forgets the key and applies again best-effort before re-raising, so nothing stays open.
- **No `Runner` change:** a missing program raises `MediaProblem` (as for nft today); `guest-firewall`'s `main` catches
  `OSError/ValueError/RuntimeError` only, so that path ends as a traceback with exit 1, as before.

## Interface for Step 3

    LanTarget(address: str, tcp_ports: tuple[int, ...])
    LanSession(key: str, guest_address: str, targets: tuple[LanTarget, ...])
    LanLedger(directory: Path)            # record(session) / forget(key) / clear() / sessions()
    GuestFirewall(policy, ledger, registry, runner, rules_file, *, lan_ledger: LanLedger | None = None)
        .open_lan_session(session)        # ValueError (invalid for the policy) or RuntimeError; nothing stays open
        .close_lan_session(key)           # idempotent
    render_ruleset(policy, ports, addresses, lan_sessions=())

**Locking, not solved here:** `bin/guest-firewall` takes `flock(state/lock)` around `init` and `hook`. `guest-control` runs in another
process; if it calls `open_lan_session` directly it must take the same `flock` (or shell out to a `guest-firewall` subcommand, which
does not exist yet), otherwise a hook event and an open can interleave their ledger writes and applies. Step 3 should decide.

## Check 1: unit tests (written first, seen failing)

`cape/tests/test_lan_firewall.py` (780 lines, 111 cases passing, 3 skipped) and additions to `test_guest_firewall.py` (the two golden tests) and
`test_guest_firewall_command.py` (3 tests; its `Programs` now routes to `FakeContainer` from `test_lan_firewall.py`, which also answers
`iptables`, `ip` and `nft list/delete`). Covered: zero, one and two sessions; two guests with different targets (A's pairs never
allow B, in both directions); every invalid value (newline, `;`, `}`, `}\ndelete table ...`, a range, an int instead of a string, port
0, -1, 65536, 70000, `True`, `"445"`, `445.0`, `None`) refused at construction and at render; a target outside the block and a guest
inside it or outside the subnet refused; bridge rules have no new `accept` (the accept lines are identical with and without sessions)
and the block rules sit before the accepts that would end the checks; ledger round trip, one file per key, replace, forget twice,
seven kinds of unreadable or invalid files skipped, key cannot walk out; iptables reconcile with a fake runner (add missing, remove
stale, remove a rule with our comment that is not the wanted one, leave a foreign rule and a `CAPE-rooter` rule alone, ours go first,
idempotent on a second apply, shared by two sessions of one guest); routes (stale of protocol 77 removed, a route of another
protocol left); tables; `close_lan_session` returns iptables, routes and tables to their state before and the nft file to the golden
bytes (compared with the fixture file); `initialise()` clears sessions and cleans; hook event rebuilds from the ledger; a failure
while opening leaves nothing recorded or open; nft refusing stops before iptables and routes.

Golden: `tests/fixtures/guest_firewall_running.nft` and `guest_firewall_idle.nft` were written from the unchanged `render_ruleset`
before any edit; `test_the_ruleset_with_guests_running_is_byte_for_byte_...` and the idle twin compare against them. They passed
before the change and pass after it. PASS.

## Check 2: syntax against the real nft (`-c`)

`nft -c` needs `CAP_NET_ADMIN` to talk to the kernel's nf_tables, not a netns of its own (`-c` loads nothing). Exact commands (the
scratch script `render.py N` renders the repo's `render_ruleset` for two running guests and N sessions, with the raw and TTL tables
inside the same file):

    python3 -I render.py N > rulesetN.nft
    docker run --rm -i --cap-add NET_ADMIN --entrypoint "" tartarus-cape:latest nft -c -f /dev/stdin < rulesetN.nft

| sessions | lines | result |
|---|---|---|
| 0 | 75 | rc=0, no output: PASS |
| 1 | 127 | rc=0, no output: PASS |
| 2 | 127 | rc=0, no output: PASS |
| edge: subnet 10.77.4.0/24, a session with no target and a target with no port | 16 lan lines | rc=0: PASS |

(nft in the image: 1.0.9, iptables 1.8.10 nf_tables, iproute2 6.1.0.) The same check runs as a pytest case on a machine where
`unshare -rn nft -c` works, but an **unprivileged user namespace refuses `ip ttl set` in a `type route` chain** (the Step 0
prototype `ttl.nft` fails the same way there: "Operation not permitted"), so the case skips on this host (3 skipped) and the docker
command above is the real check.

## Check 3: replica rig, real nft, iptables, ip and the rooter's own functions

Rig (all throwaway, `--internal` docker networks `s2rig-net` 192.168.150.0/24 and `s2rig-net2` 172.30.0.0/24): `s2rig-T`, the cape image
with `NET_ADMIN`/`NET_RAW`, its `eth0` enslaved to a bridge `tt-guest` that carries 192.168.150.1/24, a second address 172.30.0.2 on
`eth1` as the canary; the real `ip filter` rules from cape's `iptables-save` and `tartarus_egress` rendered by the repo's
`render_egress_ruleset`; `s2rig-G`, the "guest" (same image, fixed MAC 02:42:c0:a8:96:0b, address .11, probes in python:
TCP connect with banner, a raw-socket ping that reads the reply's TTL); `s2rig-L`, the listener
(`--network container:s2rig-T --cap-drop ALL --cap-add NET_BIND_SERVICE`) bound to .200:445, .200:3389, .200:22, .201:445, .201:3389,
.202:445, .1:2042 (the ResultServer port), 172.30.0.2:8000 (canary) and 0.0.0.0:8001 (wildcard). The firewall is driven by the repo's
own `GuestFirewall` with a runner that does `docker exec -i s2rig-T <command>` (`init`, `bind` = what the hook does,
`open_lan_session`, `close_lan_session`, `apply`). The rooter routes are the real functions of `/opt/CAPEv2/utils/rooter.py`:
`drop_enable` for `none` and `drop` (CAPE's `analysis_manager.py` line 814 sends `none`, `drop` and `false` to the same call, so
those two runs are the same code path twice), `inetsim_enable` + `libvirt_fwo_enable` + `forward_enable` for `inetsim`, nothing for
`raw`. A foreign route `local 192.168.150.202/32 dev lo` (another protocol) exists the whole time, so ".202 has no ARP entry" proves
the bridge layer stops it and the route reconcile leaves it alone.

Session: guest .11 may reach .200 on 445, 3389, 22 and .201 on 445, and ping both.

Per run 34 PASS lines (`out_<route>.txt` in the scratch dir, deleted with it); `raw`, `none`, `drop`, `inetsim` (rooter first),
and `inetsim` with the session opened first and the rooter enabled after it:

| Check | raw | none | drop | inetsim |
|---|---|---|---|---|
| allowed (guest, host, port) connects and the fake host's own banner comes back (`HELLO 192.168.150.200:445 from 192.168.150.11`), also :3389, :22, .201:445 | PASS | PASS | PASS | PASS |
| allowed host, port not in the set (.201:3389) | PASS timeout | PASS timeout | PASS timeout | PASS timeout |
| block host not in the session (.202:445): times out, no ARP entry with a lladdr | PASS | PASS | PASS | PASS |
| block address with no route (.210) | PASS | PASS | PASS | PASS |
| ping .200 and .201 answer, `REPLY ttl=128`; the gateway keeps TTL 64 (or its pre-session behaviour: the rooter's own OUTPUT drop already silences it on `none`/`drop`) | PASS | PASS | PASS | PASS |
| ping .202 silent | PASS | PASS | PASS | PASS |
| guest takes .200 as its own: ping and tcp to the gateway dropped; takes .202: dropped; control: invented .250 still works | PASS | PASS | PASS | PASS |
| canary 172.30.0.2:8000 and wildcard .1:8001 never connect, and the listener log shows no connection from any not-allowed address or port | PASS | PASS | PASS | PASS (a refusal: the rooter hijacks the SYN to the gateway's port 1) |
| our iptables OUTPUT and INPUT accepts are the first rule | PASS | PASS | PASS | PASS |
| second `apply()`: zero `-I`/`-D`/route/table changes, nft+iptables+routes state equal to the state after open | PASS | PASS | PASS | PASS |
| after `close_lan_session`: .200:445, .200:22, .201:445, ping .200/.201 silent; the gateway control still works | PASS | PASS | PASS | PASS |
| after close: `nft list ruleset`, `iptables-save`, `ip route show table local` equal the baseline saved before open (counters stripped) | PASS | PASS | PASS | PASS |

`inetsim` with the session opened before the rooter route: 35 PASS, 1 FAIL line, explained and not ours: after the close **and** after
`inetsim_disable` the iptables and route state equal the baseline, but `nft list ruleset` has one extra empty
`chain PREROUTING { type nat hook prerouting priority dstnat; }` in `table ip nat`: iptables-nft's base chain that the rooter's first
`-t nat -A PREROUTING` created and that disabling does not remove (the baseline of that variant was taken before the rooter ran). The
`diff` shows only those lines; no `tartarus-lan`/`tartarus_lan` object is left (that check passed). The rooter's `-A` rules came after
ours (our OUTPUT accept stayed line 2 of `iptables -S OUTPUT`).

Reconstruction (`reconstruct.sh`, raw route): wiping our iptables rules, routes and tables with raw commands and then running a plain
`apply()` (what a hook event runs) rebuilt all of it from the ledger (state equal to the open state): PASS. Then `init`, as at
container start, closed the session, cleared the ledger and left the state equal to what `init` left before the session: PASS.

Re-check from a clean state (rig destroyed and rebuilt, run after the last code edit): `checks.sh raw` 34 PASS 0 FAIL,
`checks.sh inetsim` 34 PASS 0 FAIL.

## Check 4: whole suite and lint

- `cd cape && uv run --no-project --with pytest --with-requirements build/pycdlib.requirements pytest -q`: **3011 passed, 45 skipped,
  0 failed** (the first run found one failure in `test_engine_generic_code.py`, which forbids the word "windows" in engine code: my
  `WINDOWS_TTL`/comment; renamed `FAKE_HOST_TTL`).
- `ruff check` and `ruff format --check` on my seven files: clean. On all of `guest_engine auxiliary tests bin/...` (the Makefile
  `lint` set) two E501 errors remain in `tests/test_snapshot_step.py` and `tests/test_windows_profile.py`, not mine.
- mypy: the Makefile runs it on `backend/app` only, not on cape, so it was not run.

## Not tested

- A real Windows guest through the real stack (the live `tartarus_guest` may not be replaced; the rig has a Linux guest, as in Step 0).
- Two guests at once on the rig (unit tests cover two guests; the rig has one), a `GUEST_SUBNET` other than 192.168.150.0/24 on the rig
  (unit tests and `nft -c` cover 10.77.4.0/24).
- Real INetSim behind the `inetsim` route (the rig has no INetSim: the hijacked SYN to the gateway's port 1 is refused).
- A rooter that enables its route between the reconcile's list and its insert (no lock with the rooter; the rooter appends with
  `-A`, we insert at position 1, so both orders were run but not a race).
- Concurrency of `guest-control` with the libvirt hook (see "Locking" above).

## Cleanup

Removed: containers `s2rig-T`, `s2rig-G`, `s2rig-L`, networks `s2rig-net` and `s2rig-net2`, the scratch directory. No image was built or
pulled. `docker ps` shows the same five tartarus services as before, `docker compose exec -T cape nft list tables` is identical to the
list saved at the start, and in cape there is no `tartarus_lan` table, no `tartarus-lan` iptables rule and no route of protocol 77.
Nothing was run against the live stack's firewall, routes, iptables, INetSim or guests (only the read-only `nft list tables` and
`nft list/iptables -S` comparisons of the final check).
