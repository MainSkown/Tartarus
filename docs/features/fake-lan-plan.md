# Plan: fake local network

Implementation plan for [fake-lan.md](fake-lan.md). It was written from reading the spec, the guest
firewall (`cape/guest_engine/firewall.py`), the compose file, the supervisor config, the submit and run
path (`backend/app/analyses/runner.py`), the ingest and Sigma code, and the zip-submission plan for its
shape. **Step 0 has run** (2026-11-23, notes in
[../history/fake-lan-notes/step0-notes.md](../history/fake-lan-notes/step0-notes.md)): findings 1 to 13 were
written from reading code, and "What Step 0 found" below says which held and what it added.

## Findings that change the spec

| # | Finding | Effect |
|---|---|---|
| 1 | The guest bridge `tt-guest` exists only inside the `cape` container's network namespace, not as a Docker network. A separate container cannot be "attached to the guest network" with `networks:`. | The fake-host container must share the namespace: `network_mode: "service:cape"`. It still has its own image, user, capabilities and no CAPE secrets. Decision 1 compares it with a program inside `cape`. |
| 2 | Fake hosts in the guest's own /24 are one hop away: the guest ARPs for them and sends frames to the bridge. Nothing is routed, so the **forward** chain and `RESERVED_NETWORKS` are not involved. Today the **input** chain drops anything not addressed to the gateway. | The firewall change is in the input chain and the bridge table, not in the forward chain as the spec's firewall item reads. |
| 3 | The rooter's `inetsim` route DNATs a guest's traffic in `PREROUTING` and sends "everything else to port 1" (comment in `firewall.py`). It probably matches the guest's source address only. *Verify.* If so it also rewrites traffic to a fake address before the input chain sees it. | Possible blocker. Step 0 reads `rooter.py`'s `inetsim_enable` and tests on the `inetsim` route. The fix would be a `NOTRACK`/early accept for the fake range in a table of ours at a priority before the rooter's chain, the same trick `firewall.py` already uses. |
| 4 | The anti-spoofing sets (`protected`, `bound`) cover the gateway and running guests only. A guest could claim a fake host's address. | The fake addresses join `protected`, bound to no port. A frame carrying one as source is dropped. |
| 5 | If the fake addresses are local routes of the container, every fake host answers ARP with the **bridge's MAC**, and ICMP replies carry Linux's TTL. Malware that fingerprints by MAC vendor or TTL sees through it. | Accepted for v1 (spec non-goal is "no real VMs"). Write it into the spec's behavior details so nobody is surprised. |
| 6 | INetSim's DNS answers every name with the gateway address. `net use \\FS01\C$` and any name-based tool would go to INetSim, not to the fake host. INetSim cannot serve SRV records, so AD discovery by `_ldap._tcp.dc._msdcs` does not work. | Fake host names need `dns_static` entries, rendered into `inetsim.conf` from the presets at start. NetBIOS and LLMNR broadcasts stay unanswered in v1 (the input chain drops them). The spec gets a "name resolution" line and Step 0 checks which lateral tools resolve by name. |
| 7 | The backend queue runs **one analysis per guest at a time** (`runner.py`: "one per guest at a time"), and the analysis already names its machine (`create_file_task(machine=guest.name)`). | The backend can open the LAN session for that guest just before it submits to CAPE and close it when the analysis ends, through the control service. No CAPE auxiliary module and no CAPE patch. It also makes "never half simulated" enforceable: a failed open fails the analysis. (A host-side auxiliary that fails to start does not stop a CAPE task.) |
| 8 | The Sigma matcher is single-event (`rules/matcher.py`, 54 lines). "Sweeps" and "many-hosts fan-out" are aggregates over time. | The normaliser emits **derived** events (`lan-sweep`, one per process, service and window), the way capemon emits derived events, and the rules match those. No aggregation in the matcher. |
| 9 | CAPE's `tcp[]`/`udp[]` records already become `network-connection` flows, with process attribution, for traffic to fake addresses. A second flow event from the fake-host log would double every row in the Network tab. | `lan-sim` events **enrich** instead of repeating flows: login attempts, share access, file writes and the derived sweeps. The flow rows to fake addresses are flagged from the analysis's preset (the address set goes into `IngestContext`). |
| 10 | `GUEST_SUBNET` is configurable (`firewall.py`, `policy_for`), so "fixed IPs per preset" cannot be literal `192.168.150.x`. `scripts/verify-isolation.sh` already uses `.250` as its invented address. | Presets store **host offsets** (`200`), resolved against the subnet. Fake hosts live in `.200` to `.247`; `.248` to `.254` stay free. |
| 11 | The summary is computed at final ingest (`backend/app/analyses/summary.py`, as `entry_sha256` was for zip submission), not by a view endpoint. | "Summary view endpoint" in the spec becomes a field of the analysis summary: `summary.lan`. |
| 12 | `SubmitDialog.vue` is 827 lines, and the tunnel-routes spec rewrites its route picker. | The LAN controls go in a new `SubmitLanFields.vue`, as `SubmitArchiveFields.vue` did. Merge order with the tunnel work is Decision 6. |
| 13 | The live feed has no source for fake-host logs. | The Lateral movement data is final-phase only in v1. The e2e live-versus-final alert comparison already exempts alerts whose trigger exists only in the final phase. |

## What Step 0 found

Held: findings 1, 2, 4, 6, 7, 9 and 10. Corrected or added by the spike:

| # | Result | Effect on the plan |
|---|---|---|
| S1 | **Finding 3 is true and worse.** The rooter's `inetsim` DNAT sends a guest's SYN to a fake address to INetSim's port 1 (the guest sees a live host answering from `.200`, and the per-port filter is bypassed). Routes `none` and `drop` add `iptables OUTPUT -d <guest> -j DROP`, which kills every reply of a local fake host. `inetsim` also adds `INPUT -s <guest> --dport 22 -j DROP`. | Three fixes, all tested on a replica rig: a `notrack` rule in a raw-priority table of ours (both directions); `iptables -I OUTPUT 1 -m iprange --src-range <block> -d <guest> -m comment --comment tartarus-lan -j ACCEPT`; and the same kind of rule for INPUT. `cleanup_rooter()` keeps rules whose comment is not `CAPE-rooter`. **`firewall.py` must therefore also drive iptables**, and the iptables rules must be reconciled (stale ones removed) by the same `apply()`. |
| S2 | **An accept in a table of ours cannot open the input chain**: a packet accepted at one base chain still meets `tartarus_guest`'s final `counter drop`. | The allowed-pair sets go **inside `tartarus_guest`'s own input chain**, not a table of ours. Only the notrack and TTL rules live in tables of ours. |
| S3 | The bridge-level sets work as drafted: `arp daddr ip` and `ip daddr` of the fake block dropped unless the `(guest, host)` pair is allowed; a guest that takes a fake address is dropped; a canary on the container's other address stays unreachable. The accept for a pair must not be a bridge `accept`, which would skip the spoofing checks below it. | Step 2 uses the prototype's rule shapes (`docs/history/fake-lan-notes/firewall-sets.diff`). The sets are rendered **only when a session exists**, so the no-session ruleset stays byte-identical. The block comes from the presets, not a literal `.200-.247`. |
| S4 | Fake addresses answer ARP with the bridge's MAC. ICMP TTL is 64, fixable to 128 with an nft `type route hook output` rule (`ip ttl set 128`) for the fake addresses. | Decision 4 improves: the MAC is accepted, the TTL is fixed (`ttl.nft`). |
| S5 | **Windows' SMB client signs with a key derived from the password.** A fake host that accepts any password cannot sign back, so `net use`, `dir` and `copy` end in "Invalid Signature" on Win10 22H2 and Win11 25H2. With **one known account** per host, `net use`, `dir` and `copy` to `ADMIN$` all work. `sc \\host` also needs an authenticated, sealed RPC bind. | Presets list **accounts with known (weak, well-known) passwords per host**. A login with another password fails as on a real host, and its NTLMv2 material is logged. "Accept any login" holds only for clients that do not sign (impacket tools, smbclient, nxc). Execution is never offered; PsExec from Windows is logged up to the service-creation attempt. Decision 9. |
| S6 | impacket's `SimpleSMBServer` needs patches: clear the Guest session flag, make `IPC$` read-only, add a fake `svcctl` pipe, serve each RPC connection on its own thread, and replace its file writes (any size, client-chosen path) with a capped virtual store. `wmiexec` needs DCOM on 135 and is out. | SMB is the biggest service, not "negotiate plus tree connect". Step 4 describes it accordingly. Decision 10. |
| S7 | Names: `dns_static` serves **FQDNs only**; a single-label name stops all of INetSim from starting, and so does a name with an underscore (SRV); the guests have no DNS suffix, so `\\FS01\C$` cannot work by name. NetBIOS, LLMNR and mDNS queries leave the guest but nothing in the chain delivers them to a socket. | Preset host names are FQDNs (`fs01.corp.local`), and the renderer validates them before writing `inetsim.conf`. Single-label discovery is out of scope (worm-style IP scanning needs no name). |
| S8 | The daemon only sees connections to **open** ports: a half-open SYN scan is invisible to it, and closed ports and absent addresses exist only in CAPE's flows and ARP. | `lan-sweep` and `lan-fan-out` are derived from the CAPE `tcp[]` and `dead_hosts` flows and the capemon `connect` calls that the `lan-sim` normaliser reads from the report, not from the daemon's log. |
| S9 | Attribution works the way `cape-network` already does it: pcap flow (source port) joined with Sysmon EID 3 (`SourcePort`, pid, image), and capemon `connect` for attempts that never established. `tcp[]` has no process; EID 3 exists only for established connections. | The `lan-sim` log has no pid: its events are keyed on `(guest source port, destination ip, port)` and take the process from the flow. |
| S10 | Caps from the flood data (Step 4 uses them): 200 events/s per session; the first 200 events per (session, host, service) in full, then counters (up to 50 usernames, 5 secrets); a hard cap of 20 000 events or 8 MB per session; 32 connections per (source, service) and 512 per session; 64 KiB per connection, 30 s idle, 16 MiB per file and 64 MiB per session. Derived thresholds: sweep at 5 or more hosts on one port within 30 s; fan-out at 4 or more hosts over 2 or more services within 5 min; credential spray at 3 or more hosts with one username within 5 min. | Starting values, tuned once the real daemon exists. |

Not tested by the spike, so Steps 2 and 12 must cover them: a Windows guest reaching a fake address with the fixes in place (the spike could not replace the live `tartarus_guest`, which the permission layer denied, so it measured a Linux guest on a replica rig that uses the repo's own `render_ruleset` and the rooter's real functions), two guests at once, a `GUEST_SUBNET` other than the default, and hostile input against the services.

## Design in one paragraph

One `lan-sim` container shares `cape`'s network namespace and binds each fake host's services on the
host's own address (a local `/32` route per address, no wildcard listener, so the container's other
addresses expose nothing). **Presets use disjoint address blocks and unique host names**, so one shared
daemon answers by destination address, and concurrent analyses cannot clash: this answers the spec's
first open question. The firewall opens, per running guest, exactly its preset's addresses and ports
(`ip saddr . ip daddr` sets in the input chain, the same pairs in the bridge table for ARP and IP), so a
guest on preset A cannot even ARP for preset B's hosts. The backend opens a *session* (task, guest address,
preset) through the control service before it submits to CAPE; the daemon writes one JSONL log per session;
closing the session copies the log into the analysis folder (`lansim/events.jsonl`), where the new
`lan-sim` normaliser reads it, like Sysmon's `sysmon/sysmon.xml`.

## Steps

Each step follows the [rules](../contributing/the-rules.md): test first, self-documenting code, no
duplication. Model tiers follow rule 5 (never Opus; pass `model` explicitly). Every "extreme" step keeps a
notes file in `docs/history/fake-lan-notes/` (done, running, next), and I re-run its checks and read its
diff before committing. Work goes on **one branch** (`fake-lan`) as separate commits.

### Step 0: spike on a real stack

**Status: done.** Evidence and the stand-in scripts are in
[../history/fake-lan-notes/](../history/fake-lan-notes/step0-notes.md); "What Step 0 found" above carries
the results.

**Tier:** extreme (Sonnet, with the notes file). Needs the stack up and one ready Windows guest. The app
has no Linux guests, so the spike has two vantage points, and each case says which one it uses:

- **The Windows guest**, for everything that depends on the path a real guest takes (ARP, the bridge and
  input rules, the rooter's routes). It uses Windows' own tools (`arp`, `ping`, `Test-NetConnection`,
  `net use`, `sc`, `Enter-PSSession`, `mstsc`) and, where a Linux tool is wanted, a portable Windows build
  or a Python package uploaded through the guest's agent (the guest has no internet on `inetsim`/`none`).
- **A throwaway container** with `network_mode: service:cape`, running the Linux tools (impacket, nmap,
  netexec, `ldapsearch`, `sqlcmd`, `ssh`). It shares the namespace, so its traffic is local to the
  container and **bypasses the guest rules**: it proves what a service answers, never what a guest can
  reach. The daemon sees the container's own address as the source, so the spike gives it a session for
  that address by hand.

Each case ends in a check that can fail:

1. **Mechanism** (Windows guest). Add local `/32` routes for three addresses on `tt-guest`; from the
   guest, `arp -a` and ping them, and an address with no route must stay silent. Run a listener from a
   container with `network_mode: service:cape` bound to one fake address and connect from the guest. Repeat on routes
   `none`, `drop` and `inetsim` (finding 3). Record whether the rooter's DNAT or a missing input rule
   gets in the way, and the exact rule that fixes it.
2. **Filtering** (Windows guest). With nft sets of `guest . host` pairs in the input chain and the bridge
   table, the guest reaches its preset and cannot ARP for another's. With only one guest available, the
   "other preset" case is a second preset's address that this guest's set leaves out, and the
   two-guest case is left to `make verify-isolation` (Step 12), which already starts two guests. A guest
   that takes a fake address as its own is dropped (finding 4).
3. **Protocol fidelity**, per service, with the tools malware families actually use against it
   (impacket `psexec`/`smbexec`/`wmiexec`, `smbclient`, `nmap -sV`, `netexec`, `ldapsearch`, `sqlcmd`, `ssh`
   from the **container**; `net use \\ip\C$`, `sc \\ip`, `mstsc`, `Enter-PSSession` from the **Windows
   guest**): what is the minimum a fake host must answer so the tool proceeds one more step (finding 5 and
   the spec's second open question). Where the two disagree, the Windows guest wins: it is what the
   sample sees.
   Evaluate reusing libraries before writing parsers (rule 3): impacket's SMB server, `asyncssh`, `ldap3`
   server side, OpenCanary's MSSQL module. Note licenses for `THIRD_PARTY.md` and `docs/licenses.md`.
4. **Names** (Windows guest). Which of those tools resolve by name, and does `dns_static` in INetSim
   serve them (finding 6).
5. **Floods** (container for volume, Windows guest for one realistic scan). `nmap -sS -p-` and `-sT` over
   the whole /24 and a 10 000-attempt SMB login loop: events per second, log size, CPU and memory of the
   daemon. This gives the cap numbers (third open question). A scan from the guest is slower and
   shaped by Windows' own socket limits, so it sets the realistic rate and the container sets the worst case.
6. **Attribution** (Windows guest). Whether the guest's Sysmon EID 3 and CAPE's pcap flows for these
   attempts carry the process, so the normaliser can attribute lan-sim events through `endpoint_key`.

Write the findings to `docs/history/fake-lan-spike-notes.md` and close the open questions in the spec.
Delete the throwaway container, the uploaded tools and any memory dumps afterwards.

### Step 1: preset format and loader

**Tier:** Sonnet (it fixes the format three components read), with the format already decided by Step 0.

- `guest/lan-presets/<id>.json`, declarative, next to `guest/profiles`: `id`, `name`, `description`,
  `domain`, `hosts: [{fqdn, host_offset, role, os_banner, accounts: [{user, password}], services: [{kind, port, options}]}]`.
  `accounts` are the well-known weak accounts that let Windows' signing SMB client past the logon (S5).
- A loader and validator in the `cape` Python project (`guest_engine/lan_presets.py`), because the control
  service, the firewall and the daemon all run beside it. Rules checked by tests: offsets inside
  `.200`-`.247`, **no overlap between presets**, unique FQDNs (valid for INetSim's `dns_static`: two labels or more, no underscore, S7), ports in range, known service kinds, at least one account on every SMB host.
- Three presets: small office (domain controller, file server, two workstations, SQL server, printer),
  flat home LAN, domain with servers. The concrete hosts come from the Step 0 findings.
- Test first: the three shipped presets validate; an overlap, a duplicate name and an offset outside the
  block each fail with a precise message.

### Step 2: firewall and addresses

**Tier:** extreme (Sonnet, with the notes file). The delegation table lists guest network isolation rules
under extreme.

Extend `cape/guest_engine/firewall.py` (a `lan_firewall.py` beside it if it grows past one screen, so the
module keeps one job):

- A `LanLedger` like `PortLedger`: one file per running guest, `{guest_address, preset}`.
- Inside `tartarus_guest`'s own input chain (S2): accept `ip saddr . ip daddr . tcp dport` and the ICMP echo
  pairs from sets built from the ledger and the presets. The rest of the chain is unchanged: still `counter drop`.
- Bridge table (S3, shapes from `firewall-sets.diff`): drop ARP and IP to a fake-block address unless the
  `(guest, host)` pair is allowed, and any frame that uses a fake address as its source. Not a bridge `accept`.
- Three more pieces, because nft cannot override the rooter's iptables (S1, S4): a raw-priority table of
  ours with `notrack` both ways for the pairs; a `type route hook output` table that sets TTL 128 on the
  fake addresses; and iptables `OUTPUT` and `INPUT` accepts for the fake block, one per guest, with the
  comment `tartarus-lan`, inserted first and reconciled (stale ones removed) by `apply()`.
- Local `/32` routes (`dev lo`) for the addresses of the presets in use, applied and removed by the same `apply()`.
- Everything is rendered only while a session exists; the block comes from the presets and `GUEST_SUBNET`.
- `RESERVED_NETWORKS`, forward chain, port isolation (`isolation.py`, `port_isolation.py`) and the qemu
  hook are **not touched**. With no session the rendered ruleset is byte-identical to today's and nothing is
  added to iptables, and a test says so.
- Tests first: render tests like `test_guest_firewall.py` (the ruleset with zero, one and two sessions;
  every value validated before it lands in nft input; the empty case is unchanged), plus a syntax check
  with `nft -c` where the test image has nft. The iptables reconcile is tested with a fake runner (the add, the
  removal of a stale rule, the rooter's own rules left alone). The proof on a real Windows guest and on two
  guests is Step 12.

### Step 3: control service endpoints

**Tier:** Sonnet. Builds on Steps 1 and 2; the endpoint shapes follow `control_http.py`.

On `guest-control` (authenticated, only on `tartarus-control`):

- `GET /lan-presets`: the presets as the API shows them (id, name, hosts with role, address and services).
- `POST /lan/sessions` `{task key, guest, preset}`: records the ledger entry, applies the firewall, tells
  the daemon, and answers only when the daemon confirms it listens. Any failure answers an error and
  leaves nothing open.
- `DELETE /lan/sessions/{key}`: closes the ledger entry, applies the firewall, asks the daemon to flush
  and close the log, copies it to the analysis folder (`lansim/events.jsonl`, the pattern of the memory
  dump), and deletes the staging copy. Idempotent.
- `GET /lan/health`: the daemon's state, for submit-time refusal.
- On `guest-control` start, close every session left from a crashed run (nothing from before the restart
  may stay open).
- One socket-and-protocol helper, not a second copy of `machine_broker_logic.serve_connection`: extract
  what both need if the daemon channel ends up needing it (extract on the third use, not the second).

### Step 4: the `lan-sim` daemon

**Tier:** the framework is Sonnet (it handles hostile input), and so is each protocol that parses a binary
format. Protocols that Step 0 shows to be a library call or a fixed reply go to Haiku with the spec the
spike produced.

New top-level `lan-sim/` (own `Dockerfile`, pinned base by digest like the others, a small Python
project with its own tests):

- **Framework** (Sonnet): asyncio, one listener per `(address, port)` from the loaded presets, one
  `Service` protocol every service implements (the normaliser-interface pattern), one event writer that
  JSONL-logs every connection, login attempt, share access and file write with the session key resolved
  from the source address. Hard limits: bytes per connection, connections per source, a file-write cap
  (writes are logged and hashed, never stored beyond a cap, never executed), idle timeouts. Flood
  control from Step 0: events past the cap collapse into counters in the session's final record.
- **SMB** (Sonnet, the largest piece; S5, S6): impacket's protocol classes behind our own server, not its
  `SimpleSMBServer` as is. Known accounts from the preset sign and get real sessions; any other login
  fails and its NTLMv2 material is logged; clients that do not sign may also get in (impacket tools,
  smbclient, nxc) with the Guest flag cleared. Tree connect to `IPC$` (read-only), `ADMIN$`, `C$` and the
  preset's shares; a fake `svcctl` pipe (open manager, create, start, delete, enumerate) that logs the
  service name and binary path and never starts anything; one thread per RPC connection; a capped
  virtual file store (hash and size, never a client-chosen host path). Server name and domain from the
  preset, SMB1 off. `wmiexec` (DCOM on 135) and `sc.exe`'s authenticated RPC are out for v1.
- **RDP** (Sonnet): X.224 confirm selecting HYBRID, TLS with a self-signed certificate for the host's FQDN,
  a CredSSP exchange that captures the NTLM material, then `STATUS_LOGON_FAILURE`.
- **LDAP** (Sonnet): ldap3's `rfc4511` classes with a small hand-written server: anonymous and simple bind, a
  root DSE that includes `configurationNamingContext` (nxc needs it), a base search of the domain DN, NTLM
  binds captured and refused.
- **MSSQL** (Sonnet; no library fits): hand-rolled TDS prelogin and Login7 (the token layout depends on the
  client's TDS version), log the login, answer `SELECT @@version`, refuse the SSPI path after capturing it.
- **WinRM** (Haiku, from the spike's stand-in): HTTP 5985, `401` with `Negotiate` and `Basic`, an
  unauthenticated `Identify` answered with 200, NTLM and Basic captured, always `401` after.
- **SSH** (Haiku, asyncssh, from the spike's stand-in): banner from the preset, password and key attempts
  logged, a login that is accepted and leaves the client with nothing to run.
- Tests: each service against a recorded exchange from the Step 0 tools (a fixture replay, no containers);
  the framework with a fake clock and socket pair; the limits with a flood. A test that a handler never
  runs, writes outside its cap, or opens a file path the client chose.

### Step 5: compose service, image and supervision

**Tier:** Sonnet (isolation-relevant, so rounded up from Haiku).

- `docker-compose.yml`: `lan-sim` with `network_mode: "service:cape"`, `cap_drop: [ALL]` plus
  `NET_BIND_SERVICE`, `read_only: true`, a non-root user, `no-new-privileges`, no `.env` secrets, memory
  and pids limits, a healthcheck, `depends_on: cape: service_healthy`. Two small volumes: sessions and logs
  (read-write for `cape`'s control service, read-only sessions for `lan-sim`). Part of the default stack.
- The entrypoint renders `dns_static` entries for all preset host names into `inetsim.conf` (finding 6).
- Document the one compose caveat: recreating `cape` recreates its namespace, so `lan-sim` must restart
  with it (check that `docker compose up` does this; if not, the cape healthcheck gates it and the docs
  say how to recover).
- `THIRD_PARTY.md` and `docs/licenses.md` for every library the image adds.
- Tests: `cape/tests/test_capability_drop.py`-style check that `lan-sim` holds no capability beyond the
  one listed, and an image test that it runs as non-root.

### Step 6: backend options and run orchestration

**Tier:** Sonnet.

- `AnalysisOptions.lan_preset: str | None` (None is off); refused with `route="internet"`; unknown preset
  refused (the list comes from the control service). Both refusals with precise messages. No new column:
  the preset is in `analysis.options`.
- `GET /api/lan-presets` proxies the control service's list; operation id for the generated client.
- Submit refuses with a clear message when `lan/health` says the daemon is not up.
- `AnalysisRunner._upload` opens the session before `create_file_task`; any failure ends the analysis as
  `FAILED` with "the fake local network could not start", and **nothing is submitted**. Every path that
  ends an analysis (finished, failed, cancelled, a task CAPE lost) closes the session; the monitor's
  existing reconciliation also closes sessions for analyses that are no longer active (a backend restart
  mid-run).
- The close runs before the final ingest, ordered the way `memory_step.py` orders the memory read, so
  `lansim/events.jsonl` is in the analysis folder when the ingest looks.
- Tests first with fake control and CAPE clients: off means no call at all; open fails, nothing submitted;
  CAPE refuses, session closed; cancel, restart and failure each close.

### Step 7: normaliser, fields, network view

**Tier:** the mapping table is Haiku once Step 0 fixes the log format; the normaliser, the derived events
and the attribution are Sonnet.

- Fields (the one catalog, `backend/app/search/fields.py`, and the table in `docs/specs/data-model.md`):
  `tartarus.lan.simulated` (boolean), `tartarus.lan.host` and `tartarus.lan.role`, `tartarus.lan.service`,
  `tartarus.lan.preset`, `tartarus.lan.share`, `tartarus.lan.attempts` (on derived events), plus
  `user.name`, `user.domain`, `file.name`, `file.hash.sha256` and `event.outcome` already in the
  catalog where they exist. A catalog test covers that the query bar, the autocomplete and the Sigma
  pipeline all read the new rows (they read one table).
- `backend/app/ingest/lan_sim.py` (reads the daemon's log from `analysis_dir` **and** the report's
  `network.tcp[]`, `dead_hosts` and capemon `connect` calls for the derived events, S8): `LanSimNormalizer` implementing the `Normalizer` protocol, built with
  `EventFactory`, attributed through `ProcessAttribution`/`endpoint_key` as `cape-network` does. Actions:
  `lan-login-attempt` (category `authentication`), `lan-share-access`, `lan-file-write`, and the derived
  `lan-sweep` and `lan-fan-out`. A missing or truncated log yields no events and a warning, never an
  exception (the protocol says so).
- Registered in the ingester's list of sources, and the docs of "adding an event source" followed.
- `IngestContext` gets the analysis's fake-host addresses so `cape-network` flags flows to them
  (`tartarus.lan.simulated`).
- `backend/app/views/network.py`: `HostRow` gets `simulated` and the host's LAN name and role; flows get
  the flag. The hosts list sorts fake hosts as any other.
- Tests first: pure normaliser tests from a fixture log (including a flood log, a truncated log and a
  hostile string in a username), the view test for the flags, and a test that no flow row is duplicated.

### Step 8: Sigma rules and ATT&CK

**Tier:** categories and mapping are Sonnet (judgment in the Sigma field mapping); the rule files are
Haiku (a clear template in `rules/sigma/tartarus/`).

- `SUPPORTED_CATEGORIES`, `ACTION_CATEGORIES` and `FIELD_MAPS` get `lan_authentication`, `lan_share_access`
  and `lan_sweep` (one table per category, as `mapping.py` is built).
- Rules in `rules/sigma/tartarus/` (authored here, not SigmaHQ's pinned set, so `ATTRIBUTION.md` stays
  true): connection to SMB, RDP, WinRM, SSH or MSSQL ports on a fake host by a process that is not a
  system one (`network_connection`, `attack.lateral-movement`, T1021.001/.002/.004/.006, T1210); admin
  share access, which covers PsExec (T1021.002, T1570); credentials tried against many fake hosts
  (T1110.003); a sweep and a many-hosts fan-out from the derived events (T1046, T1021).
- Check `backend/app/data/attack_techniques.json` has every id used (`scripts/build-attack-table.py`
  builds it); a test fails on a rule with an id the matrix cannot name.
- Tests first: the rule loader and matcher tests for each rule against a normaliser fixture, a negative
  case each (a system process, a host outside the preset), and the ATT&CK view test that the technique
  lands in Lateral Movement.

### Step 9: summary and report

**Tier:** summary aggregation Sonnet; the HTML/PDF section Haiku, following an existing section.

- `summary.lan` computed at final ingest: preset, and per fake host the services touched, attempts, first
  and last time, credentials and files the sample used or wrote (user names and hashes as the sample
  sent them, capped; untrusted text, escaped on display). `null` when the feature was off, so the section
  is hidden; present with no hosts when the sample did nothing, so the empty state shows.
- `backend/app/export/report`: the Lateral movement section in the HTML and PDF templates, and the fake
  flags on the hosts it lists.
- Tests first: aggregation from normaliser fixtures (off, empty, populated, over the cap); the report
  renders each of the three states.

### Step 10: frontend

**Tier:** the composable and the badge are Haiku; the dialog fields and the Summary section are Sonnet.

- `useLanPresets` (vitest: loading, error, none, many) over the generated client (regenerate it after
  Step 6; no hand-written fetch).
- `SubmitLanFields.vue`: the "Simulate local network" switch, off by default, the preset picker, the
  disabled state with its reason for `internet`; blocks submit while presets load or fail. Mounted in
  `SubmitDialog.vue` without growing it.
- Network tab hosts list: a "fake LAN host" badge and the filter-on / filter-out action through the shared
  `FieldActions` component, not a copy.
- `LateralMovementSection.vue` in the Summary tab: hidden, empty and populated states.
- Every string through message keys, in every locale file ([how](../contributing/adding-a-message-key.md)).

### Step 11: visual review

Done by me, per rule 4, one Artifact per screen:

1. Submit dialog fields: off; on with the picker; presets loading, error and none; disabled for `internet`;
   a long preset name; narrow window.
2. Network tab: the badge in the hosts list and flows, the filter action, many fake hosts, a long host
   name.
3. Summary, Lateral movement: hidden, empty, populated, a host with many services, long credential
   strings, narrow window.

I check every screenshot myself first, publish, and answer comments on the same Artifact URL.

### Step 12: proofs

**Tier:** the isolation script is Sonnet (it is the proof of the guarantee); the e2e is Sonnet because it
drives a real guest; docs are Haiku.

- `scripts/verify-isolation.sh`: with a session open, the guest reaches its preset's fake hosts on the
  right ports, the gateway, and nothing else, on every route in `ROUTES` including `raw`; with no session
  the existing results are unchanged; guest B (no session or another preset) cannot ARP for or reach guest
  A's fake hosts; a guest that takes a fake address as its own is dropped; guest A still cannot reach
  guest B. Add the negative proof the script already documents (delete the nft table, expect exit 1).
- `scripts/lib/e2e-lan.sh` (`E2E_ONLY=lan scripts/e2e.sh`): the benign sample scans for SMB, connects to
  an admin share and writes a file, on routes `none` and `inetsim`: Network tab flags, `summary.lan`, the
  Lateral Movement alert, the technique in the matrix, the section in the HTML report; and a run with the
  feature off that shows none of it.
- Docs from the spec's "Other" list and `CHANGELOG.md`.

## Order

```
0 → 1 → (2 ∥ 4-framework) → 3 → 4-protocols ∥ 5 → 6 → 7 → (8 ∥ 9) → 10 → 11 → 12
```

Steps 2 and 4 can run in parallel once the preset format exists; the protocols fan out as one message of
parallel agents. The frontend can start once Step 6 has produced the API client.

## Decisions

**All eight were accepted as recommended on 2026-11-23.** The list below is what was decided.

1. **Container or program.** Recommended: a container with `network_mode: service:cape`. It keeps hostile
   protocol parsing out of the container that holds libvirt, QEMU and CAPE's secrets, and matches the spec's
   "compose service". The cost is the shared-namespace restart caveat. The alternative is a supervisord
   program as an unprivileged user inside `cape`: simpler, one less restart hazard, a larger blast radius.
2. **Presets with disjoint address blocks.** Recommended (answers open question 1, makes the shared
   daemon and the shared `dns_static` safe). The cost: a guest that resolves another preset's name gets an
   address it cannot reach.
3. **Backend-orchestrated session** instead of a CAPE auxiliary module (finding 7). Recommended: it is
   fail-closed and needs no CAPE patch.
4. **Same bridge MAC and TTL for every fake host** (finding 5). Recommended: accept for v1 and document it.
5. **Sweep and fan-out as derived events** (finding 8), thresholds set from Step 0's flood numbers.
6. **Merge order with [tunnel routes](tunnel-routes-and-tls-interception.md).** Both rewrite the route area
   of `SubmitDialog.vue`. Recommended: this feature goes first (its dialog code lives in
   `SubmitLanFields.vue`, so the conflict is a few lines), and the tunnel work rebases. Once `internet` is
   hidden by that work, the API refusal in Step 6 stays as the guard.
7. **Live phase.** Recommended: final only in v1 (finding 13).
8. **Security docs.** Does `docs/security.md` get its accepted-risks table before this ships, and does the
   next audit's scope include `lan-sim`? Recommended: yes to both, in the same branch (the spec's last open
   question). Needs your answer because it changes what "done" means.

New from the spike, **not yet confirmed by the user** (work proceeds on the recommended default, and the
presets and the SMB service are the only places either would change):

9. **Known accounts instead of accept-any-login** (S5). Recommended: each host's preset lists well-known weak
   accounts (`Administrator` / `Password1` style); the guest's own account is **not** added to the fake
   hosts in v1, so no guest secret reaches the daemon. The cost: a sample that reuses the logged-on user's own
   credentials fails the logon (as on a host that does not know them), though its NTLMv2 material is logged.
   Adding the guest's own account is a later step and needs a secret-handling review first.
10. **impacket and wmiexec** (S6). Recommended: use impacket's protocol classes (a modified Apache 1.1
    licence, to list in `THIRD_PARTY.md` and `docs/licenses.md`), and accept that `wmiexec` (DCOM on 135) and
    `sc.exe` (sealed RPC) get no working answer in v1.

## Spec edits this plan implies

- Behavior details, from the spike: accounts with known passwords per SMB host; FQDN host names only; the
  TTL of fake hosts is 128; `firewall.py` also drives iptables and two tables of ours (notrack, TTL);
  sweeps are derived from CAPE flows because the daemon never sees a closed port.
- Guest network: the container shares `cape`'s namespace (`network_mode`), not "attached to the guest
  network".
- Firewall item: the change is in the input chain and the bridge table; forward and `RESERVED_NETWORKS`
  are not involved.
- Behavior details: presets store host offsets in `.200`-`.247`, have disjoint blocks, and unique host
  names; fake hosts share the bridge's MAC; name resolution through `dns_static`, NetBIOS and LLMNR not
  answered.
- Backend: `summary.lan` replaces "Summary view endpoint"; the normaliser enriches and does not repeat
  flows; sweeps are derived events; the session is opened and closed by the backend through the control
  service.
- Open questions: close 1 (disjoint blocks), keep 2 and 3 until Step 0, keep 4 as Decision 8.
- Relevant code: add `cape/bin/guest-control`, `cape/bin/control_http.py`, `backend/app/analyses/summary.py`,
  `backend/app/ingest/ecs.py`, `backend/app/rules/mapping.py`.
