# Fake local network

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
- [ ] `SubmitDialog.vue`: a "Simulate local network" control, off by default. When on, a preset picker is shown (presets come from the API).
- [ ] Submit dialog: the control is disabled with an explanation when the route is `internet`.
- [ ] Network tab hosts list: a "fake LAN host" badge on simulated hosts, and a filter-on / filter-out action for it, using the existing shared filter component.
- [ ] Summary: new "Lateral movement" section, per fake host: services touched, number of attempts, first and last time, credentials or files the sample used or wrote. Empty state when the sample did nothing on the LAN; hidden when the feature was off.
- [ ] HTML and PDF report export include the Lateral movement section and the flags on fake hosts.
- [ ] All new strings through message keys.

### Backend / API
- [ ] `AnalysisOptions`: add `lan_preset: str | None` (None = off); validated against the preset list; refused together with route `internet`.
- [ ] `GET /api/lan-presets`: list of presets (id, name, hosts with role, IP and services).
- [ ] New ingest source `lan-sim` implementing the `Normalizer` protocol: converts the fake-host container's service logs into events (lane `network`, plus authentication events for login attempts) with the target host and service as ECS fields. Shared helpers are reused, not copied.
- [ ] Field catalog (the single field-definition table) gets the new fields, so the query bar, autocomplete and the Sigma pipeline see them.
- [ ] `backend/app/views/network.py`: mark hosts that belong to the preset as fake; flows to them are flagged.
- [ ] Summary view endpoint: lateral-movement aggregation per fake host.
- [ ] Sigma: new `network_connection` rules (SMB/RDP/WinRM/SSH/MSSQL sweeps, admin-share access, many-hosts fan-out) with `attack.lateral-movement` tags and technique ids, plus whatever rules need new categories; ATT&CK matrix picks them up through the existing path.

### Guest network / infrastructure
- [ ] New compose service for the fake hosts: one container attached to the guest network that answers ARP and ping and serves emulated SMB (445), RDP (3389), WinRM (5985), SSH, LDAP and MSSQL on many addresses of the guest subnet, with canned banners and a log of every connection, login attempt and file write.
- [ ] Presets as declarative files (like guest profiles), at least: small office (domain controller, file server, two workstations, SQL server, printer), flat home LAN, domain with servers. Hostnames and IPs fixed per preset.
- [ ] Start the container with the analysis and stop it afterwards; per-analysis logs saved with the analysis. Several analyses can run at once, so fake hosts cannot clash (see Open questions).
- [ ] Firewall (`cape/guest_engine/firewall.py`): allow the guest to reach only the gateway plus the preset's fake host addresses when the feature is on. `RESERVED_NETWORKS` stays; guest-to-guest stays blocked; anti-spoofing in `cape/libvirt/qemu-hook` stays.
- [ ] Port isolation (`cape/guest_engine/isolation.py`) is kept; the fake hosts are not another guest port.
- [ ] `scripts/verify-isolation.sh` / `make verify-isolation` extended: with the feature on, a guest reaches the fake hosts and nothing else; with it off, behavior is unchanged; guest A still cannot reach guest B.

### Other
- [ ] Docs: `docs/guide/safety.md` (fake LAN), `docs/security.md`, `SECURITY.md`, `docs/specs/cape-integration.md`, `docs/specs/guest-profiles.md` if presets reference guests.
- [ ] `CHANGELOG.md` entry.

## Behavior details
- The fake LAN is opt-in per analysis. Off means today's behavior exactly, including the isolation proof.
- Presets use addresses in the existing guest subnet (192.168.150.0/24), outside the guest range .10-.99 and the DHCP pool .100-.119 (concrete ranges are decided in the preset spec).
- The fake hosts respond just enough for malware to proceed to the next step (open a port, accept a login, accept a file), and log everything. They never run what the malware sends.
- The fake LAN combines with the tunnel routes of [tunnel-routes-and-tls-interception.md](tunnel-routes-and-tls-interception.md): lateral-movement traffic goes to the fake hosts, C2 traffic goes through the tunnel.
- Routes `none` and `drop` with the fake LAN on are allowed, so LAN behavior can be studied with no outside access at all.

## Edge cases
- Fake LAN on, route `internet` → refused at submit with a message.
- Fake-host container fails to start → the analysis does not start, and the failure says so; it never runs "half simulated".
- Sample scans the whole /24 → addresses without a fake host get no answer; the scan itself is still recorded as flows.
- Sample attempts to reach another real guest → still blocked and not flagged as a fake host.
- Many connection attempts (scan floods) → events are aggregated or capped so the report stays usable (limit in Open questions).

## Acceptance criteria
- With the small-office preset, a sample that scans for SMB gets answers from the fake file server and domain controller, and the Network tab lists them with a fake-LAN badge.
- The Summary shows which fake hosts and services the sample touched, and how often.
- A sample using PsExec-style behavior against an admin share triggers a Sigma alert tagged Lateral Movement, and the technique appears in the ATT&CK matrix.
- With the feature off, existing analyses and `make verify-isolation` behave exactly as before.
- With the feature on, `make verify-isolation` shows the guest reaches only the fake hosts and the gateway, and never another guest, the host LAN or the internet.
- The exported HTML and PDF reports include the Lateral movement section.

## Decisions
- Emulated services in one container, not real VMs: light, safe, fits the guest cap.
- Presets chosen in the submit dialog; fixed presets, no GUI editor.
- Opt-in toggle in the submit dialog, off by default, on top of any route except `internet`.
- Report: Network tab flags, Summary section, Sigma and ATT&CK rules, and the exported report.

## Open questions
- How are fake hosts isolated between concurrent analyses (one container per analysis, or one container with per-analysis address spaces)?
- Which exact preset hosts, IPs, hostnames and services, and the minimum protocol fidelity per service (is a canned SMB negotiation enough for the commonly seen tools?).
- Cap and aggregation for scan floods.
- Does `docs/security.md` get an updated accepted-risks table before this ships, and does the audit scope extend to the new container?

## Relevant code
- Firewall and isolation: `cape/guest_engine/firewall.py` (`RESERVED_NETWORKS`), `cape/guest_engine/isolation.py`, `cape/libvirt/qemu-hook`, `scripts/verify-isolation.sh`
- Guest network and CAPE config: `docker-compose.yml` (cape service, `GUEST_SUBNET`), `cape/templates/cape-conf.d/routing.conf`, `cape/templates/tt-guest.xml`, `cape/templates/inetsim.conf`, `cape/supervisord.conf`, `guest/domain/domain.xml.tpl`
- Routes: `backend/app/schemas/settings.py:7`, `frontend/src/services/routes.ts`
- Submit: `frontend/src/components/SubmitDialog.vue`, `backend/app/schemas/analysis_requests.py`, `backend/app/analyses/runner.py`
- Ingest and views: `backend/app/ingest/` (`cape_network.py`, `capemon_rules.py`, `sysmon_mapping.py`), `backend/app/views/network.py`, `backend/app/views/attack.py`, `backend/app/rules/attack.py`, `backend/app/rules/categories.py`, `frontend/src/components/tabs/NetworkTab.vue`, `NetworkTable.vue`
- Sigma: `rules/sigma/default`, `rules/sigma/custom`
- Docs: `docs/specs/cape-integration.md` (lines 17-22), `docs/guide/safety.md`, `docs/security.md`, `SECURITY.md`, `docs/features/tartarus-v1.md` (non-goals), `docs/specs/data-model.md`
