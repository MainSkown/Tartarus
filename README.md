# Tartarus

[![CI](https://github.com/MainSkown/Tartarus/actions/workflows/ci.yml/badge.svg)](https://github.com/MainSkown/Tartarus/actions/workflows/ci.yml)

Tartarus is a local malware-analysis workbench built on [CAPEv2](https://github.com/kevoreilly/CAPEv2).
You submit a Windows file, it runs inside an isolated, hardened Windows VM under CAPE while you watch,
and you then explore what it did in a web UI: processes, events, timeline, network, artifacts and
detections.

**Status:** v1 release candidate. The v1.0.0 tag is not cut yet. See the [changelog](CHANGELOG.md) when it lands.

## What you can do

- **Submit** a sample from the browser, and queue analyses on several guests at once.
- **Watch it live:** a live event stream and process tree while the run is in progress, and an
  interactive desktop of the guest in the browser.
- **Explore the result:** process tree, events, timeline, network and artifacts, linked by a
  KQL-like query bar with facets and an IOC pivot to every analysis that saw the same indicator.
- **Detect:** Sigma rules run on the live event stream, and CAPE signatures and YARA appear with them.
- **Sources:** Sysmon events and Volatility3 memory findings (full memory dump) are added to the
  final report. Defender's verdict is shown on guests with Defender on.
- **Guests:** a wizard builds a Windows 10 or Windows 11 guest from your own ISO, with Defender on
  or off, optional Sysmon and a lived-in look. Clone a guest to get another one, up to five.
- **Import:** PCAP files and memory images can be analysed without a guest run.
- **Export:** IOCs as STIX, MISP or CSV, and the report as HTML or PDF.
- **Tag and note** analyses, processes and events.

## Quick start

You need a Linux host with KVM (`/dev/kvm`) and Docker with Compose 2.24.4 or newer. The full list is in
[the install guide](docs/guide/install.md).

```bash
git clone https://github.com/MainSkown/Tartarus.git
cd Tartarus
make init-env     # writes .env with random secrets (mode 600); never overwrites an existing .env
make preflight    # checks the host and the secrets in .env; fix every FAIL
make up           # builds and starts the stack (the first build takes 20 minutes or more)
```

Then open http://localhost:8080. The app listens on `127.0.0.1` only.

Copy a Windows ISO into `data/iso/` (git-ignored, mounted read-only into the `cape` container), open
**Guest VM** in the app and press **[+ NEW GUEST]**. The wizard builds the guest; it takes about 16 minutes.
Tartarus never bundles or downloads Windows.

The stack does not start after a reboot (every container has restart policy `no`). Run `make up` again
after you log in. `make down` stops it and keeps your data. The
[install guide](docs/guide/install.md) covers the host setup, the `vm.max_map_count` setting and the
details of each step.

## The guest

Tartarus never bundles or downloads Windows. Your ISO goes in `data/iso/`, and the wizard lists the
editions it finds there. Each guest is a full copy of about 22 GB, and the wizard can keep up to five.
Analyses run on a ready guest. Only Windows 11 25H2 (Polish) and Windows 10 22H2 have been run for real.
The details, the timings and the naming rules are in [building a guest](docs/guide/building-a-guest.md).

## Safety

Tartarus runs live malware. Guests sit on an isolated bridge inside the `cape` container, and the
default network route is simulated (INetSim). The `internet` route is real internet access, so use it
only on a dedicated machine or behind a VPN. Read [the safety guide](docs/guide/safety.md) before you run
anything, and [the security overview](docs/security.md) for the threat model and the risks that remain.
To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Documentation

| Read | When |
|---|---|
| [User guide](docs/guide/README.md) | You use Tartarus: install, build a guest, run a sample, read a report, troubleshoot |
| [Contributing](docs/contributing/README.md) | You change the code: layout, set-up, the rules, adding a guest profile or an event source |
| Specs | You need the exact behaviour: [backend](docs/specs/backend.md), [data model](docs/specs/data-model.md), [GUI](docs/specs/gui.md), [CAPE integration](docs/specs/cape-integration.md), [guest profiles](docs/specs/guest-profiles.md) |
| [Architecture](docs/architecture.md) | You want the containers, the data flow and the isolation model |
| [Design system](docs/design/design-system.md) | You design or change a screen (the theme tokens are in [app.css](frontend/src/css/app.css)) |
| [History](docs/history/finish-line.md) | You want to know how v1 was built: the milestone plans, spike notes and review reports |
| [Security](docs/security.md) and [SECURITY.md](SECURITY.md) | You review the threat model, or report a vulnerability |

## Development

Run `make hooks` once per clone to install the pre-commit checks.

| Command | What it does |
|---|---|
| `make dev` | Runs the stack with hot reload: the frontend on `127.0.0.1:5173`, the backend and its API docs on `127.0.0.1:8000` |
| `make test` | Unit tests: `cape/` code, the shell tests of the scripts, backend and frontend |
| `make lint` | ruff, mypy, eslint and the TypeScript check |
| `make check` | Everything: lint, unit and integration tests, and the screenshot harness (needs Docker) |
| `make e2e` | End-to-end check on the running stack with a built guest (slow) |

`make help` lists every target. [Running the tests](docs/contributing/running-the-tests.md) explains each
layer and what it needs. The development rules are in [.claude/CLAUDE.md](.claude/CLAUDE.md).

## License

Tartarus is licensed under the [GNU General Public License v3.0](LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md)
to contribute and [THIRD_PARTY.md](THIRD_PARTY.md) for the components it bundles. Those components,
including CAPEv2 and the guest tools, keep their own licenses.
