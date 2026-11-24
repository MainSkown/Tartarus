# Step 12b fix notes: Sysmon and capemon connections to a fake host get the `tartarus.lan` flag

Resume file (Done / Running / Next). 2026-11-24. Backend only, nothing committed (the planner commits).
Gaps A (route `none`, no pcap) and B (bare connects are not pcap flows) of [step12b-notes.md](step12b-notes.md).

## Design (decided by the planner)
- Every `network-connection` event whose destination ip is in `context.lan_hosts` carries `lan_section(host)`, stamped in
  `EventFactory.build` (one place; cape-network's own stamp is removed).
- `summary.lan` counts one connection once: pcap flow preferred, else Sysmon, else capemon.
- The Sigma `lan_connect_*` rules then fire on the stamped Sysmon/capemon events; the engine's (rule, process.entity_id) 60 s
  suppression already merges Sysmon + capemon + pcap of one process into one alert with a repeat count.

## Done
- read the code and the existing tests.
- step 1: tests first. `tests/ingest/test_lan_connections.py` (15, through the ingester: flag, one attempt, route none shape, Sigma
  rdp, one alert for three sources, sweep guard) and 10 new/changed cases in `tests/analyses/test_lan_summary.py`. 10 + 6 failed for the
  right reason (no `lan` key on Sysmon/capemon events, host missing from summary, no alert, attempts 1 vs 2, 3 vs 2 for daemon+flow).
- step 2: implemented. Flag in `EventFactory.build` (ecs.py), cape_network's own stamp and `_Candidate.tartarus` removed.
  `without_repeated_capemon_rows` + `key_of` moved from views/network.py into ingest/attribution.py (view imports it).
  lan_summary: connections of any source, deduped (pcap > sysmon by (ip, port, sport), capemon dropped when another source has the
  endpoint), connections last, a connection to a (host, port) the daemon logged on is not counted. Two old tests changed to the new rule
  (`test_an_attempt_is_a_login...`, `test_the_result_carries_the_lan_summary...`: login + flow on 445 is 1 attempt, not 2).
- step 3: full suite 5172 passed (282 integration deselected), mypy app clean, ruff check clean, ruff format --check clean.

- step 4: backend image rebuilt and restarted (once). POST /api/analyses/180/reingest and 181 (181 had to wait for 180: one at a time).
  Before/after, from the API:
  - 180 (none): summary.lan 5 hosts / 23 attempts -> 6 hosts / 34 attempts (printer01 ssh now listed); network hosts flagged 0/6 -> 6/6,
    flows flagged 0/16 -> 16/16; flagged events 28 -> 60; alerts 12 -> 17 (+ lan_connect smb, rdp, winrm, mssql, ssh, one each).
  - 181 (inetsim): 5 hosts / 32 attempts -> 6 hosts / 37 attempts; hosts flagged 5/7 -> 6/7 (only 192.168.150.1 is not fake); flows
    flagged 6/273 -> 22/273; flagged events 37 -> 69; alerts 14 -> 18 (+ rdp, winrm, mssql, ssh; smb was already there).
  - 182 (fake LAN off): unchanged (1007 events, summary.lan null, 0 flagged, same 8 alerts).
  - No doubled alerts: one alert per rule and process; the Sysmon + capemon (+ pcap) copies of a connect are its `repeated` count.
- step 5: Summary NETWORK > HOSTS tile = `len(report.network.hosts)` of CAPE (summary.py, since the first report-reader commit b57f191,
  2026-10-13). CAPE's `network.hosts` is 0 even with a pcap (172: hosts 0, tcp 249, dns 2); the Hosts tab derives its rows from events.
  Predates the fake LAN, not caused by it. Not fixed.

## Running
- nothing

## Next
- nothing from this brief (the planner commits; docs of summary.lan counting in data-model.md/gui.md are not touched here)
