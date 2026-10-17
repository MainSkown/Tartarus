# Guest profiles: adding an operating system

Everything that differs between operating systems is a **guest profile**: a directory in the repo,
`guest/profiles/<id>/`, made of one validated JSON file and the step files and assets that file names.
The build and clone engine, the registry, snapshots, CAPE registration, health checks, the build job,
the desktop proxy and the whole GUI are generic and are driven by the profile. A profile is data plus
executables, not a plugin: nothing is loaded dynamically, the directory is copied into the `cape`
image (`cape/Dockerfile`) and read when the control service starts.

Windows is the only profile that ships and the only one that has been built and run. A Linux profile
exists on paper only ([S0e](../plans/m6-spikes/S0e-findings.md)); its findings are the checklist for
the first non-Windows profile, [below](#checklist-for-a-new-os). How the pieces run is in
[cape-integration](cape-integration.md#guest-vm-build-wizard); the API they are served through is in the
[backend spec](backend.md#guests).

## Layout

```
guest/
├── profiles/<id>/             one directory per operating system; <id> must equal profile.json's "id"
│   ├── profile.json           the only file the engine reads for itself
│   ├── inspector.py           the media inspector (the module name is media.inspector)
│   ├── manifest.sha256        pinned downloads for the generic `fetch` step (optional)
│   ├── steps/                 the profile's own step files (executable)
│   ├── selftest/              the benign sample's source, the facts script
│   └── ...                    whatever its steps use: answer-file template, scripts, name tables
├── steps/                     generic steps: preflight fetch define copy snapshot register, and lib/
├── domain/                    domain.xml.tpl and fragments/ (one file per hardware choice)
└── personas/                  SMBIOS personas (vendor strings), shared by all profiles
```

`load_profiles` (`cape/guest_engine/profile.py`) loads every directory of `guest/profiles/`. A profile that
fails validation is logged with every bad field and listed as broken; it does not stop the others. A
profile loads only if every step it names exists as an executable file and every file it names under
`selftest` exists inside its directory.

## `profile.json`

Unknown fields are rejected; every field below is required unless a default is given. `"schema_version"` is
`1`.

| Field | Meaning |
|---|---|
| `schema_version` | Must be `1`. A schema change bumps it, so an old profile is refused rather than misread |
| `id` | Slug `[a-z][a-z0-9-]{1,31}`, equal to the directory name. Stored in each guest as `profile` |
| `display_name` | What the GUI calls the OS, for example "Windows 11" |
| `family` | A label (`windows`, `linux`). Nothing may branch on it |
| `cape.platform` | CAPE's `platform` for the machine section: `windows`, `linux` or `darwin` |
| `cape.tags` | CAPE machine `tags` (each `[A-Za-z0-9][A-Za-z0-9_.-]{0,31}`) |
| `arch` | `x64` or `x86`, CAPE's `arch` |
| `hardware.machine` | libvirt machine type. The domain is rendered from fragments, so it must have a `machine.<value>.xml` fragment (only `q35` exists) |
| `hardware.boot` | `uefi` or `bios` |
| `hardware.secure_boot` | `true` needs `boot: uefi`. With `uefi` it selects the Microsoft-enrolled firmware; UEFI without Secure Boot has no fragment yet |
| `hardware.tpm` | `true` adds an emulated TPM 2.0, with a fresh state per guest |
| `hardware.disk_bus` | `sata`, `scsi`, `ide` or `virtio`. Fragments exist for `sata` and `virtio` |
| `hardware.nic_model` | NIC model; fragments exist for `e1000e` and `virtio` |
| `hardware.clock` | `utc` or `localtime` |
| `hardware.persona` | Name of a file in `guest/personas/` (default `default`): the SMBIOS vendor strings, shared so no profile carries its own copy |
| `resources.vcpus`, `ram_mb` | Defaults, 1 to 8 vCPUs and 2048 to 32768 MB |
| `resources.disk_gb`, `min_disk_gb` | Default and minimum disk. A request below the minimum is refused |
| `resources.scratch_gb` | Free space beyond the disk that a build needs (default 0). `preflight` requires disk + scratch + 20 GB |
| `media.kinds` | One or both of `installer` (an ISO to install from) and `disk_image` (an already installed image). Each needs its pipeline |
| `media.inspector` | Module name of `<profile>/<name>.py` that recognises this profile's media, or `null` |
| `options[]` | The choices the wizard and the clone form offer. See [Options and badges](#options-and-badges) |
| `identity.account`, `.machine`, `.password` | Each `{pattern, generator, label?, reserved?, optional?}`. See [Identity](#identity-and-giveaways) |
| `clone.computer_name_editable` | Whether a clone may be given a chosen machine name (otherwise one is generated) |
| `pipelines.build.<kind>` | The ordered steps of a build, one list for each of `media.kinds` |
| `pipelines.clone` | The ordered steps of a clone (may be empty if the profile cannot clone) |
| `agent.port` | The CAPE agent's port in the guest |
| `agent.path_style` | `windows` or `posix`: the separator of paths in the guest |
| `agent.ready.marker` | A path (`{work_dir}` is replaced) whose existence means provisioning is done, or `null`. Parsed and validated; nothing reads it yet (the Windows steps take the marker's name from `names.json`) |
| `agent.finish_dir` | The guest folder CAPE's analyzer watches for the early-end signal (`C:\Windows\Temp`, `/tmp`) |
| `agent.work_root` | Where a guest's neutral working folder is made; the folder name is random per guest |
| `agent.shutdown` | `acpi` or `agent-command`. Parsed; the generic `snapshot` step always shuts down with ACPI, so `agent-command` is not implemented |
| `agent.interactive` | `{options, task_fields}`: the CAPE task options string and extra task fields for a run the analyst drives. Windows: `interactive=1,nohuman=yes` and no fields |
| `agent.pre_snapshot` | A step name run by `snapshot` just before it takes the snapshot (a `sync` on Linux), or `null`. The Windows profile sets `remove-ghost-drives`, which removes the non-present CD-ROM device nodes the install left ([CAPE integration](cape-integration.md#self-test)) |
| `selftest.sample` | `{source, build, output}`: the benign sample's source file, the build command as an argument list holding `{source}` and `{output}` exactly once each, and the file it produces. Optional |
| `selftest.signals[]` | The signals the analysis of the sample must show. See [Self-test](#self-test) |
| `selftest.facts.script` | The guest-side script that prints facts and giveaways, a file in the profile directory. Optional |
| `selftest.check_step` | The step that runs the guest-side checks, or `null` |
| `selftest.extras` | A list of extra checks. Parsed; nothing runs them |
| `packages` | The CAPE analysis packages the Submit dialog offers for a guest of this profile (`auto` is always allowed) |
| `badges[]` | `{option, value, label}`: the badge a guest earns when its option has that value |
| `timeouts.agent_s`, `idle_s`, `shutdown_s` | How long `snapshot` waits for the agent, lets the guest idle, and waits for a clean shutdown |
| `adoption` | Optional. How to describe a guest built before the wizard existed, which cannot be asked: `{account, machine, password, work_dir, media, options}`. Only the Windows profile has one |

### Pipeline entries

An entry is `{step, desktop?, timeout_s?, weight?, when?}`.

- `step`: a step name, `[a-z][a-z0-9_-]{0,63}`, used once per pipeline.
- `desktop` (default `false`): the guest's screen is worth showing during this step. The build page
  shows the live desktop only while such a step runs or is paused.
- `timeout_s` (default 600): the step and its whole process group are killed after this long.
- `weight` (default 1): the step's share of the build's progress bar.
- `when`: `{option, value}` or `{option, not}`. The step runs only if the guest's option has that value
  (or, with `not`, any other value). The Windows `tamper-off` step runs when `defender` is `false`.

A build uses `pipelines.build.<media kind>` of the medium chosen; a medium whose kind the profile has no
pipeline for is refused.

## Steps

A step is an executable file, found first in `guest/profiles/<id>/steps/` and then in `guest/steps/`, so a
profile overrides a generic step by naming its own file the same. The engine runs it as a subprocess in a
process group of its own and never through a shell.

**Generic steps** (`guest/steps/`):

| Step | What it does |
|---|---|
| `preflight` | `/dev/kvm` and the CPU flags, free disk, the media readable, an earlier attempt's leftover domain, the address not held by another guest |
| `fetch` | Downloads what `manifest.sha256` pins (`<sha256> <name> <url>`) into the cache, hash-checked before use |
| `define` | Creates the disk (blank for an installer, a resized copy for a disk image; a clone arrives with its disk) and defines the libvirt domain |
| `copy` | Clone only: copies the source's base disk and nvram |
| `snapshot` | Clean ACPI shutdown, boot from disk, wait for the agent, idle, run `agent.pre_snapshot`, take the external snapshot `tartarus-clean`, power off |
| `register` | A placeholder so a pipeline reads build, snapshot, register: the engine registers the guest with CAPE itself when the last step succeeds |

**The environment.** A step gets only a few harmless variables (`PATH`, `LANG`, `LC_ALL`, `TZ`, `HOME`) and
these, never the service's own secrets:

| Variable | Value |
|---|---|
| `TT_CONTEXT_JSON` | `context.json` of this build: `guest` (the whole `guest.json`), `profile` (this file), `source` (the clone's source guest, else null), `build` (`id`, `kind`, `steps`) and `host` (`subnet`, `gateway`, `registry_root`, `libvirt_dir`, `media_dir`, `registration_dir`, `libvirt_uri`). Mode 0600: it holds the guest's password |
| `TT_GUEST_JSON`, `TT_GUEST_DIR` | The guest's record and its directory |
| `TT_PROFILE_DIR` | This profile's directory |
| `TT_BUILD_DIR`, `TT_STATE_FILE`, `TT_LOG`, `TT_BUILD_ID`, `TT_STEP` | The build's directory, its `build.json`, its log, its id and this step's name |

Values are read from `context.json`, never pasted into a command line. `guest/steps/lib/common.sh` gives a
shell step `step`, `progress`, `log`, `fail`, `context_var`, `vsh` (`virsh`), `wait_for`,
`render_domain`, `define_rendered` and `guest_record`; `guest-record set <field> <json>` writes a field of
`guest.json` (`disk_path`, `nvram_path`, `snapshot`, ...), and a field `Guest` has no place for is refused.

**The protocol.** Each output line is read as one of these; anything else is a log line.

| Line | Meaning |
|---|---|
| `STEP <text>` | What the step is doing now (the build page shows it) |
| `PROGRESS <0-100>` | How far along this step is |
| `LOG <text>` | A line for the build log |
| `PAUSE <text>` | Instructions for the analyst, used with exit code 75 |

**Exit codes.** `0` done; `75` waiting for the user; anything else, or a timeout, failed. A step that exits
75 leaves the build `paused` with its last `PAUSE` text shown; **Continue** runs the same step again.
After a failure, **Resume** re-runs the failed step and **Restart** begins from the first. So a step must
be idempotent: run twice, it must end in the same state. The guest's password and any `secret` option are
masked in the log before anything is stored.

**Profile steps.** A profile's own steps do the parts only it can: for Windows `install` (answer-file
disc, first boot, wait for provisioning), `provision`, `tamper-off`, `defender-on`, `reconfigure` (a
clone's new identity) and `selftest-checks`. A Windows step that talks to the guest uses
`guest_agent.py`, a client of CAPE's agent.

## Options and badges

An option is `{key, label, type, default, help, choices?, requires_user_step?, changeable_on_clone?}`,
with `key` `[a-z][a-z0-9_]{0,31}` and `type` one of `bool`, `string`, `choice` (needs `choices`) and
`secret` (masked in the guest's record and in every log). The `default` must be valid for its type.

The wizard's settings step and the clone form are **rendered from this list** (`GET /guests/profiles`):
one generic control per type, the label, the `help` text, nothing OS-specific in the frontend.
`changeable_on_clone: true` marks what a clone may change; every other option is shown fixed with the
source's value. `requires_user_step` marks an option that may pause the build for the analyst. A
`badges[]` rule turns an option value into the label cards, the Submit dialog and the analysis header
show (`defender: true` gives `DEFENDER ON`).

## Identity and giveaways

`identity` has three rules, for the account, the machine name and the password: a regular `pattern` the
whole value must match, `reserved` names the OS itself refuses, a `generator` that makes a value when the
analyst leaves it blank, and `optional` (default `true`). Generators are chosen by name from
`cape/guest_engine/names.py`: `first_name`, `first_name_lower`, `computer_name`, `hostname`,
`folder_name` and `password`; a new kind of name is a new generator there, not a profile field.

A value that tells a sample what the machine is is refused, by one list in `cape/guest_engine/giveaways.py`
shared by the build, the clone, the generators and the facts script:

- refused anywhere in the text: `tartarus`, `sandbox`, `malware`, `virus`, `cuckoo`;
- refused as a whole word or path component only (`cape` is inside `landscape` and `escape`): `cape`,
  `test`, `admin`; and any word starting `analy`.

The guest's own names (working folder, firewall rule, scheduled task, install-disc label) are neutral and
come from one table in the profile (`names.json` for Windows), which the shipped-file scan keeps free of
the same words. Nothing Tartarus puts in a guest may carry the product's name.

## Media inspectors

`media.inspector` names a Python module in the profile directory with `needs_mount` (bool) and
`inspect(path, context)`. For each file in `data/iso` the scan asks every profile's inspector, and one
file may be recognised by more than one:

- return `None` if the file is not this profile's media;
- return `{kind, variants, version, build, language, arch}` if it is, where `kind` is `installer` or
  `disk_image` and each variant is `{index, name, ...}` (Windows: one per edition);
- raise `MediaProblem` if it is this kind of medium but cannot be read, with a message fit for the GUI.

With `needs_mount = True` the context offers `mounted(path)`, a read-only loop mount that is always
detached afterwards. An inspector for non-Windows media should be a read-only userspace tool instead, may
return `language: null`, and may recognise an unknown image by its sha256 against the profile's manifest.

## Self-test

A new guest is `testing` until the backend's self-test passes. It builds the profile's `selftest.sample`
(the control service runs the argument list and caches the result by source and command), queues it as an
ordinary analysis on the new guest (tag `self-test`), reads the signals out of that analysis, and asks the
control service to run the guest-side checks. The verdict is stored in the guest's record.

**Signals.** Each `selftest.signals[]` entry is `{id}` from this catalog; `source` says what it is read from:

| Id | Source | Passes when |
|---|---|---|
| `events.process` | events | at least two processes were recorded (the sample and its child) |
| `events.file` | events | a file event was recorded |
| `events.registry` | events | a registry event was recorded |
| `report.present` | report | the analysis has a report |
| `report.dns_answer` | report | the lookup of `tartarus-selftest.example` was seen; an answer is reported but not required |
| `report.child_process` | report | accepted by the schema |
| `storage.monitor_log` | storage | accepted by the schema; needs a `path`, the log's place in the analysis folder |

The backend judges only the first five. A profile that lists `report.child_process` or `storage.monitor_log`
gets a failing verdict for it until the backend learns it (`backend/app/guest/selftest_verdict.py`). A
profile whose runs have no normaliser yet lists report-level signals only, which is allowed.

**Checks inside the guest.** `selftest.check_step` is a step the control service runs outside any build.
It restores the guest's snapshot and prints, one per line:

| Line | Meaning |
|---|---|
| `FACT key=value` | A fact about the guest; a few are shown on its card |
| `GIVEAWAY <text>` | Something that tells a sample what the machine is. Any one fails the self-test |
| `PROOF <name>=ok` or `PROOF <name>=failed <message>` | A claim checked inside the guest. A failed proof fails the self-test |

Everything the guest itself writes reaches the service behind a `LOG ` prefix, so nothing in a guest can
pass itself off as a fact, a giveaway or a proof. The check step exits 0 when the checks ran (a failed
proof is a result) and 1 when the guest could not be restored, reached or read. The Windows step runs the
facts script (`selftest/guest-facts.ps1`) and `defender-proof.ps1`, which writes the EICAR test string in two
halves and requires it to be removed with Defender on and kept with Defender off.

## Hardware and personas

A guest's domain is rendered from `guest/domain/domain.xml.tpl`: the profile's `hardware` block picks one
file for each choice from `guest/domain/fragments/` (`boot`, `secure_boot`, `tpm`, `disk_bus`,
`nic_model`, `clock`, `machine`; a value with no fragment is refused by name), and the persona supplies
the SMBIOS strings, the NIC's vendor prefix and the disk and board serial formats. The CPU hides the
hypervisor bit and KVM's state. The template's optical drives are `${install_drives}`: install mode fills them,
run mode leaves them out. `hardware` has no display field, because the display adapter is the QEMU standard VGA
fixed in the template: the [S2 spike](../plans/m7-spikes/S2-findings.md) found no candidate that Windows names
differently. New hardware is a new fragment file, not a template per profile, and the
generic steps read the disk target, nvram and TPM from the domain, never from a constant.

## Checklist for a new OS

Work through these in order; each line either is a file in the profile or a decision recorded in it.

1. **Media.** An inspector that recognises the installer or disk image, and a pipeline for each kind. A
   cloud image has no installer: its pipeline has no `install` step and `define` copies and resizes it.
2. **Unattended install and provisioning**, as profile steps, ending with the CAPE agent running at boot
   with the privileges the OS needs, on a static address from the guest's record.
3. **Software the guest needs.** The guest network is isolated, so everything it installs must come from
   the install media or from `fetch` into the cache at build time (`manifest.sha256`), or from a profile
   step that builds a mirror for the build only.
4. **Identity rules, generators and neutral names**, and a facts script that scans the guest for the
   giveaway words.
5. **Agent block**: port, path style, the finish folder, the interactive options.
6. **CAPE side**: the platform and tags, the analysis packages that actually work, and the host-wide CAPE
   switches the platform needs (they are not per guest).
7. **A normaliser** for what CAPE records for the OS. Without one the analyses show report-level data
   only, and the self-test lists report-level signals only.
8. **Self-test sample** buildable inside the `cape` image, and the signals it must produce.

### What CAPE's Linux support requires

From [S0e](../plans/m6-spikes/S0e-findings.md), read from the CAPE commit this repo pins and not run. It is
the starting list for the first Linux profile.

- **CAPE says so itself:** "Linux guests don't have official CAPE support", and the switch that allows
  submitting ELF files (`web.conf [linux] enabled`) ships off. Tartarus's `cape/conf/web.conf` does not set
  it, so a Linux submission is refused until a profile turns it on.
- **Guest requirements:** native 64-bit Python 3, the agent running as root, `sudo` and `strace`, a static
  address, the firewall and NTP off (the analyzer sets the clock with `date -s`). Screenshots need a GNOME
  Shell on D-Bus; `nohuman=yes` wraps the sample in `xterm`, which needs an X11 session.
- **The monitor is `strace` text,** streamed to `logs/strace.log`. There are no per-process BSON logs, so
  the live collector shows nothing for a Linux run until a Linux collector and normaliser exist. CAPE's
  parser for it (`[strace]` in `processing.conf`) is off by default.
- **A Linux analysis ends when the sample exits,** unless `enforce_timeout` is set; `interactive` is not
  read. The early-end trick works with a folder in `/tmp` instead of `C:\Windows\Temp`.
- **Platform gate:** with `machine=<label>` CAPE refuses a sample whose detected platform differs from the
  machine's; anything that is not an ELF or a shell script is classified `windows`. A Python, Perl, `.deb` or
  `.jar` sample sent to a Linux guest is refused unless CAPE's platform detection is changed.
- **Packages:** `zip`, `wget` and `ps1` are broken or unreachable at the pinned commit by inspection, and
  there is no `url` package; the rest need their runtime installed in the guest. A profile's `packages`
  list should leave the broken ones out.
- **Not yet in the schema** (deferred to the first non-Windows profile): per-package runtime requirements,
  host-wide CAPE settings a profile needs, a profile `extends` (so two distributions share an apt and
  systemd base), and showing CAPE's unofficial status on the profile's card.
- **Unverified:** everything about Ubuntu autoinstall, cloud-init and preseed, whether a remastered ISO
  boots under the Secure Boot firmware, and whether CAPE's Linux analyzer works at all at this commit.

## Tests that gate a profile

| Test | What it keeps true |
|---|---|
| `cape/tests/test_profile.py` | The schema loader: every field, every refusal and its message, the round trip through `to_dict`, conditions. Runs on fixture profiles (`cape/tests/fixtures/profiles/`), including a Linux one and a fake one |
| `cape/tests/test_clone_pipeline.py` | Every profile in `guest/profiles/` loads, and every step its pipelines name exists |
| `cape/tests/test_engine_generic_code.py` | The grep gate: no line of `cape/guest_engine/*.py` outside `protocol.py` may match `windows`, `defender` or `powershell`, except two lines of schema vocabulary in `profile.py` |
| `cape/tests/test_windows_profile.py` | The giveaway scan: no file the Windows profile ships contains a giveaway word, outside a short allow-list (the sample's source, Microsoft's EICAR text, the adoption block). A new profile needs the same scan |
| `cape/tests/fixtures/fake_profile/` | A fake profile (two trivial steps, an option, a pause) that runs the sequencer, the engine, the form schema and a clone with no Windows file involved |

The grep gate covers the engine only. `backend/app/guest/selftest_verdict.py` still names three Windows
facts it shows on a guest's card (`defender.*`), and the frontend has a few strings that say "Windows ISO";
no test keeps those two places free of OS words.
