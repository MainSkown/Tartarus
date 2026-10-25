# Security policy

Tartarus runs live malware in virtual machines on your own computer. Read [docs/security.md](docs/security.md) for how it contains that
and for the risks that remain, and [the safety guide](docs/guide/safety.md) before you detonate anything.

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability. Use GitHub's private vulnerability reporting on this repository
(Security tab, "Report a vulnerability"). Include what you did, what you expected and what happened, the version (`GET /api/version`
once it exists, otherwise the commit), and whether a guest or only the web app is involved.

You can expect an answer within a week. A fix ships as a patch release with a note in the changelog, crediting you if you wish.

## What counts

- A guest reaching the host, another guest, the compose services or the LAN on a route where it should not.
- Hostile analysis data (a report, a pcap, a memory image, a file or process name) crashing the backend, running code, or running script in the browser.
- A web page the analyst visits driving the app, or the guest desktop, across origins.
- Secrets leaking into logs, images or process lists.

Known and accepted risks are listed in [docs/security.md](docs/security.md#accepted-risks); a report about one of them is welcome as a
reason to close it, not as a new vulnerability.
