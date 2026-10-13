# Tartarus

A local malware-analysis workbench built on [CAPEv2](https://github.com/kevoreilly/CAPEv2).
Drop in a Windows sample, watch it detonate **live** in an isolated, hardened Windows VM, interact
with the guest desktop, then dig through processes, timeline, network and detections with a
query bar, and export IOCs and reports.

> **Status:** the foundation is built and running (the Docker stack, a FastAPI backend with a
> live health feed and a Settings API, a Quasar PWA with the app shell and Settings page), and
> the sandbox works underneath it: a privileged CAPE container runs a script-built Windows 11
> guest on KVM, and a test sample has been analysed end to end. What isn't built yet is the part
> that connects them: submitting a sample from the UI, live monitoring, and the analysis views.
> See the [overview](docs/overview.md#roadmap) and the [M0 plan](docs/plans/m0-cape-spike.md).

## Documentation

| Doc | What's in it |
|---|---|
| [Overview](docs/overview.md) | What Tartarus is, why it exists alongside CAPE, roadmap, glossary |
| [Architecture](docs/architecture.md) | Containers, data flows, isolation model, tech stack, repo layout |
| [v1 scope](docs/features/tartarus-v1.md) | Checklist, acceptance criteria, decisions, open questions |
| [Backend spec](docs/specs/backend.md) | Modules, REST and WebSocket API, collector, Sigma, query language, exports |
| [Data model](docs/specs/data-model.md) | PostgreSQL schema, OpenSearch ECS event schema, source mappings |
| [GUI spec](docs/specs/gui.md) | Screens, layouts, interactions, states, frontend structure |
| [CAPE integration](docs/specs/cape-integration.md) | `cape` container, CAPE config, guest build wizard, Windows-host plan |
| [Design system](docs/design/design-system.md) | Ice-blue cyberpunk theme: tokens, components, data-viz rules |
| [Theme CSS](frontend/src/css/app.css) | The theme stylesheet, single source of the design tokens |
| [Plan: foundation](docs/plans/foundation.md) | Compose stack, backend and frontend skeletons: subtasks, model tiers, dependencies |

## Quick start

Needs Docker with Compose 2.24.4 or newer. Run `make preflight` first to check your host.

```bash
cp .env.example .env     # then set POSTGRES_PASSWORD and CAPE_DB_PASSWORD
make up                  # production build at http://127.0.0.1:8080
```

For development with hot reload, use `make dev` instead (frontend on `127.0.0.1:5173`, backend
and its API docs on `127.0.0.1:8000`). Database migrations run when the backend starts.

`make check` runs everything (lint, unit and integration tests, screenshots) and needs `uv` and
Node 24 or newer on the host. `make smoke` checks the compose files' safety rules without
starting anything; `make smoke MODE=prod` or `MODE=dev` checks a running stack.

Submitting a sample needs the CAPE container and a Windows guest, which come in later
milestones (see the [overview](docs/overview.md#roadmap)).

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
