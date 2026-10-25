# Contributing to Tartarus

Thanks for looking. Tartarus runs live malware in virtual machines on your own computer, so read
[the safety guide](docs/guide/safety.md) before you run anything, and report security problems
through [SECURITY.md](SECURITY.md), not as public issues.

## Reporting a bug

Open an issue with:

- what you did, what you expected and what happened, in that order;
- the commit you ran (`git rev-parse HEAD`);
- whether a guest was involved, and which one (Windows 10 or 11, Defender on or off);
- the relevant lines of `make logs`, or the failing step's message on the analysis or build page.

A bug that reproduces in a test is worth more than a long description: if you can write the failing
test, say so in the issue.

## Proposing a change

Open an issue before a large change, so the design can be agreed first. The specs in
[docs/specs](docs/specs/) are the reference for how the system works; a change that contradicts them
should change the spec in the same pull request. Non-goals and the list of features that come after
v1 are in [docs/features/tartarus-v1.md](docs/features/tartarus-v1.md).

## Branches and commits

- Branch from `master`. One concern per pull request.
- Commit messages start with a lower-case area and a colon, then one sentence that says what changed
  and why: `security: a guest reaches only its gateway: ...`, `cape: ...`, `frontend: ...`,
  `docs: ...`, `ci: ...`. Look at `git log --oneline` for the style.
- Write the test in its own commit before the code that passes it, so the diff shows the test failing
  first.

## Checks before a pull request

Run from the repo root. `make help` lists every target.

```sh
make lint               # ruff, mypy, eslint and the TypeScript check
make test               # unit tests: cape, scripts, backend and frontend
make test-integration   # backend tests that start OpenSearch and Postgres (needs Docker)
make check-links        # every relative link in the markdown resolves
```

[docs/contributing/running-the-tests.md](docs/contributing/running-the-tests.md) explains each layer
and what it needs.

## Rules

The code follows [the rules](docs/contributing/the-rules.md): test first, names over comments, no
comment that restates the code, no duplicated logic, and a screenshot review for any visual change.

## Changes that touch a guest

A change to the guest, the CAPE container, the guest network or the guest build needs proof on a real
guest, not only the unit tests. Run the matching check and paste its result in the pull request:

- `make verify-cape` for the CAPE container's host-side checks;
- `make verify-cape-hardening` for its privileges and secrets;
- `make verify-guest` after `make build-guest`, for the analysis checks;
- `make verify-isolation GUESTS="labelA labelB"` for the guest network;
- `make verify-wizard` for the guest wizard's API path;
- `make e2e` for an end-to-end run on the running stack.

These need KVM and an ISO, so the maintainer may run them for you; say which ones you could not run.

## Licence

Tartarus is licensed under the GPL-3.0 (see [LICENSE](LICENSE)). By contributing you agree that your
contribution is released under the same licence.

## Security

Report vulnerabilities privately, as [SECURITY.md](SECURITY.md) describes. Known and accepted risks are
listed in [docs/security.md](docs/security.md#accepted-risks); a report about one of them is welcome as a
reason to close it.
