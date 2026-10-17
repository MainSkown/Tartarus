# Tartarus

A local malware-analysis workbench built on [CAPEv2](https://github.com/kevoreilly/CAPEv2).
Drop in a Windows sample, watch it detonate **live** in an isolated, hardened Windows VM, interact
with the guest desktop, then dig through processes, timeline, network and detections with a
query bar, and export IOCs and reports.

> **Status:** milestones M0 to M7 are built: submitting a sample from the UI, live monitoring and
> the interactive desktop, the analysis views, the query bar and timeline, Sigma detections, tags,
> notes and exports, building, cloning and choosing guests from the GUI, cancelling a build, and
> extending an interactive run. See the
> [overview](docs/overview.md#roadmap) for what each milestone proved and what was not run.

## Documentation

| Doc | What's in it |
|---|---|
| [Overview](docs/overview.md) | What Tartarus is, why it exists alongside CAPE, roadmap, glossary |
| [Architecture](docs/architecture.md) | Containers, data flows, isolation model, tech stack, repo layout |
| [v1 scope](docs/features/tartarus-v1.md) | Checklist, acceptance criteria, decisions, open questions |
| [Backend spec](docs/specs/backend.md) | Modules, REST and WebSocket API, collector, Sigma, query language, exports |
| [Data model](docs/specs/data-model.md) | PostgreSQL schema, OpenSearch ECS event schema, source mappings |
| [GUI spec](docs/specs/gui.md) | Screens, layouts, interactions, states, frontend structure |
| [CAPE integration](docs/specs/cape-integration.md) | `cape` container, CAPE config, the guest control service, guest build and clone, Windows-host plan |
| [Guest profiles](docs/specs/guest-profiles.md) | How to add an operating system: the profile directory, `profile.json`, the step contract, the self-test |
| [Design system](docs/design/design-system.md) | Ice-blue cyberpunk theme: tokens, components, data-viz rules |
| [Theme CSS](frontend/src/css/app.css) | The theme stylesheet, single source of the design tokens |
| [Plan: foundation](docs/plans/foundation.md) | Compose stack, backend and frontend skeletons: subtasks, model tiers, dependencies |
| [Plan: M0 CAPE spike](docs/plans/m0-cape-spike.md) | The privileged CAPE container and the Windows 11 guest: checks, results, findings |
| [Plan: M1a](docs/plans/m1a-submit-and-report.md) | Submit a sample from the UI and see its result: decisions, contracts, subtasks |
| [Plan: M6](docs/plans/m6-guest-wizard.md) | The guest wizard and several guests: decisions, what each wave proved, what is open |

## Quick start

Needs Docker with Compose 2.24.4 or newer. Run `make preflight` first to check your host.

```bash
cp .env.example .env     # then set POSTGRES_PASSWORD, CAPE_DB_PASSWORD, CAPE_API_TOKEN and GUEST_CONTROL_TOKEN
make up                  # production build at http://127.0.0.1:8080
```

`make up` starts the whole stack, including the privileged `cape` container, which needs
`/dev/kvm` and takes a few minutes to build the first time. Without KVM you can still work on the
UI with `docker compose up -d --no-deps postgres opensearch backend frontend` (`--no-deps`,
because the backend waits for a healthy `cape` otherwise); CAPE then shows as down.

The two tokens are secrets between containers: make each with `openssl rand -hex 32`. `GUEST_CONTROL_TOKEN`
is what lets the backend, and nothing else, ask the `cape` container to build and delete guests;
`make preflight` checks it is at least 32 characters.

For development with hot reload, use `make dev` instead (frontend on `127.0.0.1:5173`, backend
and its API docs on `127.0.0.1:8000`). Database migrations run when the backend starts.

`make check` runs everything (lint, unit and integration tests, screenshots) and needs `uv` and
Node 24 or newer on the host. `make smoke` checks the compose files' safety rules without
starting anything; `make smoke MODE=prod` or `MODE=dev` checks a running stack.

## The guest

Submitting a sample needs at least one guest. Tartarus never bundles or downloads Windows: put your own
ISO in `data/iso/` (git-ignored; the `cape` container mounts it read-only), open **Guest VM** in the app
and press **[+ NEW GUEST]**. The wizard reads the ISO, asks for a name, the editions and the options
(Defender on or off, a lived-in look, Sysmon), and builds the guest while showing the log and, during the
install, its screen. The same build from the command line is `make build-guest` (the stack must be up; it
reads `GUEST_ISO`, `GUEST_IMAGE_INDEX` and the other `GUEST_*` settings of `.env`). `make verify-guest`
proves a guest works.

What to expect:
- **Time:** a build takes about 16 minutes and a clone (`[CLONE]` on a guest's card) about 5. No
  analysis can start while one runs, and neither can start while an analysis is queued or running,
  because registering a guest restarts CAPE.
- **Disk:** every guest is a full copy of about 22 GB, and there can be at most five (a failed one counts
  until you delete it).
- **Several guests:** build Windows 11 with Defender on and clone it with Defender off; the Submit dialog
  then lets you pick one for each analysis. Only Windows 11 25H2 with a Polish ISO has been run.
- **Names:** the account and computer name inside the guest are random unless you choose them, and the
  wizard refuses names such as `sandbox` that tell a sample what the machine is. The guest built before
  the wizard existed (`win`) is adopted as it is and keeps its account `Analyst` and a few other names a
  sample can read; its card lists them, and a rebuild is the way to a clean one.

## Developing

Run `make hooks` once per clone to enable the pre-commit checks.

Development rules — self-documenting code, test-first, no duplication, screenshot review of
frontend changes, and delegating work by difficulty — live in
[.claude/CLAUDE.md](.claude/CLAUDE.md).

## Safety

Tartarus runs live malware. Guests sit on an isolated bridge inside the `cape` container. The
default network route is simulated (INetSim), and the UI listens on localhost only. Use a
dedicated machine where possible, and read the safety notes in
[architecture](docs/architecture.md#network-and-isolation-model) before choosing the `internet`
route.
