# Tartarus

A local malware-analysis workbench built on [CAPEv2](https://github.com/kevoreilly/CAPEv2).
Drop in a Windows sample, watch it detonate **live** in an isolated, hardened Windows VM, interact
with the guest desktop, then dig through processes, timeline, network and detections with a
query bar, and export IOCs and reports.

> **Status:** design phase. Nothing is implemented yet; the docs below describe what will be
> built.

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
| [Theme CSS](docs/design/tartarus-theme.css) | Reference stylesheet (becomes `frontend/src/css/app.css`) |

## Planned quick start (v1)

```bash
# Linux host with KVM (/dev/kvm) and Docker + Compose
cp .env.example .env
docker compose up -d
# put a Windows 10/11 ISO into ./data/iso, then open http://127.0.0.1:8080 → Guest VM → Build
```

## Developing

Three rules govern this codebase — self-documenting code, test-first, and no duplication — see
[CLAUDE.md](CLAUDE.md).

## Safety

Tartarus runs live malware. Guests sit on an isolated bridge inside the `cape` container. The
default network route is simulated (INetSim), and the UI listens on localhost only. Use a
dedicated machine where possible, and read the safety notes in
[architecture](docs/architecture.md#network-and-isolation-model) before choosing the `internet`
route.
