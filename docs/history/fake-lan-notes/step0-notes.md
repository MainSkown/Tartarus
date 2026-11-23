# Fake LAN spike notes (Step 0 of fake-lan-plan.md)

Setup: stack already up (not rebuilt). Guests `win` (Win11 25H2, 192.168.150.10) and `w10` (Win10 22H2, 192.168.150.11), shut off at the start; both were
started by me (snapshot revert) and are shut off again. Baseline nft and iptables state saved before the first change. Throwaway scripts lived in the
session scratchpad; the ones worth keeping are copied under `docs/history/fake-lan-notes/` (`standins/`, `firewall-sets.diff`, `notrack.nft`,
`identity-dnat.nft`, `ttl.nft`). Nothing under cape/, backend/, frontend/, docker-compose.yml, rules/ or scripts/ was touched, nothing committed.

**One thing was not done as briefed:** the brief assumes an nft table of ours can open what `tartarus_guest` drops. It cannot (Finding A). Testing the
positive path on the real Windows guest would have meant replacing `tartarus_guest`; the permission layer denied `nft delete table inet tartarus_guest` and
I did not look for another way. The positive path of cases 1 and 2 was measured on a replica rig with a Linux guest instead (same rules, same rooter code),
plus what the real guest could show with the real firewall (ARP, MAC, rooter DNAT, SSH drop, process attribution).

## Done
- Case 1 (mechanism): done on the real guest (ARP/MAC/inetsim DNAT/ssh drop, task 170) and on the rig (all routes, fixes). 
- Case 2 (filtering): done on the rig with a prototype of the Step 2 ruleset; real tables verified unchanged.
- Case 3 (fidelity): all six services, container tools and Windows guests.
- Case 4 (names), case 5 (floods), case 6 (attribution): done.
- Re-check of the most important checks of cases 1 and 2 from a freshly built rig: reproduced (see "Re-check" at the end).
- Cleanup: done (see "Cleanup" at the end).

## Running
- nothing

## Next
- the planner decides the spec edits listed under "Contradictions and spec edits" and Step 1 and 2; the open points under "Not tested" are the follow-ups.

## Findings

### Real guest, firewall unchanged (case 1, first half)

Local routes added in cape: `ip route add local 192.168.150.200/32 dev lo`, `.201 ... dev tt-guest`, `.202 ... dev lo`;
listener container `docker run --network container:tartarus-cape --cap-drop ALL --cap-add NET_BIND_SERVICE python:3.12-slim`
bound to .200:445, .201:445, .202:445, .200:3389 (`ss -ltn` in cape shows them).

| Check | Result | Evidence |
|---|---|---|
| Guest `arp -a` after pinging .200/.201/.202 | PASS: all three resolve | `192.168.150.200/.201/.202  52-54-00-8f-4c-05  dynamic` = the MAC of the `tt-guest` bridge (`ip link`: 52:54:00:8f:4c:05), same as the gateway's |
| Route device irrelevant for ARP | PASS | `dev lo` (.200, .202) and `dev tt-guest` (.201) all answered. Choose `dev lo`: it is the standard form for a local route and does not depend on the bridge existing |
| Address with no route (.203) stays silent | PASS | no ARP entry; `ping` answers `Reply from 192.168.150.10: Destination host unreachable` (the guest's own stack after ARP failed), nothing from the network |
| Ping to a fake address with the firewall as shipped | silent (expected) | `Request timed out` x2; input chain `counter ... drop` went from 0 to 10 packets |
| TCP connect .200:445 with the firewall as shipped | silent (expected) | `TCP 192.168.150.200:445 TIMEOUT` while `192.168.150.1:80` `CONNECTED` |
| ICMP TTL | not measurable yet (needs input opened) | Linux default `net.ipv4.ip_default_ttl = 64`, so a reply arrives as TTL=64 |

ARP is answered by the kernel from the local route alone (bridge table lets guest ARP requests through because the
target is not in `protected`). Everything above the bridge is stopped by the input chain, as the plan assumed.

### Finding A (contradicts plan, Step 2 and the task text): a table of ours cannot open the input chain

An experimental inet table `tartarus_lanspike` with `type filter hook input priority -20` and rules
`ip saddr . ip daddr . tcp dport @lan_tcp counter accept` / `ip saddr . ip daddr @lan_icmp icmp type echo-request counter accept`
was loaded next to the untouched `tartarus_guest`. Result:

    chain input (tartarus_lanspike):  ... tcp dport @lan_tcp counter packets 3 bytes 156 accept
                                       ... @lan_icmp icmp type echo-request counter packets 2 bytes 120 accept
    chain input (tartarus_guest):      counter packets 15 bytes 1021 drop      (was 10; the same packets)
    guest: TCP 192.168.150.200:445 TIMEOUT, ping .201 timed out

`accept` in a base chain only ends that chain; the packet still goes through the next base chain at the same hook, and
tartarus_guest's final `counter drop` kills it. So the plan's "accept in a table of ours at a priority before the
iptables chains" is impossible for the input chain: **the allowed-pairs sets and accept rules must live inside
`tartarus_guest`'s own input chain** (which is what Step 2 of the plan literally says, but not what this spike's brief
assumed). For the same reason nothing of ours can bypass the iptables chains by accepting early (see case 1, rooter).
The table was deleted again after the test.

BLOCKED: to test the positive path with the real Windows guest the spike would have to replace `tartarus_guest` with a
copy that has the sets (`replica.nft` in the scratchpad, generated from the live table). The permission layer denied
`nft delete table inet tartarus_guest` (the brief says that table must stay untouched), so I did not do it. The positive
path is measured on a replica rig instead (a Linux guest in a throwaway container, see below), and the Windows-guest
checks that need an open input chain are listed under "NOT tested".

### Replica rig for the positive path of cases 1 and 2 (Linux guest, not Windows)

Because the real firewall could not be replaced (see BLOCKED above), cases 1 and 2 were run on a rig that has the same
rules and the same rooter code, and a Linux guest instead of Windows:

- `lanspike-T`: a container from the `tartarus-cape` image (own network namespace, `--cap-add NET_ADMIN --cap-add NET_RAW`,
  entrypoint `sleep`), on a throwaway docker network `lanspike-net` (192.168.150.0/24). `eth0` is enslaved to a bridge
  named `tt-guest` that carries 192.168.150.1/24, so the bridge table sees the guest's frames exactly as on the real stack
  (`bridge link`, `nf_call_iptables 0` as in cape). The real `ip filter` rules (from `iptables-save` in cape) and
  `tartarus_egress` are loaded, and `tartarus_guest` is rendered by the repo's own `render_ruleset` (stock) or by a patched
  copy (prototype, `proto/guest_engine/firewall.py` in the scratchpad, diff in `firewall_proto.diff`).
- Rooter rules come from the real `utils/rooter.py` functions (`drop_enable`, `inetsim_enable`, `libvirt_fwo_enable`,
  `forward_enable`), called with the arguments `rooter-route.py` uses. The routes `none`, `drop` and `false` are the same
  thing in CAPE (`analysis_manager.py` line 814: all three call `drop_enable`).
- `lanspike-G`: a Linux guest with the fixed MAC of its bridge port (02:42:c0:a8:96:0a, address .10), `lanspike-Tlisten`:
  the listener in T's namespace (`--network container:lanspike-T`, `--cap-drop ALL --cap-add NET_BIND_SERVICE`).
- The stock render on the rig reproduces the real guest's behaviour: ARP for .200 answered with the bridge MAC, ping and TCP
  dropped by the input `counter drop`, .203 silent.

#### Case 1 results (rig; ARP and MAC also confirmed on the real Windows guest above)

| Check | Result | Evidence |
|---|---|---|
| Local `/32` routes make a fake address answer ARP, ICMP and TCP | PASS | `ip route add local 192.168.150.200/32 dev lo`; G: `TCP ...200:445 CONNECTED banner=b'HELLO 192.168.150.200:445 from 192.168.150.10'`, `ping ... ttl=64` |
| Address with no route stays silent | PASS | `.203`: neighbour `FAILED`/`INCOMPLETE`, TCP TIMEOUT, ping 100% loss, on raw, none and inetsim |
| `dev lo` vs `dev tt-guest` | both work, use `dev lo` | ARP is answered by the local route alone; on the real stack also `dev tt-guest` answered |
| MAC of every fake address | the bridge's MAC | real guest: `arp -a` `52-54-00-8f-4c-05` for .1 and .200-.202; rig: `ee:50:de:f0:b4:a0` = `tt-guest` MAC |
| TTL of ICMP replies | 64 (Linux default) | `64 bytes from 192.168.150.200: ttl=64`. Fixable to 128: nft table `type route hook output priority -150` with `oifname "tt-guest" ip saddr @fake_hosts ip ttl set 128` gave `ttl=128` for the fake addresses and `ttl=64` for the gateway |
| Route `raw` (no rooter rule), prototype ruleset | PASS | allowed pair connects, other port, other host and unallowed address time out |
| Route `none`/`drop` | FAIL until fixed (finding B) | ARP resolves, `TCP .200:445 TIMEOUT`, `ping` 100% loss; `iptables -S OUTPUT -v`: `-d 192.168.150.10 ... CAPE-rooter -c 8 528 -j DROP` counted the SYN-ACKs |
| Route `inetsim` | FAIL until fixed (finding C) | `TCP .200:445 CONNECTED banner=HELLO 192.168.150.1:1`, also `.201:3389`, a port the guest is NOT allowed: INetSim answers instead of the fake host and the port filter is bypassed |

**Finding B: the rooter's `drop_enable` blocks every reply from a local fake host.** `iptables -A OUTPUT -d <guest> -j DROP`
(after two accepts for tcp 8000 and sport 2042). The replies are local OUTPUT traffic, so they die there. An accept in an nft
table cannot beat an iptables drop (finding A). Fix that works and survives the rooter: an iptables rule with a comment other
than `CAPE-rooter`, inserted first:

    iptables -I OUTPUT 1 -m iprange --src-range 192.168.150.200-192.168.150.247 -d 192.168.150.10 -m comment --comment tartarus-lan -j ACCEPT

Result on route `none`: all three allowed connections and pings answered, `.202` still silent. The rooter's own
`cleanup_rooter()` (run at rooter start) rewrote iptables without every `CAPE-rooter` line and kept this rule
(`iptables -S | grep tartarus-lan` before and after). `iprange` works in this kernel (xt_iprange).

**Finding C (the key question, plan finding 3): yes, the inetsim route rewrites traffic to a fake address.** The rooter rules
match only the guest's source address:

    -t nat -A PREROUTING -s 192.168.150.10 -p tcp --syn ! --dport 2042 -j DNAT --to-destination 192.168.150.1:1
    -t nat -A PREROUTING -s 192.168.150.10 -p udp ! --dport 2042 -j DNAT --to-destination 192.168.150.1:1
    -t nat -A PREROUTING -s 192.168.150.10 -p icmp --icmp-type any -j DNAT --to-destination 192.168.150.1:1
    (plus tcp/udp 7,9,13,17,19,21,22,25,37,69,79,80,110,113,123,443,465,514,990,995,6667 -> 192.168.150.1, dns 53 -> :5353)
    -A INPUT -s 192.168.150.10 -p tcp --dport 22 -j DROP        (also from `inetsim_enable`)

Two fixes were tested, both in a table of ours that runs before the iptables-nft nat chain (which is at priority -100):

1. NAT bypass by identity DNAT, priority below -100, tested and working:
   `table ip tartarus_lanspike { chain pre { type nat hook prerouting priority -110; iifname "tt-guest" ip saddr . ip daddr @lan_pairs dnat to ip daddr } }`
   The mapping now exists, so the rooter's later DNAT does nothing: `TCP .200:445 CONNECTED banner=HELLO 192.168.150.200:445`,
   `.201:3389` times out again.
2. `notrack` in a raw-priority table (recommended, no conntrack entries for scan floods, no NAT at all):
   `table ip tartarus_lanspike_raw { chain pre { type filter hook prerouting priority -300; iifname "tt-guest" ip saddr . ip daddr @lan_pairs notrack }
   chain out { type filter hook output priority -300; oifname "tt-guest" ip saddr @fake_hosts notrack } }`
   Same result. Both directions must be untracked. It works because the input chain accepts by pair and port, not by ct state.

SSH (port 22) on the inetsim route additionally needs an iptables INPUT accept, because the rooter's `INPUT -s guest --dport 22 -j DROP`
runs after DNAT/notrack and also hits traffic to the fake host:
`iptables -I INPUT 1 -s 192.168.150.10 -m iprange --dst-range 192.168.150.200-192.168.150.247 -m comment --comment tartarus-lan -j ACCEPT`.
Without it `TCP .200:22 TIMEOUT` (counter on the rooter's DROP went 0 -> 3), with it `CONNECTED`.

So the iptables rules (OUTPUT and INPUT accept for the fake block) and a nat/raw bypass are all required, and none of them
can live in `tartarus_guest`'s nft chains alone: only the sets go there. They must be added and removed by the same code that
applies the firewall.

#### Case 2 results (rig, prototype ruleset)

The prototype adds to `tartarus_guest` (sets `lan_tcp`, `lan_icmp` in the inet table; `fake_block` interval
192.168.150.200-.247 and `lan_pairs` in the bridge table; full diff `firewall_proto.diff` in the scratchpad):

    inet input, after `ct state established,related accept`:
        ip saddr . ip daddr . tcp dport @lan_tcp accept
        ip saddr . ip daddr @lan_icmp icmp type echo-request accept
    bridge arp_from_guest, right after the port_macs check:
        arp saddr ip @fake_block counter drop
        arp daddr ip @fake_block arp saddr ip . arp daddr ip != @lan_pairs counter drop
    bridge ip_from_guest, after the dhcp rule:
        ip saddr @fake_block counter drop
        ip daddr @fake_block ip saddr . ip daddr != @lan_pairs counter drop

The accept for a pair is deliberately NOT a bridge `accept` (that would skip the spoofing checks below it: my first draft did
that); the bridge only drops what is not allowed and lets the existing rules judge the rest.

| Check | Result | Evidence |
|---|---|---|
| Allowed (guest, host, port) passes, nothing else | PASS | `.200:445`, `.200:3389`, `.200:22`, `.201:445` CONNECTED; `.201:3389` (host allowed, port not) TIMEOUT; `.202:445` TIMEOUT |
| An address of the block that is not allowed for this port is silent at ARP | PASS | `ip neigh`: `.202 FAILED`, `.203 INCOMPLETE`; counter on `arp daddr ip @fake_block ... != @lan_pairs ... drop` increments |
| Not-allowed host with a static neighbour entry for the bridge MAC (hairpin trick) | PASS | `ip neigh replace .202 lladdr <bridge mac> nud permanent`: `TCP .202:445 TIMEOUT` even after temporarily adding an input accept for `.202:445`, so the bridge IP rule is an independent layer |
| Guest takes a fake address as its own | PASS | `ip addr add 192.168.150.200/24`: `ping -I 192.168.150.200 gateway` 100% loss, `arping -U -s .200` unanswered, counter on `ip saddr @fake_block counter drop` 2-4 packets; same for the not-allowed `.202` |
| Control: an invented address outside the block (verify-isolation's `.250`) | PASS (still works) | `ping -I 192.168.150.250 192.168.150.1`: 2/2 replies, as today |
| Gateway-only for the rest | PASS | a canary on a second address of the container (172.30.0.2:8000, plays CAPE web) reached via the gateway: TIMEOUT on routes raw and none, with the prototype ruleset; wildcard listener `0.0.0.0:8001` addressed to the gateway or to `.200`: TIMEOUT. Control from inside the container: reachable |
| Existing `tartarus_guest` untouched on the real stack | PASS | `nft list table inet|bridge tartarus_guest` before and after, counters stripped, identical (re-checked at the end) |
| Stock ruleset on the rig = real behaviour | PASS | see above |

Design notes for Step 2 from the prototype: (a) render the `lan_*`/`fake_block` sets and rules only when at least one session
exists, so the no-session ruleset stays byte-identical to today's (the plan asks for that; my prototype always emitted the empty
sets); (b) a design choice to settle: with no session the whole block stays unreachable as today (no rule needed, nothing answers); (c) `fake_block` and
the pairs need the address block from the presets, not a literal `.200-.247`, because `GUEST_SUBNET` is configurable.

### Case 3, container vantage point (Linux tools against stand-ins in the cape namespace)

Stand-ins run in throwaway containers with `--network container:tartarus-cape --cap-drop ALL --cap-add NET_BIND_SERVICE --user 0`
(image `lanspike:tools2`: impacket 0.13.1, asyncssh 2.24.1, ldap3 2.9.1, pyasn1, cryptography), bound to 192.168.150.200 (local
`/32` route in cape). Clients run from `lanspike:tools3` (adds netexec 1.5.1 from git, which ships its own impacket 0.14.0.dev;
NetExec is not on PyPI under `netexec` for this Python, `pip install git+https://github.com/Pennyw0rth/NetExec` works).
Scripts: `smb_standin.py`, `others.py`, `ntlmhelp.py` (copied to `docs/history/fake-lan-notes/standins/` at the end).
This traffic bypasses the guest rules, so it proves only what a service answers.

#### SMB 445: impacket `SimpleSMBServer` + 3 patches (PASS for smbclient, nxc, psexec up to the point of no execution)

Library: impacket (license "Apache modified", see its LICENSE; it is Fortra's modified Apache 1.1 text, to be listed in
THIRD_PARTY.md), already used by this class of tools. Out of the box it is NOT enough:

| What the tool does | Stock SimpleSMBServer | Fix needed (tested) |
|---|---|---|
| any login accepted, NTLM material logged | yes: `admin::WORKGROUP:aaaaaaaaaaaaaaaa:<ntproof>:<blob>` (hashcat 5600 format), user, domain, tree connects, pipe names, file names go to the log | none; the challenge is the constant `aaaaaaaaaaaaaaaa` unless `setSMBChallenge("")` (random, used) |
| session flags | every accepted login is a **Guest** session (`SessionFlags=1`) because no credentials are configured; impacket 0.14 psexec aborts "Authenticated as Guest. Aborting", nxc prints `(Guest)` | wrap `SMB2_SESSION_SETUP` and clear `SessionFlags` |
| psexec `findWritableShare` | opens `\` with `FILE_WRITE_DATA|FILE_DIRECTORY_FILE`: IPC$ is "writable" (wrong, psexec then uploads to IPC$ and fails), ADMIN$ fails with `EISDIR` | wrap `SMB2_CREATE`: IPC$ refuses anything but the known pipes, a directory open for write is downgraded to read attributes |
| `\pipe\svcctl` (psexec, smbexec, nxc "Pwn3d!") | not served: `STATUS_NO_SUCH_FILE` right after the IPC$ tree connect, tool stops | a `DCERPCServer` for svcctl: OpenSCManagerW (15), CreateServiceW (12), OpenServiceW (16), StartServiceW (19), DeleteService (2), QueryServiceStatus (6), CloseServiceHandle (0), REnumServicesStatusW (14, needed by nxc); about 40 lines |
| concurrent clients | impacket's `DCERPCServer` serves **one connection at a time**: a client that keeps a pipe open blocks every other (psexec opens svcctl twice, it hung) | per-connection thread (`serve`/`run` override) |
| server identity | random host name and domain on each start (`VSMGJVME`/`neUkTTyo`), `SMBv1:True`, `Null Auth:True` in nxc's banner | needs the preset's name and domain, and SMB1 off (not done) |
| file writes | written to a real directory under the share path, any size, the path the client sends | must be replaced by a capped virtual file store in the daemon (hash, size cap, never a client-chosen host path); a tmpfs `/srv` with `size=64m` was only the spike's guard |

Results with the three patches and svcctl:

| Tool | Result | Last step reached |
|---|---|---|
| `nmap -sV -p445` | PASS `microsoft-ds`; `smb-protocols` lists SMBv1 and 2:0:2 | |
| `smbclient -L`, `smbclient //h/C$ -c ls`, `put p.exe` into ADMIN$ | PASS | file lands in the share |
| `nxc smb -u admin -p ...` | PASS `[+] ...\admin:Passw0rd (Pwn3d!)`, `--shares` lists ADMIN$/C$/DATA READ,WRITE | `-x whoami` goes through wmiexec by default: needs TCP 135 (DCOM), refused: stops there |
| `psexec.py` | PASS up to the point of execution | `Found writable share ADMIN$`, `Uploading file dhFOXfZh.exe` (56 KB RemCom binary in ADMIN$, never executed), `Opening SVCManager`, `Creating service BSSh`, `Starting service BSSh`, then it waits for the `RemCom_communicaton` pipe until its own timeout |
| `smbexec.py` | PASS: service created and started, the log has the whole command | `svcctl CreateServiceW name=VjizNpEO binary=%COMSPEC% /Q /c echo cd ^> \\%COMPUTERNAME%\C$\__output_LnKvsenZ 2^>^&1 > %SYSTEMROOT%\RWnARetT.bat ...`; fails afterwards reading the output file |
| `wmiexec.py` | FAIL: `Connection refused` on 135 | needs an endpoint mapper and DCOM activation (ORPCTHIS, IRemoteSCMActivator, IWbemServices): not a cheap addition; leave it unanswered or answer only on 135 with a fault |

What the log gives (all from impacket's own logging plus ours): NetNTLMv2 hash with user and domain, tree connects, file creates,
pipe names, and from the fake svcctl the service name and the **binary path** (the actual command for smbexec, the uploaded
file name for psexec). That is the lateral-movement evidence the normaliser wants.

#### SSH 22: asyncssh (PASS)

Library asyncssh 2.24.1 (EPL-2.0 or GPL-2.0-or-later, dual: use under EPL-2.0). Server: `begin_auth`, `password_auth_supported`,
`validate_password` always True and logged, `validate_public_key` logs the fingerprint and refuses, `process_factory` logs
the command and exits 0 with no output, `server_version="OpenSSH_8.9p1 Ubuntu-3ubuntu0.10"`, an ed25519 host key made at
start. `nmap -sV` prints `OpenSSH 8.9p1 Ubuntu 3ubuntu0.10 (Ubuntu Linux; protocol 2.0)`; `ssh h cmd` returns 0 and the command
is in the log; `nxc ssh` prints `[+] root:hunter2` (it believes the login); interactive shell closes at once; sftp/scp
refused (`subsystem request failed`). Nothing to execute exists in the process.

#### LDAP 389: ldap3's ASN.1 classes, hand-rolled server (PASS for rootDSE and bind, search empty)

No LDAP server library worth using: `ldap3` is client side only (LGPL-3.0), but its `ldap3.protocol.rfc4511` pyasn1 classes decode
requests and encode responses, so the server is about 60 lines (BER framing, `LDAPMessage` decode, bind, search, unbind). pyasn1 is BSD-2.
Minimum replies: anonymous or simple bind -> success; rootDSE base search -> one entry (defaultNamingContext,
rootDomainNamingContext, configurationNamingContext, schemaNamingContext, namingContexts, dnsHostName, serverName,
supportedLDAPVersion, supportedSASLMechanisms, domain/forest/DC functionality, ldapServiceName); base search of the domain DN ->
one entry; anything else -> done with no entries. Results: `ldapsearch -x -b '' -s base` prints the rootDSE, the bind with
`CORP\admin` then base search prints the domain entry, `nmap --script ldap-rootdse` prints all attributes and `(Anonymous bind OK)`,
`nxc ldap` reads `DC01 / corp.local`, and then needs the NTLM bind. For NTLM both forms were implemented (`sicilyNegotiate`/`sicilyResponse`,
and SASL `GSS-SPNEGO`/`NTLM` with the challenge in `serverSaslCreds` inside an SPNEGO NegTokenResp): the hash is logged and the bind
answers 49 invalidCredentials; `nxc ldap` then prints `[-] corp.local\admin:Passw0rd`. Before adding `configurationNamingContext` nxc
died with `KeyError: 'configurationNamingContext'`: that attribute is mandatory for nxc.
NOT done: simple bind never fails, no search below the domain DN (so BloodHound/ldapdomaindump-style enumeration sees an empty domain).

#### MSSQL 1433: hand-rolled TDS (PASS for prelogin, SQL login, `SELECT @@version`, NTLM capture)

OpenCanary's `mssql.py` (BSD-3, 464 lines, Twisted + ntlmlib) was read and rejected: it only logs and always answers "login failed",
and drags Twisted. Hand-rolled (about 80 lines): prelogin reply (VERSION 15.0.x, ENCRYPTION = NOT_SUP so no TLS, INSTOPT, MARS),
Login7 parse (host, user, de-obfuscated password, app, SSPI token), reply LOGINACK + ENVCHANGE (database, packet size) + INFO + DONE, SQL batch
reply (`@@version` -> one NVARCHAR row, anything else -> DONE), SSPI path (Login7 with an SSPI blob -> 0xED token carrying the NTLM challenge, then packet 0x11
carries the NTLM authenticate: hash logged, then an ERROR 18456 token). Detail that bit: the token layout depends on the TDS version in Login7
(impacket asks for TDS 7.1, FreeTDS for 7.3): UserType is 2 bytes and the DONE row count 4 bytes below 7.2.
Results: `nmap -sV` `Microsoft SQL Server 2019 15.00.2000.05`; `pymssql` (FreeTDS) login and `SELECT @@version` PASS; `mssqlclient.py sa:Passw0rd@h`
login and `select @@version` PASS (still prints one cosmetic `Unknown Token 0` at connect); `nxc mssql` reads `FS01 / CORP / Server 2019 build 17763`, SQL login
refused when the password is SQL auth in my SSPI path (`Login failed`), hash logged; `xp_cmdshell` queries are logged and answered with an empty DONE.
NOT done: ms-sql-info/ms-sql-ntlm-info nmap scripts fail (they want the instance/SSRP on UDP 1434 and a Windows-auth prelogin); no real result sets.

#### WinRM 5985: asyncio HTTP (PASS for curl and nxc)

Hand-rolled, no library (about 35 lines): unauthenticated request -> `401` with `WWW-Authenticate: Negotiate` and `Basic realm="WSMAN"`;
an `Identify` request without auth -> `200` IdentifyResponse (what `Test-WSMan` sends); `Authorization: Negotiate <NTLM type 1>` -> `401` carrying
the NTLM challenge; type 3 -> hash logged, `401`; `Basic` -> credentials logged, `401`. `curl --ntlm` ends in 401 and the hash is in the log;
`nxc winrm` reads `FS01 / CORP / Server 2019 build 17763` and prints `[-] CORP\admin:Passw0rd`. `nmap -sV` hung until I closed HTTP/1.0 connections
after the reply (fixed). A login that "succeeds" (a SOAP shell) is deliberately NOT offered.

#### RDP 3389: X.224 + TLS + CredSSP NTLM capture (PASS for nxc and nmap, freerdp stops)

Hand-rolled (about 60 lines, `cryptography` for a self-signed cert, `ntlmhelp.py` with impacket's `ntlm` and `spnego`): TPKT/X.224 connection confirm with
RDP_NEG_RSP `selectedProtocol=HYBRID(2)`, `StreamWriter.start_tls` with a self-signed certificate (CN FS01.corp.local), then a CredSSP TSRequest
exchange: NTLM challenge wrapped in SPNEGO inside TSRequest `negoTokens`, authenticate captured, TSRequest `errorCode=0xC000006D`. Logged: the `mstshash`
cookie (the username the client puts in the X.224 request) and the requested protocols. With only the X.224 confirm (selected SSL, no TLS) nxc says
`Probably old, doesn't support HYBRID` and freerdp fails at the TLS handshake. With TLS + CredSSP: `nxc rdp` -> `FS01 / CORP (nla:True)`,
`[-] CORP\admin:Passw0rd (STATUS_LOGON_FAILURE)`, hash logged; `xfreerdp3 /auth-only` fails in `CONNECTION_STATE_NLA` (it wants the server's public-key echo; the
hash is captured before that); `nmap rdp-enum-encryption` says every layer SUCCESS (my server accepts whatever it is offered: a fingerprint, fix later).
NOT done: no session beyond CredSSP, no MCS/GCC.

### Case 3, Windows-guest vantage point (the result that counts)

The input chain lets a guest reach only gateway ports, so the stand-ins were bound to the **gateway address** 192.168.150.1 on ports
the chain already allows and INetSim does not use (INetSim restarted without its echo/discard/daytime/quotd/chargen/time_tcp/finger/ident/smtps/ftps/pop3s/irc
services, config backed up and restored later): SMB 7, RDP 9, WinRM 13, SSH 17, LDAP 19, MSSQL 37. To let the Windows tools use their standard ports, the
rooter's own redirect hook was used: `[inetsim] ports = 445:7 3389:9 5985:13 22:17 389:19 1433:37` in the cape container's `routing.conf`
(restored later), then `rooter-route.py enable inetsim <guest>`. The rooter then writes
`-t nat -A PREROUTING -s <guest> -p tcp --dport 445 --syn -j DNAT --to-destination 192.168.150.1:7` and so on, ahead of its catch-all. So a
connection to **any** address on port 445 lands on the stand-in, exactly the situation a fake address will be in once the identity-DNAT/notrack fix
of case 1 is in place, and the protocol the guest sees is the stand-in's.
`win` is Windows 11 25H2 (build 26200, Polish UI, WinRM stopped, no `ssh.exe`); `w10` is Windows 10 22H2 (19045, English). Both were started by me
(snapshot revert) and are powered off at the end.

| Service | Windows tool | Result |
|---|---|---|
| SMB | `net use \\gw\C$ /user:admin Passw0rd`, `dir`, `copy x \\gw\ADMIN$\payload.txt`, `sc \\gw query` (win and w10) | **FAIL after login**: the client connects, NTLM authenticates (NetNTLMv2 captured, also for the logged-on user's implicit credentials: `DESKTOP-B542SHD\Isabel`, `LAPTOP-AAEEKFQ\Patrick`), tree connects to `ADMIN$`/`C$`/`IPC$` are logged, then `System error 2148073478` / `Invalid Signature`; nothing is copied; `sc \\gw query` fails at OpenSCManager `1722 RPC server unavailable` (it also needs the endpoint mapper on 135). Same result with `RequireSecuritySignature=False` on the client and with the server advertising `SecurityMode=0` (signing disabled) in the SMB2 negotiate. The same stand-in works for smbclient, nxc and psexec from Linux, so this is the Windows-vs-container disagreement the brief warned about |
| SMB with `/TCPPORT:7` | Win11 25H2 `net use /TCPPORT` and `New-SmbMapping -TcpPort` | the options exist on 25H2 (not on Win10), but the client sent nothing (error 67/64 before any packet); the rooter redirect was used instead |
| WinRM | `Test-WSMan -ComputerName gw` | **PASS**: prints the IdentifyResponse (`ProductVendor Microsoft Corporation`, `Stack 3.0`) |
| WinRM | `Test-WSMan -Authentication Negotiate -Credential` | the client refuses before sending credentials: `0x8009030e ... server identity could not be verified ... add to TrustedHosts` (an IP address is not accepted for NTLM unless it is in TrustedHosts): NTLM capture over WinRM needs a host **name** the guest trusts, or `TrustedHosts` set by the sample. `Enter-PSSession` has the same rule |
| LDAP | .NET `LdapConnection` anonymous bind + rootDSE search | **PASS**: `entries=1 defaultNamingContext=DC=corp,DC=local dns=DC01.corp.local` |
| LDAP | ADSI `[ADSI]"LDAP://gw/RootDSE"` (SASL GSS-SPNEGO) | the bind arrives (`auth=sasl`), the NTLM step was not captured (no hash line); returns nothing |
| MSSQL | `System.Data.SqlClient`, SQL auth `sa`/`Passw0rd`, `SELECT @@version` | **PASS**: full version string returned, login and batch logged (TDS 7.4, app `.Net SqlClient Data Provider`) |
| MSSQL | `SqlClient` Integrated Security | NTLM captured (`Patrick::LAPTOP-AAEEKFQ:...`), then `Login failed for user ''` |
| RDP | raw X.224 request with RDP_NEG_REQ(HYBRID) | **PASS**: reply `03 00 00 13 0e d0 ... 02 00 08 00 02 00 00 00` (CC + RDP_NEG_RSP selecting HYBRID) |
| RDP | `mstsc /v:gw` with a stored credential (through the agent, no desktop) | connected twice (`mstshash=admin`, requested protocols 11 and 1), then reset the connection during TLS: no certificate prompt can be answered; the CredSSP capture from a Windows client is **not proven** (nxc and freerdp from Linux did prove it) |
| SSH | no OpenSSH client on either guest; raw socket read | banner `SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.10`; a real client was not available |

Summary of what a Windows sample sees today: the services answer and log (WinRM identify, LDAP, SQL, RDP negotiation, SSH banner), credentials
and NTLM material are captured on SMB, MSSQL, WinRM (when the client sends them) and RDP, **but Windows' own SMB client does not get past the signature check**
against a server that accepts any password, so `net use`/`copy`/`sc` stop after the logon, on both Win10 22H2 and Win11 25H2. Hypotheses, not isolated: NTLM-derived
signing/MIC integrity (the server cannot derive the key without the password), SMB 3.1.1 pre-auth integrity on the session-setup response, or the guest-flag
handling. What would settle it: a packet capture decoded in Wireshark, or a run with a server that knows one password and signs (impacket's `SimpleSMBServer.addCredential`
with a matching password); I did not run either.

#### Case 3 addendum: what settles the SMB signature failure (tested on w10)

The stand-in was restarted with one registered account (`SimpleSMBServer.addCredential("admin", ..., nthash("Passw0rd"))`, so it can derive the NTLM session key
and sign) and Windows 10 22H2 ran `net use \\gw\C$ /user:admin Passw0rd`, `dir \\gw\C$`, `copy hosts \\gw\ADMIN$\payload.txt`:

    The command completed successfully.   Directory of \\192.168.150.1\C$ ... 23/11/2026 14:25 <DIR> Windows
    1 file(s) copied.                      (payload.txt, 824 bytes, present in the stand-in's ADMIN$ share directory)
    sc \\192.168.150.1 query  ->  [SC] OpenSCManager FAILED 5: Access is denied.

So the "Invalid Signature" above is the server not knowing the password: **Windows signs SMB with a key derived from the password, and a server that accepts any
password cannot sign back**, whatever the client's `RequireSecuritySignature` and the negotiate's SecurityMode say. Consequences for the preset format and the SMB service:
accounts with known passwords per fake host (the domain's well-known weak accounts, e.g. `Administrator` / `Password1`, plus anything the preset lists) behave as on a real host
(share access, file writes, ADMIN$ drops all work from the Windows client); a login with any other password is a logon failure, as on a real host, and the NetNTLMv2 material is
still logged. "Accept any login" works only for clients that do not sign (smbclient, nxc, impacket tools; and it needs the Guest flag cleared). Optionally the server can test the
received NTLMv2 proof against a short dictionary and grant the session when one matches (not tried). Second finding: `sc \\host` (Windows) opens svcctl with an **authenticated** (NTLM, sealed)
RPC bind, which impacket's `DCERPCServer` does not implement: `OpenSCManager` returns 5 even though impacket's clients (which bind without authentication) pass. A fake that is to satisfy
`sc.exe` and `psexec` from Windows needs NTLM-authenticated RPC on the pipe (sign/seal with the session key it can derive only for known passwords). Deliberately left out for v1:
PsExec-style behaviour from Windows against a known-password account is logged up to the service creation attempt; execution is never offered.

### Case 4: names

INetSim edited in the running container: `cp -p /etc/inetsim/tartarus.conf /tmp/tartarus.conf.orig` (md5 7a0b9a2e...), appended `dns_static fs01.corp.local 192.168.150.200` and
`dns_static dc01.corp.local 192.168.150.201`, `supervisorctl -c /etc/supervisor/supervisord.conf restart inetsim`. Restore: copy the backup back and restart (done at the end).

| Check | Result | Evidence |
|---|---|---|
| `dns_static` with an FQDN answers the fake address | PASS | `nslookup fs01.corp.local 192.168.150.1` -> `192.168.150.200`; `Resolve-DnsName fs01.corp.local` -> `192.168.150.200` |
| `ping fs01.corp.local`, `Test-NetConnection fs01.corp.local -Port 445`, `net use \\fs01.corp.local\C$` + `dir` reach the fake host | PASS (win, with a known-password stand-in) | `Reply from 192.168.150.200 ... TTL=64`, `TcpTestSucceeded True`, `net use` success and `dir \\fs01.corp.local\C$` listing the stand-in's `Windows` directory. The SMB step needed the rooter redirect `445:7` of case 3 because the stand-in was bound to the gateway; with the case 1 fix the connection would go to the fake address itself |
| A **single-label** name (`fs01`, `FS01`) | FAIL: `dns_static` cannot serve it | (1) INetSim refuses to start at all: `Error: 'fs01' is not a valid FQDN hostname in configuration file ... line N` (a bad `dns_static` line stops **every** INetSim service, so the preset renderer must validate names and emit only FQDNs). (2) `nslookup fs01 gw` answers INetSim's default IP 192.168.150.1, not the fake host. (3) The guests have no primary DNS suffix, so Windows does not send a single-label name to DNS at all: `ping fs01` / `net use \\FS01\C$` / `Test-NetConnection fs01` / `Resolve-DnsName fs01` all fail with "could not find host" / error 53/67 / `ERROR_INVALID_NAME` |
| Broadcast name resolution for single labels | the guest sends it, nothing answers | capture on `tt-guest` while `ping fs01` runs: mDNS `224.0.0.251:5353` (`A? fs01.local`), NBNS broadcast `192.168.150.255:137` (3 times), LLMNR `224.0.0.252:5355`. A listener bound to `0.0.0.0` on UDP 137, 5355 and 5353 (with the multicast groups joined) in the cape namespace received **0 packets** in 20 s, and the input chain's drop counter did not move (unjoined multicast and the bridge never deliver them to a socket, and nothing in the chain accepts them): so with the shipped firewall NetBIOS/LLMNR cannot be answered by a fake host, as plan finding 6 says. Answering them would need an input accept for those UDP ports and the multicast/broadcast destinations, and a responder on them; not tried |
| INetSim serves SRV | FAIL | `nslookup -type=SRV _ldap._tcp.dc._msdcs.corp.local gw` -> `Not implemented`; and `dns_static` refuses names with underscores (`'_ldap._tcp.dc._msdcs.corp.local' is not a valid FQDN hostname`, INetSim then does not start) |
| Unknown names | INetSim answers its default IP for any FQDN | `nslookup unknownhost.corp.local` -> 192.168.150.1; `dns_default_ip 192.168.150.1` |

Which lateral tools need a name: `net use`/`dir`/`copy` to `\\host\share` and `sc \\host`, `PsExec \\host`, `Enter-PSSession`/`Invoke-Command -ComputerName` (and Windows refuses NTLM to a bare IP
there unless TrustedHosts allows it), Kerberos anything, `wmic /node:`, AD discovery (`nltest /dsgetdc`, `_ldap._tcp.dc._msdcs` SRV, which cannot work), and every sample that enumerates the network
by name (`net view`, `NetServerEnum`, which rely on NetBIOS browsing, unanswered). Tools that work with the bare IP: SMB `net use \\192.168.150.200\C$`, `Test-NetConnection`, raw socket clients, `sc`/`psexec` with an IP,
RDP/SSH/LDAP/SQL with an address. Malware that scans /24s and then uses discovered IPs (the common worm pattern) needs no name.

### Case 5: floods

Container side: stand-ins on 192.168.150.200 in the cape namespace (SMB = SimpleSMBServer, others = `others.py`), clients in `lanspike:tools2/3` with
`--network container:tartarus-cape`. Guest side: PowerShell on `win`. Spike code is Python threads/asyncio in one process each, so these are the numbers of a
prototype, not of the final daemon.

| Measurement | Result |
|---|---|
| `nmap -sT -p-` / `-sS -p-` against one fake host (65 535 ports) | 0.9 s / 0.7 s. The daemon logged **6 events** for `-sT` (one connect per listening port) and **0** for `-sS` (half-open, never accepted). A daemon that binds only its services never sees a probe of a closed port: the kernel answers RST. The scan itself is visible only in CAPE's pcap/flows (or an nft counter/log rule), as plan finding 9 assumes |
| `nmap -sT/-sS` six ports over the whole /24 from the container | 0.8 s / 0.5 s; not representative (local namespace) |
| 10 000 SMB logins (impacket client, 8 processes, new connection each) | 27.7 s, **361 logins/s**, SimpleSMBServer at **~105 % CPU** (one Python process, GIL-bound) and **55 MiB**, 111 threads during the run and 4 afterwards (no leak). The client side limited the rate, not necessarily the server |
| Log volume | SimpleSMBServer's own logging: **61 MB for 10 000 logins = 6.1 MB per 1000 events** (6 DEBUG-level lines of ~1 KB per login, mostly the NTLM blob). Our JSONL lines are 88 B for a connect (2.66 MB for 30 013 lines) and roughly 450 B for a login with an NTLMv2 hash: **0.09 to 0.45 MB per 1000 events**. impacket's logging must be replaced by ours |
| 5000 raw connects per service, 8 threads, no handshake completed | SSH 188/s (asyncssh does key exchange per connection), LDAP ~405/s, MSSQL ~350/s, WinRM ~405/s, RDP ~375/s; `others.py` stayed at 42 MiB, 2 PIDs, ~0 % CPU afterwards; 30 013 JSON lines. TIME_WAIT sockets after the runs: 7 806 (the daemon closes first); not a problem at these volumes |
| Guest scan: PowerShell, 253 hosts x ports 445, 3389, 22, all connects started at once | 759 connects started in 4.5 s (**~170 connects/s**, PowerShell-bound); the guest put **1 418 ARP requests** (about 5.6 per absent address: Windows retries) and only **89 SYNs** on the bridge, because only addresses that answer ARP get TCP. Unanswered /24 sweeps are therefore ARP noise in the pcap, not events in the daemon; a worm-style native scanner can start thousands of connects per second but reaches at most the preset's hosts and open ports (<= 48 hosts x ~6 services) |
| Route effect | on `inetsim` with the default catch-all every connect to a live (ARP-answering) address goes to INetSim port 1 and is "open"; with the case 1 fix the fake host answers instead |

Proposed numbers (from the data above, to be tuned once the real daemon exists):
- **Per connection**: bytes read capped at 64 KiB per connection and 30 s idle timeout; SMB file writes capped at 16 MiB per file and 64 MiB per session (hash everything, keep nothing beyond the cap, never execute, never a client-chosen host path).
- **Concurrency**: at most 32 concurrent connections per (source, service) and 512 in total per session; beyond that accept-and-close (or let the backlog fill) and count.
- **Rate**: individual events up to **200 events/s per session**; above that count only (a 361/s prototype already saturates one core).
- **Event cap**: the first **200 events per (session, fake host, service)** are logged in full; the next ones only increment a counter in a per-(host, service) aggregate (count, first/last time, up to 50 distinct usernames, up to 5 distinct passwords/hashes). A hard cap of **20 000 JSONL events or 8 MB per session**, then the session's final record carries only the counters. 8 MB is about 18 000 login lines with a hash.
- **Derived events** (no aggregation in the matcher): `lan-sweep` when one process contacts **>= 5 distinct fake hosts on the same port within 30 s** (a three-port PowerShell scan of the preset reaches all hosts in under 5 s, so this triggers in practice; a legitimate single connection to a file server does not); `lan-fan-out` when **>= 4 distinct hosts over >= 2 services within 5 min**; credential spray (T1110.003) when **>= 3 distinct hosts see login attempts with the same username within 5 min**. Sweeps are counted from CAPE's connect flows and ARP as well, since the daemon never sees a closed port.

### Case 6: attribution (CAPE task, real Windows guest, route inetsim, local routes for .200-.205 present)

First two attempts did not run the sample usefully (not a finding about fake hosts): task 168 (`ps1` package, `powershell.exe -File`) sat in PowerShell start-up
until the 70 s timeout; task 169 (`python` package) died with `ModuleNotFoundError` in the guest's `python.exe`. Task 170: a 15 KB mingw `lanprobe.exe`
(connect to .200:445, .201:445, .200:3389, .202:22, send 9 bytes, close) as package `exe`, timeout 50. All three tasks, their analysis folders and the three
binaries in `storage/binaries` were deleted afterwards.

| Check | Result | Evidence |
|---|---|---|
| CAPE `network.tcp[]` has the flows to fake addresses | PASS, but **without a process** | three entries `{src, sport, dst, dport, offset, time}` (`192.168.150.10:58882 -> 192.168.150.200:445` and so on): no pid, no name. `network.hosts` is empty, `dead_hosts` is `[['192.168.150.202', 22]]` (the unanswered SSH attempt) |
| CAPE behaviour calls carry the process and the target | PASS | `behavior.processes[lanprobe.exe pid 9640]` has `connect {socket, ip: 192.168.150.200, port: 445}`, `send`, `closesocket`, also for the unanswered `.202:22` (no source port in the call, only the socket handle) |
| Sysmon EID 3 carries the process | PASS for **established** connections only | 3 events with a fake destination: `ProcessId 9640`, `Image ...\Temp\lanprobe.exe`, `User DESKTOP-B542SHD\Isabel`, `Protocol tcp`, `Initiated true`, `SourcePort 58882/58884/58891`, `DestinationIp 192.168.150.200/.201/.200`, `DestinationPort 445/445/3389`. The unanswered `.202:22` attempt has **no EID 3** (Sysmon logs a connection when it is established) |
| pcap flows | PASS | `dump.pcap` has all four targets; the three answered ones complete the handshake, `.202:22` shows five SYN retransmissions (1, 3, 7, 15 s) |

Attribution therefore works the way `cape-network` already does it for any other address: join the pcap flow (`sport`) with Sysmon EID 3 (`SourcePort`, pid, image),
and use capemon's `connect` calls for attempts that never established. Nothing in this depends on the destination being a fake address. The `lan-sim` log has no pid:
the normaliser must key its events on `(guest source port, dst ip, dst port)` and take the process from the flow, as plan finding 9 says.

Real-stack confirmation of case 1 from this task (real Windows guest, real firewall, route `inetsim`): the guest's SYN to `192.168.150.200:445` was **answered by 192.168.150.200** in the
pcap (`Flags [S.]` from .200:445) although only a local `/32` route exists and no listener on .200: the rooter DNATs it to INetSim port 1 and the reply is un-NATed, so the connection
completes and looks like a live SMB host that says nothing. The SSH attempt to `.202:22` got no answer at all, because of the rooter's `INPUT -s <guest> --dport 22 -j DROP`. That is Finding C on the real stack.

### Re-check from a clean state (the two most important checks)

After removing every container, network and route of the spike I built the rig again from scratch (new network, new `tt-guest` bridge, real `ip filter` rules and `tartarus_egress`, fresh stock and prototype
rulesets, fresh listener) and ran: (A) stock firewall, raw route: `TCP .200:445 TIMEOUT`, ping 100% loss. (B) prototype `tartarus_guest`, raw: `.200:445` CONNECTED with the banner of the real fake
address, `.201:3389`, `.202:445`, `.203:445` TIMEOUT; route none without the iptables fix: TIMEOUT; route inetsim without the fix: `CONNECTED banner=HELLO 192.168.150.1:1` for `.200:445` **and for the
not-allowed `.201:3389`**. (C) with the iptables OUTPUT/INPUT accepts and the notrack table: none and inetsim both give `.200:445` and `.200:22` CONNECTED with the fake host's own banner, `.201:3389` and `.202:445`
TIMEOUT, ping to `.200` answered, a guest that takes `.200` as its own: 100% loss. All as in the first run.

### Cleanup

Closed the rooter routes of both guests (before restoring `routing.conf`, whose `ports` line they were built with), restored `/opt/CAPEv2/custom/conf/routing.conf` and `/etc/inetsim/tartarus.conf` from
backups (md5 `addc299b...` and `7a0b9a2e...` match the originals), restarted INetSim (`RUNNING`, 20 listeners on 192.168.150.1), destroyed `win` and `w10`, removed the local `/32` routes, every
throwaway container and the docker network `lanspike-net`, the images `lanspike:tools/tools2/tools3`, the uploaded `.ps1` files inside the guests (they were in the reverted snapshot state, which `win` and `w10` lose
at the next revert), `/tmp` files in cape, the CAPE tasks 168-170 and their three binaries, the pcaps. Then `guest-firewall init` (both guests off). `nft list tables` in cape is the starting set (inet
tartarus_guest, bridge tartarus_guest, inet tartarus_egress, ip/ip6 filter/nat/mangle), the rule text of `tartarus_guest` (both tables) and `tartarus_egress` is identical to the baseline with counters stripped
(only the listing order of the two tables changed after `init`), `iptables-save` is identical to the baseline, and `docker compose ps` shows the five services healthy. No memory dumps were made.

## Summary per case

| Case | Verdict | Decisive evidence |
|---|---|---|
| 1 Mechanism | PASS with two required fixes | local `/32` route answers ARP with the bridge MAC (real guest), TTL 64 (fixable to 128); the inetsim DNAT rewrites every destination (real guest: answered by INetSim from .200, SSH dropped); `drop`/`none` drops all replies in iptables OUTPUT; fixes tested on the rig |
| 2 Filtering | PASS on the rig, brief's premise FAIL | sets with `guest . host . port` in `tartarus_guest` input and `guest . host` in the bridge table; an early accept in another table is useless; spoofed fake address dropped; canary on the container's other address unreachable |
| 3 Fidelity | PASS per service for the cheapest stand-ins, FAIL for Windows SMB with accept-any-login | see the table of Windows results and the SMB addendum |
| 4 Names | PASS for FQDN, FAIL for single labels and SRV | `dns_static` FQDN works, bad line kills INetSim, NetBIOS/LLMNR unanswerable |
| 5 Floods | numbers obtained | 361 logins/s and 6.1 MB per 1000 logins with impacket logging, 88 B per connect event with ours; proposed caps above |
| 6 Attribution | PASS | Sysmon EID 3 carries pid/image for established flows; `tcp[]` has no process; capemon `connect` calls cover the rest |

## Library choices and licenses (for THIRD_PARTY.md / docs/licenses.md)

| Service | Library | License | Note |
|---|---|---|---|
| SMB | impacket 0.13.1 (`SimpleSMBServer`, `DCERPCServer`, `ntlm`, `spnego`) | Apache-style "Apache modified" (Fortra) | needs the patches listed in case 3; impacket's file writes, logging and single-connection RPC server must be replaced or wrapped; consider using only its protocol classes |
| SSH | asyncssh 2.24.1 | EPL-2.0 (or GPL-2.0-or-later) | pulls `cryptography` (needs >= a version that has `cryptography.hazmat.primitives.asymmetric.mlkem`, asyncssh 2.24 failed to import with the older one netexec installed) |
| LDAP | ldap3 2.9.1 (`rfc4511` classes only) + pyasn1 | LGPL-3.0 + BSD-2 | server side hand-written, ~60 lines |
| MSSQL | none (hand-rolled TDS) | | OpenCanary `mssql.py` (BSD-3, Twisted + ntlmlib) read and rejected |
| WinRM | none (asyncio HTTP) | | |
| RDP | none (X.224 + TLS + CredSSP by hand), `cryptography` for the certificate | Apache-2.0/BSD | |
| clients used in the spike, not shipped | nmap, smbclient, openldap, openssh, freerdp, netexec 1.5.1, pymssql | various | test tools only |

## Contradictions and spec edits

1. **Plan Step 2 / brief: "a table of ours before the iptables chains".** False for the input chain: sets and accept rules go into `tartarus_guest`'s own input chain. Only the NAT bypass can live in a table of ours.
2. **Plan finding 3 is confirmed and worse**: the rooter's DNAT is only half of it. Routes `none`/`drop` (iptables `OUTPUT -d guest -j DROP`) and `inetsim` (iptables `INPUT -s guest --dport 22 -j DROP`) each need a rule **in iptables** (comment other than `CAPE-rooter`, which the rooter's cleanup keeps), so `firewall.py` must also drive `iptables` for the fake block. nft cannot override an iptables drop.
3. **Plan finding 5 (MAC/TTL)**: TTL can be set to 128 with `type route hook output ... ip ttl set 128` for the fake addresses; the MAC stays the bridge's. Update the behaviour details accordingly.
4. **Plan finding 6**: single-label names do not work through DNS on these guests (no primary suffix), a malformed `dns_static` line stops INetSim, SRV impossible. Names in presets must be FQDNs (`fs01.corp.local`); `\\FS01\C$` style single-label access only works by IP or FQDN.
5. **Spec "fake hosts accept a login"**: Windows' SMB client signs with a key derived from the password, so an accept-any-password fake host cannot satisfy it. Presets need per-host accounts with known passwords for Windows clients to get past the logon; unknown passwords fail as on a real host and the NTLM material is logged. `sc.exe` additionally needs authenticated RPC.
6. **Plan finding 9 holds** and is sharper: the daemon sees only connections to open ports; sweeps of closed ports and of absent addresses exist only in CAPE flows and ARP.
7. **Plan Step 4 estimates**: SMB is not "negotiate + session setup + tree connect": it needs the svcctl pipe, non-guest sessions, ADMIN$ semantics, per-connection RPC threads and a capped virtual file store. RDP needs TLS and CredSSP for any credential evidence. MSSQL and LDAP are small hand-rolled parsers. WinRM, SSH are the cheap ones.

## Not tested

- Windows-guest TCP/ICMP to a **fake address** with the fixes applied on the real stack (needs `tartarus_guest` replaced; denied). The rig used a Linux guest. Windows-specific behaviour (ARP cache timing, `netsh` neighbour tricks) was not repeated on the rig.
- `w10`/`win` going through the identity-DNAT/notrack fix; two guests at once on different presets.
- Concurrent analyses and the shared daemon answering by destination address.
- `wmiexec` (needs DCOM on 135), `sc \\host` against an authenticated svcctl, `mstsc` through a TLS handshake (no desktop), SSH from Windows (no client on the guests), ADSI Negotiate and WinRM Negotiate NTLM capture from Windows, nmap `ms-sql-info`.
- The `internet` route (refused by the spec anyway); `GUEST_SUBNET` other than 192.168.150.0/24 (the prototype hard-codes the block).
- Whether the stand-in under real malware behaves (only my own benign clients were used); no hostile-input fuzzing of the stand-ins.
- Resource limits of the final `lan-sim` container (the spike used a throwaway one with `--cap-drop ALL --cap-add NET_BIND_SERVICE --user 0`, no read-only root).
