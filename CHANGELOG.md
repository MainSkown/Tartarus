# Changelog

All notable changes to Tartarus are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The working record of how each
milestone was built is in [docs/history](docs/history/README.md).

## [1.0.0] - unreleased

First release: a local malware-analysis workbench for one analyst on a Linux host with KVM and
Docker. CAPEv2 detonates a file in a Windows guest; Tartarus shows the run live, keeps every
analysis in its own index and reports on it.

### Added

- Submission of a file from the Submit dialog, a queue of analyses, and a cancel for a queued or
  running analysis (M1a, M7).
- Analysis pages for a finished run: an overview with score, highest severity and ATT&CK ids; a
  process tree and graph; network, artifacts, registry and file views; and a detections view with
  ATT&CK ids (M1b).
- Live view of a running analysis over a WebSocket: process and event stream, live detections,
  and an interactive guest desktop through Guacamole (M2).
- `+60s` on an interactive run to extend the analyst's deadline by a minute, up to CAPE's
  1200-second limit, and an END RUN button (M7).
- A KQL-like query bar over the events, with field aliases, validation errors with suggestions,
  autocomplete, quick-filter chips and a filter-on and filter-out action; an Events table with
  facets; and a Timeline tab (M3).
- Sigma rules evaluated live in the event stream and again at final ingest, with a shipped
  ruleset, a Rules page and per-rule enable and disable (M4).
- Tags with a `name:value` form (for example `tlp:amber`) and plain-text notes on a process, an
  event or the analysis itself (M5).
- Exports: STIX 2.1, MISP and CSV indicators of compromise, and an HTML and a PDF report, both
  produced as background jobs (M5).
- A guest wizard: build a Windows guest unattended from a user-supplied ISO, clone a ready guest
  with its own name and password, run its self-test, and delete it. Up to five guests; a failed
  guest does not count towards that limit (M6, M7).
- Build steps that can be resumed, retried or restarted from the build page, and a cancel for a
  build in progress (M6, M7).
- Sysmon events, with a tighter Sysmon configuration in the guest (M8).
- Defender's verdict for an analysis on a Defender-on guest: what Defender logged and whether it
  removed the sample or a process (M8).
- A memory option on the Submit dialog: a full memory dump of the guest, analysed offline with
  Volatility3 into memory findings. The dump is deleted after the analysis unless kept (M8).
- Import of a PCAP capture and of a memory image as analyses with no guest run (M9).
- A Search page across the events of every analysis, and an IOC pivot from an indicator to every
  analysis that saw it (M9).
- Parallel analyses: two analyses on two ready guests run at the same time. Builds, clones,
  deletes and registration still wait for every analysis to finish (M9).
- Interface text in an English catalogue, checked by lint so a new string cannot be left out of it
  (M7b).
- Proofs on real guests: a Windows 10 22H2 guest and an English-language Windows ISO were built,
  cloned, resumed, restarted and paused, and a manual Defender pause was walked through (M10).
- A CI pipeline on GitHub Actions: lint, types, the unit suites of the backend, the CAPE container
  and the frontend, the integration suite, and a compose smoke test. The real-guest checks stay
  manual, because hosted runners have no nested KVM (M11).
- Contributor and user documentation under `docs/` (M11).

### Changed

- Failed guests no longer count towards the five-guest cap, and a failed guest never blocks a new
  build (M6 decision, M7).
- The CAPE container's `finish-run` program was removed (M7).
- A resumed guest build waits for an earlier apply and reboot to finish instead of applying on top
  of it (M7).
- Every base image is pinned to a digest, and nginx to a concrete version (M11).
- ETW was dropped from v1 (M8). Sysmon and Defender are the event sources built instead.

### Security

These are the findings of the v1 review, each fixed and tested before the release. The accepted
risks that remain, and why they stay, are in [docs/security.md](docs/security.md).

- **Guest network:** a Tartarus-owned nftables ruleset sits ahead of CAPE's rules. A guest reaches
  only its gateway; internal and private networks are rejected on every route, a spoofed address is
  dropped at the bridge port, and guests cannot reach each other. `make verify-isolation` proves
  each rule from inside two real guests.
- **Host and Origin checks:** the backend and nginx refuse a foreign `Host` (421) and a foreign
  `Origin` on writes and WebSockets (403). Every response carries `nosniff`, frame and referrer
  headers, and nginx sends a Content-Security-Policy.
- **Secrets:** `make init-env` generates a mode-600 `.env` with random secrets; compose refuses to
  start without them, and preflight rejects placeholders and short tokens. Each CAPE program starts
  with only the secrets it reads.
- **CAPE container:** the `cape` user is out of the host's disk group, `tcpdump` runs on a file
  capability instead of `sudo`, the CAPE tree is root-owned, and CAPE's web UI answers only `/apiv2`
  with `DEBUG` off.
- **Hostile data:** report, PCAP and JSON input is size- and depth-bounded; out-of-range live BSON
  values are corrupt records rather than crashes; uploads are refused by `Content-Length` before the
  body is read; guest names are validated before they reach the control service; the event-log
  export from a guest is size- and time-bounded and refuses redirects.
- **Pinned images:** base images are pinned by digest, and a test fails on an unpinned `FROM`,
  `COPY --from` or compose image. Dependabot watches uv, npm, docker and actions.
- Dependencies: pillow, certifi and pypdf were moved to fixed versions for their audited advisories.

### Known issues

- **Windows 10 end-to-end limits:** `make e2e` fails two checks on a Windows 10 guest: the process
  panel selects the first process rather than the expected one, and the Sigma alert check expects its
  match on a capemon event where the Windows 10 run produces it from Sysmon (follow-up L2).
- The self-test failed once, on one of three Windows 10 clones, because an open `WinStore.App`
  window was still up after `quiet-desktop`. A settle-and-recheck is planned (follow-up L1).
- `GET /api/guests` returns the guest account's password, shown with reveal and copy on the guest
  card. A reveal endpoint is planned (follow-up L3).
- The Content-Security-Policy keeps `style-src 'unsafe-inline'`, because Quasar uses inline style
  attributes. Narrowing it is planned (follow-up L4).
- The M11 follow-ups are in [docs/history/m11-followups.md](docs/history/m11-followups.md).
