# C2b-2a notes (done / running / next)

Task: the generic guest build steps (preflight, fetch, define, snapshot, register), the domain
renderer and `guest-record`. Test-first; a piece is "done" only after its test was seen failing and
then passing.

## Done
- `guest/steps/lib/guest_record.py` + `guest-record`: 9 bash tests written first (all failed with
  "no such file"), then the code.
- `guest/steps/lib/render_domain.py` + `render-domain`, `guest/domain/domain.xml.tpl` (git mv),
  `guest/domain/fragments/*`, `guest/personas/default.json`: 25 pytest tests written first (collection
  error: module missing), then the code. Golden test: the Windows hardware block renders the same
  domain as the proven M0b template (`cape/tests/fixtures/render_windows_{install,run}.xml`, made from
  the old template with a fixed identity; canonical XML compare, a disk's children order-free).
- `guest/steps/lib/common.sh`, `preflight` (17 tests), `fetch` (10), `define` (13), `snapshot` (14),
  `register` (1): each group of tests written and seen failing (16/17, 10, 12, 15 failures) before the
  step existed.
- shellcheck (docker koalaman/shellcheck:stable) clean on every shell file; ruff check + format clean
  on the Python files and test_render_domain.py.

- Mutation checks: 34 deliberate breaks of the steps/renderer/guest-record against the new tests; 33 are
  killed. The survivor is the `FRAGMENT_VALUE` guard in render_domain.py: without it a path-like hardware
  value still cannot reach a file (the directory it names does not exist), so the guard is defense in depth
  and the mutant is equivalent.
- Final runs: test_generic_steps.sh 64/64, test_render_domain.py 25/25, test_build_guest.sh and
  test_verify_guest.sh green. `make test-cape`: 1197 passed, 1 skipped, 1 failed: the giveaway scan in
  test_windows_profile.py flags `guest/profiles/windows/steps/lib/guest_agent.py:2` (C2b-2b's file, not mine).

## Running
- nothing

## Next
- final report

## Decisions and deviations (also in the final report)
- Hardware values: the real profile schema has `boot` uefi|bios, `secure_boot` bool, `tpm` bool, not the
  brief's `uefi-secureboot` / `tpm-2.0`. The renderer maps (boot, secure_boot) to the fragment value
  `uefi-secureboot` / `uefi` / `bios` and tpm to `tpm-2.0` / `none` in one function (`_fragment_choices`).
  Fragments present: boot {uefi-secureboot, bios}, secure_boot {on, off}, tpm {tpm-2.0, none},
  disk_bus {sata, virtio}, nic_model {e1000e, virtio}, clock {localtime, utc}, machine {q35}.
  `uefi` without secure boot has no fragment (the image only has the Microsoft-enrolled OVMF pair, S0e),
  so it is refused by name; `scsi`/`ide` disk buses are in the schema but have no fragment yet.
- `guest.json` can only hold `disk_path` and `snapshot` today: the `Guest` record (registry.py, not mine)
  has no `nvram_path`, `display` or `tpm_dir`, and writing an unknown key makes the whole record
  unreadable (the registry would list the guest as broken). `guest-record` keeps the five-name allow-list
  of the brief but also refuses (exit 2, nothing written) a name the Guest record has no field for. They
  start working as soon as registry.py gains the fields. `define` therefore records only `disk_path`.
- The media kind (installer | disk_image) is in neither `guest.json` nor `context.json`; the steps tell it
  by the media file: `*.iso` is an installer, anything else a disk image (`media_kind` in common.sh).
  The clean fix is a `media_kind` in the engine's context.
- Paths are one place (common.sh): disk `<libvirt>/images/<name>.qcow2`, nvram
  `<libvirt>/nvram/<name>_VARS.fd`, snapshot files `<name>-clean.mem` / `<name>-clean.qcow2`, cache
  `<libvirt>/tartarus/cache`. render-domain takes `--disk/--nvram/--media/--extra-media` explicitly.
- The old `guest/domain.xml.tpl` is kept (restored with `git show HEAD:`) because
  `scripts/build-guest.sh` renders it and `cape/tests/test_windows_profile.py` reads it; delete it when
  C2b-2b replaces both.
- `preflight` also requires the installation media (any kind, not only installers) readable for a build,
  and not for a clone (a clone inherits media it never reads).
- Test seams (env, preflight only): `TT_KVM_DEVICE`, `TT_CPUINFO`.

## For C2b-2b (install step)
- `define` leaves the guest in install mode (installer attached to the first drive, boot cdrom then
  hd) when the build is an installer build. The domain has TWO optical drives, always: sdb (installer)
  and sdc (extra disc, empty after `define`). The `install` step builds its answer-file ISO and then
  either re-renders with `render_domain install --media "$MEDIA_PATH" --extra-media <iso>` +
  `define_rendered install` (both in `lib/common.sh`; the domain must be shut off), or
  `virsh change-media <name> sdc <iso> --insert --config`. It then `virsh start`s the domain itself
  (define does not), sends the "press any key" keystrokes, waits for the install to finish.
- `snapshot` shuts the guest down, redefines it in run mode (both drives ejected), starts it, waits for the
  agent, runs `agent.pre_snapshot` if the profile names one, idles, snapshots, powers off.
- A profile's own step sources `lib/common.sh` (`source "$GUEST_STEPS_DIR/lib/common.sh"`): it gives
  `step/progress/log/fail`, `context_var`, `vsh`, `wait_for`, `render_domain`, `define_rendered`,
  `guest_record`, `json_string`, and the path variables above.

## For the image build (planner)
- The renderer looks for `domain/` and `personas/` NEXT to the steps dir: in the image
  `/usr/local/lib/tartarus/domain` and `/usr/local/lib/tartarus/personas`, so the Dockerfile must
  `COPY guest/domain/ /usr/local/lib/tartarus/domain/` and `COPY guest/personas/ .../personas/`.
- `guest-record` imports `guest_engine` from `/usr/local/lib/tartarus` (the image) or `cape/` (a checkout).
