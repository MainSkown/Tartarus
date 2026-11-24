# Step 12a notes: the isolation proof of the fake LAN on the real stack

Resume file (Done / Running / Next). 2026-11-24. Brief: extend scripts/verify-isolation.sh with a LAN section, run it for real on `win`
(Win11, 192.168.150.10) and `w10` (Win10, 192.168.150.11), run the negative proof, run the shell tests. Nothing committed.

## Done
- Stack found DOWN, not up as briefed: the host had rebooted (uptime 1 h at start, all containers exited 2026-11-23 20:31). The cape and lan-sim images
  (built 20:16) are newer than every file under cape/ lan-sim/ guest/ (find -newermt), so they hold the code under test. Started with plain
  `docker compose up -d --wait` (no build, nothing running was recreated). No analysis ran: 27 `done` in Postgres, CAPE tasks only reported/failed.
- The BACKEND image is stale (built 2026-11-14, no `lan_health`/`lan_schemas`): `compose exec backend` cannot open sessions. So sessions are opened with
  `scripts/lib/lan-session.py` in a throwaway container of the backend image on `tartarus-control`, with the working tree's `backend/app` mounted over
  the image's copy: the backend's own `HttpGuestControl`, current source, GUEST_CONTROL_TOKEN passed by name.
- Tests first: 28 of the new shell tests failed against the unchanged script; afterwards `scripts/tests/test_verify_isolation.sh` 68 ok / 0 FAIL.
- Written: scripts/lib/lan-session.py (new), scripts/lib/isolation-probe.ps1 (probe kinds `any:PORT`, `arp`; icmp pings in parallel and with an optional
  marker such as `TTL=128`), scripts/verify-isolation.sh (catalogue of every preset service from the control service's own list, multi-word scenarios,
  LAN section, header, negative-proof knob `ISOLATION_NEGATIVE_PROOF=1`, `trap 'exit 130' INT TERM`), Makefile help line.
- Live payload check before the first full run (win, small-office): all 56 probes of the preset answered as expected; controls: a RST on the guest's own
  address gives `any:` yes, a wrong marker on a live SMB service gives no, the other preset's host gives no on TCP, `any:`, ARP and ping, and a ping of the
  gateway with marker TTL=128 gives no (64) while without the marker it gives yes.
- Run 1 (step12a-run-1.txt): 55 OK, 2 FAIL, 837 s. The two failures were a bug in my new trick, not a leak: with a fake address taken as its own, probes to
  that very address are answered by the guest's own stack (its SMB service on 445, RSTs, ping TTL 128), so only `lan-200-*` / `lan-216-*` names were
  yes; every other probe (gateway, other fake hosts, canaries, internet, the other guest) was silent. Fixed (tests first: two new tests): those probes
  are left out of that check, like `claimed` lets a guest reach itself.
- Run 2 (step12a-run-2.txt): 57 OK, 0 FAIL, 3 INFO, exit 0, 824 s. Both guests, routes raw/none/inetsim, all checks green.
- Run 3 (step12a-run-3-negative-proof.txt), ISOLATION_NEGATIVE_PROOF=1: 35 OK, 22 FAIL, exit 1, 874 s; the guests' reach is named (see the file).
- After every run: guests shut off, no LAN session listed, `nft list tables` has both tartarus_guest tables again.

## Running
- nothing (`make test-scripts` result is quoted in the final report)

## Next
- nothing from this brief
