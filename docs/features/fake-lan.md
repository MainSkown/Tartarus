# Fake local network

> **As built (2026-11-24).** The feature is built on branch `fake-lan` except the isolation proof:
> `make verify-isolation` does not yet test it (Step 12 is in progress). The implementation plan, with
> the Step 0 spike findings (S1-S10) and the decisions taken, is [fake-lan-plan.md](fake-lan-plan.md).
> The spike and step notes are in [../history/fake-lan-notes/](../history/fake-lan-notes/). The user
> guide is [guide/fake-lan.md](../guide/fake-lan.md). Where the text below says something different
> from what was built, the built version is the one that holds, and the difference is named.

## Summary
The guest today sees a gateway and nothing else, so malware that scans the LAN or tries lateral movement has nothing to touch. This feature adds a simulated local network of fake hosts (emulated services in one container, chosen from presets) so lateral-movement attempts become visible in the report, with detection rules and an ATT&CK mapping.

## Goals
- Show how a sample discovers hosts and tries to move laterally (SMB, RDP, WinRM, SSH, LDAP, MSSQL) without any real second machine.
- Surface this in the Network tab, a Summary section, Sigma alerts, the ATT&CK matrix and the exported report.

## Non-goals
- Real Windows VMs as lateral-movement targets (possible later, the design should not block it).
- A GUI editor for presets.
- Letting the sample really compromise anything: the fake hosts log attempts, they do not give the malware a working shell.
- Guest-to-guest connectivity (stays blocked).
- Sending traffic to the analyst's real LAN, ever, on any route.

## Changes

### UI / frontend
- [x] `SubmitLanFields.vue` (mounted in `SubmitDialog.vue`): a "Simulate local network" switch, off by default. When on, a preset picker is shown (presets come from the API).
- [x] Submit dialog: the switch is disabled with an explanation when the route is `internet`.
- [x] Network tab hosts list: a "fake LAN host" badge (`FakeLanBadge.vue`) on simulated hosts, and a filter-on / filter-out action for it, using the existing `FieldActions` component.
- [x] Summary: "Lateral movement" section (`LateralMovementSection.vue`), per fake host: services touched, number of attempts, first and last time, credentials or files the sample used or wrote. Empty state when the sample did nothing on the LAN; hidden when the feature was off (`summary.lan` is `null`).
- [x] HTML and PDF report export include the Lateral movement section and the flags on fake hosts.
- [x] All new strings through message keys (`frontend/src/i18n/en-US/`).

### Backend / API
- [x] `AnalysisOptions`: `lan_preset: str | None` (None = off); validated against the preset list the control service answers; refused together with route `internet`.
- [x] `GET /api/lan-presets`: list of presets (id, name, description, hosts with FQDN, address, role and services; no account or password).
- [x] Ingest source `lan-sim` implementing the `Normalizer` protocol (`backend/app/ingest/lan_sim.py`): converts the fake-host container's log into events (lane `network`, plus authentication events for login attempts) with the target host and service as ECS fields. Derived events (`lan-sweep`, `lan-fan-out`, `lan-credential-spray`) are built beside it (`lan_sim_derived.py`, `lan_derived.py`).
- [x] Field catalog (`backend/app/search/fields.py`) gets the `tartarus.lan.*` fields, so the query bar, autocomplete and the Sigma pipeline see them. The as-built names are in [data-model](../specs/data-model.md): `simulated`, `host`, `role`, `service`, `preset`, `share`, `count`, `mechanism`, `credential`, `request`, `detail`.
- [x] `backend/app/views/network.py`: hosts that belong to the preset are marked as fake; flows to them are flagged (`tartarus.lan.simulated`), whether the pcap, Sysmon or capemon saw the connection, so route `none` (no pcap) and bare connects are flagged too.
- [x] Summary: the lateral-movement aggregation is computed at the final ingest and stored as `summary.lan` (`backend/app/analyses/lan_summary.py`). It replaces the planned view endpoint (plan, finding 11).
- [x] Sigma: eleven rules in `rules/sigma/tartarus/` (`network_connection` rules for SMB, RDP, WinRM, SSH and MSSQL; admin-share access; executable written to an admin share; service created over SMB; credential spray; sweep; fan-out), tagged `attack.lateral-movement` or the matching tactic with technique ids. The ids are in `backend/app/data/attack_techniques.json`, so the ATT&CK matrix picks them up through the existing path.

### Guest network / infrastructure
- [x] Compose service `lan-sim` (`tartarus-lan-sim`): one container, built from `lan-sim/`, that shares `cape`'s network namespace (`network_mode: "service:cape"`), with `cap_drop: ALL` plus `NET_BIND_SERVICE`, a read-only filesystem, uid 10001, a 512 MB memory limit and a healthcheck. It answers ARP and ping for the fake addresses and serves emulated SMB (445), RDP (3389), WinRM (5985), SSH (22), LDAP (389) and MSSQL (1433) on the preset's addresses, with canned banners and a log of every connection, login attempt, share access, file write and service request.
- [x] Presets as declarative files, `guest/lan-presets/<id>.json`, validated by `cape/guest_engine/lan_presets.py`. Three ship: `small-office` (`.200`-`.205`, `corp.local`), `flat-home` (`.216`-`.219`, `home.lan`) and `domain-servers` (`.232`-`.238`, `lab.internal`). Host names and addresses are fixed per preset: the file gives a host offset, and the address is that offset in `GUEST_SUBNET`.
- [x] The container runs with the stack, not per analysis (the plan's Step 5: `restart: "no"`, started by `docker compose up`). Each analysis opens a **session** for its guest before it submits the sample and closes it when the analysis ends, through the control service. The daemon writes one JSONL log per session, and the close copies it into the analysis folder as `lansim/events.jsonl`. Analyses on different guests run at the same time, and their presets' address blocks are disjoint, so their fake hosts do not clash (see Open questions).
- [x] Firewall (`cape/guest_engine/firewall.py`, `cape/guest_engine/lan_firewall.py`): with a session open, a guest may reach only the gateway and its preset's fake host addresses on the preset's ports. The change is in the input chain of `tartarus_guest` (allowed pairs in sets) and in the bridge table (ARP and IP to a fake address are dropped unless the `(guest, host)` pair is allowed; a frame that uses a fake address as its source is dropped). The forward chain and `RESERVED_NETWORKS` are not involved (plan, findings 2 and S2, S3). Three more pieces, because the rooter's iptables rules otherwise override the fake block (plan, S1 and S4): a raw-priority `notrack` table, a route-hook table that sets TTL 128 on fake-host replies, and iptables `OUTPUT` and `INPUT` accepts tagged `tartarus-lan`. `RESERVED_NETWORKS` stays; guest-to-guest stays blocked; anti-spoofing in `cape/libvirt/qemu-hook` stays. With no session, the rendered ruleset is byte-identical to the one without the feature.
- [x] Port isolation (`cape/guest_engine/isolation.py`, `port_isolation.py`) is kept and not changed; the fake hosts are not another guest port.
- [x] `scripts/verify-isolation.sh` / `make verify-isolation` extended with a LAN section: with sessions open, each guest reaches exactly the fake hosts of its preset and nothing else, two guests with different presets never reach each other, the spoofing tricks still fail, the sessions leave the firewall as it was, and the negative proof (`ISOLATION_NEGATIVE_PROOF=1`) fails. Run for real on two Windows guests: [step12a-run-2.txt](../history/fake-lan-notes/step12a-run-2.txt) (57 ok, 0 failed), [step12a-run-3-negative-proof.txt](../history/fake-lan-notes/step12a-run-3-negative-proof.txt) (exits 1).

### Other
- [x] Docs: `docs/guide/fake-lan.md`, `docs/guide/safety.md` (fake LAN section), `docs/security.md` (accepted risks and audit scope), `SECURITY.md`, `docs/specs/cape-integration.md`, `docs/specs/gui.md`, `docs/contributing/adding-a-lan-preset.md`. `docs/specs/guest-profiles.md` is not changed: presets reference no guest profile.
- [x] `CHANGELOG.md` entry (Unreleased).

## Behavior details
- The fake LAN is opt-in per analysis. Off means today's behavior exactly, including the isolation proof.
- Presets use addresses in the existing guest subnet (default `192.168.150.0/24`), in the block `.200` to `.247`, outside the guest range `.10`-`.99` and the DHCP pool `.100`-`.119`. A preset stores a **host offset** in that block, not an address: `GUEST_SUBNET` can differ from the default, and `.248` to `.254` stay free. Presets must not overlap: two presets may not share an address or an FQDN (plan, finding 10 and Decision 2).
- **Name resolution.** INetSim's DNS answers every name with the gateway, so each fake host's FQDN is rendered from the presets as a `dns_static` entry in INetSim's configuration (plan, finding 6 and S7). Names must be FQDNs of at least two labels, lower case, with no underscore, because INetSim refuses anything else and would stop all its services. Single-label names (`\\FS01\C$`) do not resolve, since guests have no DNS suffix. NetBIOS, LLMNR and mDNS queries are not answered in v1.
- **MAC and TTL.** Every fake host answers ARP with the bridge's MAC, and replies with TTL 128 (the TTL of a Windows system), so a sample that fingerprints by MAC vendor sees the bridge (plan, finding 5 and S4; Decision 4, accepted for v1).
- **Accounts.** Each SMB host lists well-known weak accounts with their passwords (for example `Administrator`). Windows' SMB client signs its traffic with a key derived from the password, so a fake host that accepts any password cannot be used by it (S5). A login with another password fails as on a real host, and its NTLMv2 material is logged. The guest's own account is **not** added to the fake hosts, so no guest secret reaches the daemon (Decision 9). SSH is the exception: it accepts any password and runs nothing.
- The fake hosts respond just enough for malware to proceed to the next step (open a port, accept a login, accept a file), and log everything. They never run what the malware sends: `svcctl` create and start are logged and nothing starts; RDP never grants a session; WinRM never offers a shell; MSSQL answers a few canned queries and logs the rest without interpreting them. `wmiexec` (DCOM on 135) and `sc.exe` (authenticated, sealed RPC) get no working answer in v1 (S6, Decision 10).
- **Files** written to a fake share are kept in memory for the session, up to 16 MiB per file and 64 MiB per session: anything beyond is not kept, and the log's `truncated` flag says so. A stored file is never written to the host and never run. The log records the size and SHA-256 of what the client sent.
- **Limits.** The daemon logs at most 200 events per second; the first 200 events per (host, service) in full, then counters; at most 20 000 events or 8 MB per session (after that, `log_truncated`). A connection may read 64 KiB (raised only after a verified login), 30 s idle and 300 s in all. At most 32 connections per source and service and 512 per session. These numbers are in `lan-sim/lan_sim/limits.py` and come from the flood measurements of Step 0 (S10).
- **Derived events.** The daemon never sees a closed port or an absent address, so sweeps and fan-outs come from the CAPE flows and the capemon `connect` calls, not from the daemon's log (S8, Decision 5). Thresholds, in `backend/app/ingest/lan_derived.py`: a **sweep** is 5 or more hosts on one port within 30 s by one process; a **fan-out** is 4 or more hosts over 2 or more services within 5 min; a **credential spray** is 3 or more hosts with one user name within 5 min. They are starting values, to be tuned on real runs.
- **Attribution.** The daemon has no process id. Its events are joined to the process by the guest's source port and the destination, from CAPE's flows and Sysmon's EID 3 (S9).
- The fake LAN combines with the tunnel routes of [tunnel-routes-and-tls-interception.md](tunnel-routes-and-tls-interception.md): lateral-movement traffic goes to the fake hosts, C2 traffic goes through the tunnel.
- Routes `none` and `drop` with the fake LAN on are allowed, so LAN behavior can be studied with no outside access at all. Only `internet` refuses it.
- **Live phase.** The fake LAN is read at the final ingest only. The live feed has no source for the fake-host log, so lateral-movement events and their alerts appear after the run (Decision 7, finding 13).

## Edge cases
- Fake LAN on, route `internet` → refused at submit with a message.
- Fake-host container fails to start, or the control service cannot open the session → the analysis does not start, and the failure says so ("The fake local network could not start: ..."); it never runs "half simulated". Nothing is submitted to CAPE.
- Sample scans the whole /24 → addresses without a fake host get no answer; the scan itself is still recorded as flows.
- Sample attempts to reach another real guest → still blocked and not flagged as a fake host.
- Many connection attempts (scan floods) → events are aggregated or capped so the report stays usable (limits above).
- A log that is missing or unreadable → no events from it, and the analysis still ingests. A truncated log gives what it holds, and its invalid lines are skipped.

## Acceptance criteria
Not yet verified on a real guest end to end: the e2e and `make verify-isolation` parts are Step 12. The Step 0 spike showed the mechanism on a Windows guest and on a replica rig (plan, "What Step 0 found").
- With the small-office preset, a sample that scans for SMB gets answers from the fake file server and domain controller, and the Network tab lists them with a fake-LAN badge.
- The Summary shows which fake hosts and services the sample touched, and how often.
- A sample using PsExec-style behavior against an admin share triggers a Sigma alert tagged Lateral Movement, and the technique appears in the ATT&CK matrix.
- With the feature off, existing analyses and `make verify-isolation` behave exactly as before.
- With the feature on, `make verify-isolation` shows the guest reaches only the fake hosts and the gateway, and never another guest, the host LAN or the internet.
- The exported HTML and PDF reports include the Lateral movement section.

## Decisions
- Emulated services in one container, not real VMs: light, safe, fits the guest cap. The container shares `cape`'s network namespace, because the guest bridge exists only there (plan, Decision 1).
- Presets chosen in the submit dialog; fixed presets, no GUI editor.
- Opt-in toggle in the submit dialog, off by default, on top of any route except `internet`.
- Report: Network tab flags, Summary section, Sigma and ATT&CK rules, and the exported report.
- The decisions accepted on 2026-11-23 (plan, Decisions 1 to 10) are recorded in the plan, not repeated here.

## Open questions
- **Concurrent analyses.** Closed (plan, Decision 2). Each preset has its own address block and its own host names, so one shared daemon answers by destination address and two analyses cannot clash. A guest gets a session only for its own preset, and the firewall lets it reach only that preset's hosts. The cost: a guest that resolves another preset's name gets an address it cannot reach.
- **Exact hosts and protocol fidelity.** Closed by the presets and by Step 0 (plan, S5 to S7 and Step 4). A canned SMB negotiation is not enough for the tools that matter: the SMB service runs real signed sessions for known accounts, with impacket's protocol classes behind our own server (S6). `wmiexec` and `sc.exe` are out for v1.
- **Cap and aggregation for scan floods.** Closed (plan, S10). The numbers are in `lan-sim/lan_sim/limits.py`, and the sweep and fan-out thresholds in `backend/app/ingest/lan_derived.py`.
- **`docs/security.md` accepted-risks table and audit scope.** Closed: yes to both (plan, Decision 8). The accepted risks for the fake LAN and the `lan-sim` container are in [security](../security.md#accepted-risks), and the files to audit first include `cape/guest_engine/lan_firewall.py`, `cape/bin/lan_logic.py` and `lan-sim/lan_sim/`.

## Relevant code
- Firewall and isolation: `cape/guest_engine/firewall.py` (`RESERVED_NETWORKS`), `cape/guest_engine/lan_firewall.py`, `cape/guest_engine/lan_session.py`, `cape/guest_engine/lan_block.py` (the address block), `cape/guest_engine/isolation.py`, `cape/libvirt/qemu-hook`, `scripts/verify-isolation.sh`
- Presets: `guest/lan-presets/`, `cape/guest_engine/lan_presets.py`, `cape/bin/lan_dns.py`, `cape/bin/lan-dns-static`
- Control service: `cape/bin/guest-control`, `cape/bin/lan_logic.py`
- Fake hosts: `lan-sim/` (`Dockerfile`, `lan_sim/`, `SCHEMA.md` for the log)
- Guest network and CAPE config: `docker-compose.yml` (cape service, `lan-sim`, `lan-run`, `GUEST_SUBNET`), `cape/templates/cape-conf.d/routing.conf`, `cape/templates/tt-guest.xml`, `cape/templates/inetsim.conf`, `cape/supervisord.conf`, `guest/domain/domain.xml.tpl`
- Routes: `backend/app/schemas/settings.py:7`, `frontend/src/services/routes.ts`
- Submit: `frontend/src/components/SubmitDialog.vue`, `frontend/src/components/SubmitLanFields.vue`, `backend/app/schemas/analysis_requests.py`, `backend/app/analyses/lan_sessions.py`, `backend/app/analyses/lan_check.py`, `backend/app/analyses/runner.py`
- Ingest and views: `backend/app/ingest/lan_sim.py`, `lan_sim_log.py`, `lan_sim_derived.py`, `lan_derived.py`, `lan_fields.py`, `cape_network.py`, `backend/app/views/network.py`, `backend/app/analyses/lan_summary.py`, `backend/app/analyses/lan_models.py`, `backend/app/views/attack.py`, `backend/app/rules/attack.py`, `backend/app/rules/categories.py`, `backend/app/rules/mapping.py`, `frontend/src/components/tabs/NetworkTab.vue`, `NetworkTable.vue`, `FakeLanBadge.vue`, `LateralMovementSection.vue`
- Sigma: `rules/sigma/tartarus/` (the `lan_*` rules and their [README](../../rules/sigma/tartarus/README.md))
- Docs: `docs/specs/cape-integration.md`, `docs/guide/fake-lan.md`, `docs/guide/safety.md`, `docs/security.md`, `SECURITY.md`, `docs/features/tartarus-v1.md` (non-goals), `docs/specs/data-model.md`
