# Step 12b notes: the end-to-end proof of the fake LAN through the real app

Resume file (Done / Running / Next). 2026-11-24. Brief: a benign probe sample on a real Windows guest, submitted through the public API
with and without `lan_preset`, results checked by API and in the browser. Nothing committed.

## Baseline (before anything ran)
- compose: backend, cape, frontend, lan-sim, opensearch, postgres all healthy. Guests `win` .10 and `w10` .11 ready, off.
- cape nft tables: inet tartarus_egress, ip6 filter/nat/mangle, ip mangle/filter/nat, inet tartarus_guest, bridge tartarus_guest.
- tartarus-lan iptables rules in cape: 0. proto-77 routes in cape: 0. Exited containers that are not mine and are left alone:
  keen_clarke awesome_ellis naughty_kapitsa sad_neumann strange_haibt modest_lamport clever_chatelet heuristic_jang frosty_chaplygin
  competent_sanderson pedantic_antonelli busy_cannon strange_matsumoto great_merkle (+ momos-*).
- The API needs no token (frontend nginx on 127.0.0.1:8080 proxies /api).

## Done
- read the docs and the 12a notes.
- Step 1: sample `lan_probe.c` (source in docs/history/fake-lan-notes/step12b-sample/, targets.h generated from GET /api/lan-presets by
  gen_targets.py) built with mingw-w64 in a throwaway ubuntu:24.04 container (`step12b-build`, --rm). exe in the scratchpad `sample/out/`.
  Not run by hand first: went straight to an analysis (it logs to %TEMP%\lan_probe.log).
- Internet refusal proven before anything ran: POST /analyses route=internet + lan_preset -> 422 validation_error (lan_preset cannot be used
  with route internet); analysis total stayed 27.
- NOTE: "raw" is not an API route value (Literal none/drop/internet/inetsim/tor/vpn/wireguard/socks5); runs use `none` then `inetsim`.

- Analysis 180 (win, route none, small-office): status done, no error, 743 events, score 2.9, max severity high. summary.lan: 5 hosts, 23 attempts,
  5 credentials, 1 file (ADMIN$\tartarus-benign.exe on dc01, 42496 bytes). lan-* events and derived events present (28 with tartarus.lan.simulated).
  FINDING A: route `none` leaves no dump.pcap, so no cape.network events; the Network tab flows (taken from Sysmon EID 3) and hosts are NOT flagged
  (simulated false, lan_host null) although the daemon logged all 21 connections with matching source ports. Checking with route inetsim (run 2).
- Analysis 181 (win, inetsim, small-office): done, no error, 977 events, score 3.2. Network hosts flagged for 5 of 6 (printer01 .205 unflagged),
  only the 6 pcap flows with payload (445) flagged; 15 Sysmon/capemon bare-connect flows unflagged. lan_connect_smb fired (info); rdp/winrm/mssql/ssh
  connect rules did not. FINDING B (see report). Clock skew guest vs daemon: 180 28 s, 181 5.4 s.
- HTML report of 180 exported (job 134): has "Lateral movement" section (5 hosts, 23 attempts, 1 file).
- Step 4: analysis (no lan_preset, win, inetsim) submitted after 181.

- Analysis 182 (win, inetsim, NO lan_preset, same sample): done, no error. summary.lan null, no lansim dir, zero lan-* events, zero lan Sigma
  alerts, no lateral-movement tactic in ATT&CK, no flagged hosts/flows, HTML report has no "Lateral movement" and no fake-LAN text.
  Probe log: all 16 connects "no answer" (1.5 s timeouts), logons error 64 (network name no longer available).
- HTML reports exported for 180, 181 (both have the Lateral movement section) and 182 (none).
- Screenshots (frontend/screenshots/, git-ignored): fakelan-12b-{180,181,182}-{summary,network-hosts,detections}.png and
  fakelan-12b-181-network-flows.png.
- Step 5: no LAN session open (control service list empty), both guests shut off, nft tables equal to the baseline, 0 tartarus-lan iptables
  rules, 0 proto-77 routes, docker images equal to the baseline, step12b-build container was --rm. CAPE analyses 171-173 (30 MB, no memory dumps)
  left in place with their DB rows as evidence.

## Findings (spec mismatches)
- A. Route `none` captures no pcap, so no cape.network events: Network tab and hosts are not flagged, the lan_connect_* rules do not fire.
- B. Even with a pcap (inetsim) only flows CAPE reports as tcp (with payload) are flagged: SMB yes; bare connects to RDP/WinRM/LDAP/MSSQL/SSH
  (daemon logged all 21 connections) are not flagged, are not in summary.lan, and their lan_connect_* rules never fire; printer01 never shows.
- C. Clock skew: guest clock was 28 s behind the daemon in 180 and 5 s in 181, so lan-* events (host clock) sit seconds after the sweep (guest clock)
  that happened 0.1 s earlier; Summary first/last mixes pcap-relative and daemon times.

## Running
- nothing

## Next
- nothing from this brief
