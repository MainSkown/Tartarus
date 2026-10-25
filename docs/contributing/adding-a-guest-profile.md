# Adding a guest profile

A guest profile holds everything that differs between operating systems. The engine, the registry,
the snapshots, the CAPE registration, the health checks and the GUI are generic and read the profile.
The spec is [guest profiles](../specs/guest-profiles.md). This page is the working order for adding one.

Windows is the only profile that ships and the only one that has been built and run. The
[checklist for a new OS](../specs/guest-profiles.md#checklist-for-a-new-os) lists what a second one
needs, including what CAPE's Linux support requires.

## How a profile is loaded

- A profile is a directory, `guest/profiles/<id>/`. `<id>` matches `profile.json`'s `id` and the
  slug rule `[a-z][a-z0-9-]{1,31}`. The directory is copied into the `cape` image.
- `profile.json` is the only file the engine reads for itself. Unknown fields are refused. Set
  `"schema_version": 1`. The field table is in the [spec](../specs/guest-profiles.md#profilejson).
- `load_profiles` (`cape/guest_engine/profile.py`) loads every directory. A profile that fails
  validation is listed as broken with every bad field, and the others still load. A profile loads
  only if each step it names exists as an executable and each file under `selftest` exists.
- A build runs `pipelines.build.<media kind>`, a clone runs `pipelines.clone`. Each entry names a step.
  A step is an executable found first in `guest/profiles/<id>/steps/`, then in the generic
  `guest/steps/` (`preflight`, `fetch`, `define`, `copy`, `snapshot`, `register`). Naming a step with
  the same file overrides the generic one.
- The engine runs each step as a subprocess. A step and its process group are killed after
  `timeout_s` (default 600). `weight` sets its share of the progress bar, and `when` runs it only for
  an option value.
- A new guest stays in state `testing` until the backend's self-test passes. The self-test builds
  `selftest.sample`, runs it as an analysis, checks the signals in `selftest.signals`, and runs the
  guest-side checks in `selftest.check_step`. See [self-test](../specs/guest-profiles.md#self-test).

## What to copy

Start from `guest/profiles/windows/` and remove what you do not need. Its parts:

- `profile.json`: every top-level field of the schema, with Windows values.
- `steps/`: the build and clone steps (`install`, `provision`, `tamper-off`, `defender-on`,
  `remove-ghost-drives`, `quiet-desktop`, `reconfigure`, `symbols`, `selftest-checks`) and `steps/lib/`.
- `selftest/`: the benign sample's source (`benign.c`) and the facts script (`guest-facts.ps1`).
- Assets such as `autounattend.xml.tpl`, `sysmon-config.xml`, `names.json`, `keyboards.json`, and
  `inspector.py` for media recognition.

Do not copy the engine's assumptions. The engine must not name an operating system: the grep gate in
`cape/tests/test_engine_generic_code.py` fails on `windows`, `defender` or `powershell` in
`cape/guest_engine/*.py`, except `protocol.py` and two lines of schema vocabulary in `profile.py`. Put OS
words in the profile.

Two things are per profile and easy to forget:

- The **giveaway scan**. Nothing the profile ships may contain a word that tells a sample what the
  machine is. `cape/tests/test_windows_profile.py` scans the Windows profile with an allow-list. A new
  profile needs the same scan.
- The **identity rules** and **neutral names**. A guest's account, machine name and password come from
  `identity` generators, not from fixed values.

## Test it

Run the fast layers first. They need no guest:

1. `make test-cape` runs `cape/tests/`. `test_profile.py` covers the schema loader on fixture profiles
   in `cape/tests/fixtures/profiles/`. `test_clone_pipeline.py` loads every profile in `guest/profiles/`
   and checks that every step its pipelines name exists. Add your profile's fixture or case there.
2. `make test-scripts` runs the shell tests. `scripts/tests/test_windows_steps.sh` is the pattern for
   testing a profile's own steps: it runs them as executables with the `TT_*` environment against a
   fake agent (`scripts/tests/fake_guest_agent.py`), with `virsh` and `xorriso` as stubs.
3. `make lint` covers `cape/guest_engine` and the `cape/` code, with ruff.

Then the real build, which needs KVM and an installer:

4. Build the guest with the wizard (`/guest/new` in the GUI) or with `guest-build --profile <id>`
   inside the `cape` container. `cape/bin/guest-build` lists its flags in its header.
5. Let the self-test run. A guest is usable only after its verdict is `ready`.
6. `make build-guest` and `make verify-guest` are Windows scripts. They prove the Windows acceptance
   checks, so a new profile needs its own proof. Write one only if the self-test does not cover what
   the new OS must show.

See [running the tests](running-the-tests.md#real-guest-checks-manual) for the commands and what each needs.
