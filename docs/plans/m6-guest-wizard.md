# Plan: M6, the guest wizard and several guests

M0b proved the Windows guest can be built unattended (`make build-guest`, 13.6 minutes, no input) and
checked (`make verify-guest`). M6 turns those two scripts into the product feature: an analyst with an
ISO in `data/iso` builds, checks and deletes guests **from the GUI**, with the backend in charge and no
shell on the host. **There can be several guests** (for example Windows 11 with Defender on and the same
with it off), and **the analyst chooses one for every detonation**. It builds what the
[CAPE integration spec](../specs/cape-integration.md#guest-vm-build-wizard) (the wizard, the health checks),
the [backend spec](../specs/backend.md#guest) and the [GUI spec](../specs/gui.md) (the Guest VM page, the
Submit dialog) describe, and changes them where they assume one guest (decision 5). **Guest creation is
OS-independent**: Windows is the first of several possible *guest profiles*, so a Linux guest later is a new
profile, not a rewrite (decision 17).

## Status

Planned 2026-10-15 and accepted by the user the same day, after three revisions for their requirements:
several guests (decisions 5 to 7), cloning a guest (15), analyst-chosen names and no giveaways in the guest
(3, 16), and guest creation independent of the OS (17). Decisions 1, 2, 5, 6, 7, 10, 15, 16 and 17 change
what the specs say; the specs are updated as the tasks land, not before. Wave 1 (spikes) is next; nothing
else is built.

## Outcome

- **Guest VM page** (`/guest`): one card per guest (name, OS label and edition, Defender on/off, resources,
  IP, snapshot date, health checks with `[RUN CHECKS]`, last self-test, disk used, `[DELETE]`), a
  `[+ NEW GUEST]` button and a default-guest marker.
- **Build wizard** (vertical QStepper at `/guest/new`): choose an ISO (listed with edition, build and
  language read from the image), settings (the guest's **name** in Tartarus, edition, optional key, keyboard
  layout, the Windows **username** and **computer name** with a `[RANDOM]` button for each, password, vCPUs,
  RAM, disk, decoys, Defender), review, then the build with per-step progress, a log
  tail, the live desktop during install and provision, and Retry, Resume and Restart.
- **Choosing a guest per detonation:** the Submit dialog has a GUEST select listing the ready guests, each
  with OS and a Defender badge; the default comes from Settings. The analysis records which guest ran it,
  and its header, the Dashboard row and the report show it.
- **Clone a guest** (`[CLONE]` on a card): copies a ready guest, gives the copy its own identity and address,
  changes what the analyst asks for (Defender on or off, decoys, resources) and takes a fresh snapshot. No
  Windows install, so it takes minutes instead of 14, and the copy passes the same self-test before it can
  be picked.
- **Names the analyst chooses, and no giveaways in the guest.** The username and the computer name are set
  per guest (random and realistic by default), so a sample cannot recognise the sandbox by a name like
  `Analyst`, and the API refuses names that say what the machine is. Nothing Tartarus puts in the guest
  carries the product's name either (decision 16). The name a guest has in Tartarus (its label) is free to
  be anything, because Windows never sees it.
- **Any OS can be added later without touching the wizard's core.** What differs between operating systems
  (installation media, unattended install, provisioning, options such as Defender, naming rules, the
  self-test) lives in a *guest profile* directory; the sequencer, registry, cloning, snapshots, CAPE
  registration, health checks, job, desktop and the whole GUI are shared and driven by it. M6 ships one
  profile, Windows, and proves the seam with a second, fake profile in tests and a written Linux design
  check (S0e). A short guide, "adding an OS", is part of the deliverable.
- **Defender choice per guest:** on by default and needing no manual step; "off" makes that build pause
  once for the Tamper Protection step, with instructions and the desktop.
- **Builds never disturb the other guests:** a new guest is added beside the existing ones and joins CAPE only
  once its self-test has passed; a failed build leaves every other guest registered and ready.
- **Self-test through Tartarus itself,** run on the guest being built: the bundled benign sample as an
  ordinary analysis, plus an EICAR check that proves that guest's Defender is really on or off. pafish runs
  as information only.
- **No weaker isolation:** libvirt's TCP endpoint stays off, the Docker socket is never mounted. The
  backend reaches the build only through a narrow, authenticated control service in the `cape` container.

## What exists and what is missing

| Exists (M0b, M1 to M5) | Missing |
|---|---|
| `scripts/build-guest.sh`: the whole build as bash, driven from the host with `docker compose exec`; `guest/` templates and `provision.ps1`; `manifest.sha256` | Runs only on the host; one hard-coded ISO, edition 5, pl-PL, label `win`, IP `.10`; no state, so no resume; destroys the previous guest first |
| One registration file per guest in `kvm.conf.d/`, where **the last file read wins** (M0b) | A registration listing every ready guest |
| `scripts/verify-guest.sh`: checks 8 to 12 and the facts script | Not callable by the backend; submits straight to CAPE, not through Tartarus |
| `cape/bin/finish-run`: the pattern for "the backend asks a helper inside `cape`"; its guest agent URL is fixed at `192.168.150.10:8000` | No equivalent for libvirt (`libvirtd` has no `--listen`, enforced by `make verify-cape`); finish-run cannot reach a second guest |
| Job runner, `job` table, `JobType.GUEST_BUILD`, `job` messages on `/ws/system` (M5) | No `guest_build` handler |
| Desktop proxy to `guacd` (`app/desktop`) for a running task | No target for a build domain |
| `POST /analyses` with `route`, `timeout`, `package`, `interactive`; the backend submits to CAPE with the configured `GUEST_LABEL` (`win`) | No `guest` option; the Submit dialog has no guest select |
| Header guest dot (`GuestCheck`: the one configured machine is listed and not locked), `[BUILD GUEST]` on the empty Dashboard | `/guest` is a placeholder page; no `/guests` endpoints |

## Decisions

1. **Control service, not libvirt over TCP (resolves [open question 1](../features/tartarus-v1.md#open-questions)).**
   Option (c) of the open question, with (a) added. A `guest-control` program in `cape` (stdlib HTTP, the same
   shape as `finish-run`) exposes only: list ISOs, list/read/delete guests, start/resume/restart a build with a
   validated parameter set, build status and log, run checks on a guest, continue after the manual step,
   and the build domain's display. It listens on a new network `tartarus-control` shared only by `cape` and
   `backend`, and requires a bearer token (`GUEST_CONTROL_TOKEN` in `.env`, like `CAPE_API_TOKEN`).
   `libvirt-python` is not used and the `qemu+tcp` endpoint stays off, so `make verify-cape`'s two checks
   keep holding and gain: the control service answers the backend with the token, refuses without it, and is
   unreachable from `frontend`, `opensearch` and `postgres`. **Docs to change:** architecture, backend spec
   (`guest/` module), cape-integration ("Re-enabling it for the wizard"), v1 decisions table and open
   question 1. **Confirm.**
2. **One build implementation: the bash steps move into the `cape` image.** `build-guest.sh` is the part
   proven on a real 13.6-minute run, so it is not rewritten in Python. Its functions are split into step
   files: the generic ones under `guest/steps/` (preflight, define, snapshot, register, copy; the self-test is the
   backend's, decision 9) and the OS-specific ones (install, provision, reconfigure) under
   `guest/profiles/<os>/steps/` (decision 17), installed in the image and run natively there (the `docker compose exec`
   wrappers go away). A thin Python sequencer in the control service runs them as subprocesses and keeps
   one `state.json` **per guest** on the `guest-images` volume (parameters, completed steps, current
   step, log file), which gives resume and restart. `make build-guest` becomes `docker compose exec cape
   guest-build` with the same defaults, so there is one way to build and the M0b checks keep working.
   **Confirm.**
3. **Parameters are validated at the control service, not trusted from the backend.** Guest name is a
   slug `[a-z][a-z0-9-]{1,31}`, unique, and becomes the libvirt domain name and CAPE machine label (so
   it must not be able to collide with a file path or a CAPE section; it exists only in Tartarus, libvirt and
   CAPE, never inside Windows); ISO is a plain file name found in `/data/iso`; edition is an index that the
   scan listed; **username** `[A-Za-z][A-Za-z0-9_-]{0,19}` and **computer name** (Windows' own rule: 1 to 15
   characters of `[A-Za-z0-9-]`, not all digits, no leading or trailing hyphen), both optional, defaulting to
   a random first name and a random `DESKTOP-XXXXXXX` or `LAPTOP-XXXXXXX`; both are refused if they contain
   a giveaway (`tartarus`, `cape`, `sandbox`, `malware`, `virus`, `analy`, `cuckoo`, `test`, `admin` as a
   whole name and similar; one list, in one place, shared by the build, the clone and the form's hint) and
   `Administrator`, `Guest` and the other reserved names that Windows itself refuses; the password defaults to
   a random one (autologon keeps it in the registry in plain text, where any process can read it), 8 to 64
   printable ASCII, XML-escaped by the renderer (a test proves a hostile value cannot change the document); product key `XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`; resources within host-derived
   limits. Values travel in the state file and environment, never interpolated into a shell command line.
   The password is kept in the guest's `guest.json` (shown on the card, so the analyst can log into the
   desktop), readable only by the control service and the backend; it is still in plain text in the guest
   for autologon, as M0b noted.
4. **Reading installation media without extracting 7 GB** (the Windows inspector; decision 17 makes this one
   of several). The spec says extract `install.wim` once to scratch. S0a
   first tries a loop mount of the UDF image (the container is privileged) and `wiminfo` on the mounted
   file, which reads only the XML metadata; fallback is the spec's extraction by 7-Zip. Results are cached
   by (name, size, mtime), and the scan is shown with progress. Needs `wimtools` in the image.
5. **Several guests: a registry, distinct addresses, one registration.** This lifts CAPE's
   one-registration-at-a-time limit from M0b.
   - **Registry.** Each guest has its own directory on the `guest-images` volume (`guests/<name>/`: `guest.json`
     with name, OS, edition, Defender, resources, IP, state, self-test result; disk, nvram, snapshot memory
     and overlay). The control service owns it; `guest.json` is the one source of truth, and the libvirt
     domain, the CAPE registration and the backend's view are derived from it.
   - **State:** `building` → `testing` (registered, hidden from the Submit dialog) → `ready`, or `failed`
     (unregistered, files kept so a step can be retried). Only `ready` guests are offered for detonation.
   - **Addresses.** Every guest gets its own static IP, the next free one from `.10` (`.10`, `.11`, …), set in
     provisioning (`provision.ps1` already takes `-GuestIp`). Two machines sharing one IP is the part CAPE's
     machine table and the rooter's per-IP rules might not tolerate; S0b settles it, and distinct
     addresses cost nothing. At most 5 guests (a `/24` is not the limit; disk is).
   - **One registration.** The control service renders a single `kvm.conf.d/guests.conf` with
     `machines = a,b,c` and a section per guest, from every `testing` and `ready` guest, and restarts `cape`.
     This replaces the file-per-guest writes of `build-guest.sh`.
   - **Adoption.** The guest M0b built (`win`, `.10`) is adopted on the first start of the control service: its
     `guest.json` is written from the domain XML and the registration file, nothing is rebuilt. `make
     verify-guest` and the e2e keep working with `win`.
   - **Each guest is a full, independent disk** (about 22 GB used), whether it came from a 13.6-minute build or
     from a clone (decision 15). Nothing is shared, so deleting any guest is always safe. A linked clone
     (the copy backed by the source's disk) would save the 22 GB but ties the two guests' lifetimes; left out
     (see "Not in M6").
   - **Docs to change:** cape-integration (supported guests, "Only one guest is registered at a time"),
     backend spec (`/guest` → `/guests`), GUI spec (Guest page, Submit dialog, Settings), v1 open question 5,
     overview. **Confirm.**
6. **The analyst chooses a guest per detonation.** `POST /analyses` options gain `guest` (a ready guest's
   name); omitted means the default guest, a new Setting (the first ready guest until chosen). It is stored in
   `analysis.options` with the other options (no migration) and passed to CAPE as the task's `machine`, replacing
   the single configured `GUEST_LABEL`. `409` with the reason when that guest is not ready or does not exist.
   The analysis page header, the Dashboard row and the report show the guest's name and Defender state; for a
   guest deleted since, the stored name is shown plainly. `finish-run` takes the guest's address with
   each request instead of its fixed default (the backend knows which guest the analysis used; the
   control service validates the address lies in `GUEST_SUBNET`). The v1 rule "one analysis at a time"
   stays, enforced by the backend's queue as today, so two guests never run together. **Confirm.**
7. **Builds, deletes and analyses exclude each other.** Registering or deleting a guest restarts `cape`, and
   `cuckoo.py` powers off a running registered machine when it starts (M0b), which would kill an analysis. So
   while a build is running `POST /analyses` answers `409` with the reason; a build's register step, a
   delete, a build start and `[RUN CHECKS]` (which reverts a snapshot) are refused with `409` while an
   analysis is queued, starting or running. The cost is that no sample can be detonated for the 14 minutes
   of a build; narrowing the exclusion to the register step is a possible refinement. The Agent check runs on
   demand only: CAPE reverts the snapshot before every task, so "before each analysis" would do it twice.
   **Confirm (spec change).**
8. **No in-place replacement.** The earlier "rebuild replaces the guest after the new one passes" is
   dropped: adding a guest beside the others makes it unnecessary. `[CLONE]` (decision 15) is the fast way to a variant of an existing guest; `[REBUILD]` on a card opens the wizard
   prefilled with that guest's settings and a new name; the analyst deletes the old guest when happy. A
   failed build is `failed` and unregistered, so it can never be picked and never disturbs the others.
   Deleting a guest removes its domain, snapshot, disks, nvram and registration; analyses that used it keep
   their data and the stored name.
9. **Self-test goes through Tartarus, on the guest being built.** The backend creates an analysis from the
   bundled sample through the same code path as `POST /analyses` with `guest` set to the new guest (tag
   `self-test`), waits for `done`, and checks the analysis' own data: process-lane and file events from the
   live feed, a registry event, the INetSim DNS answer, a report. The result is stored in that guest's
   `guest.json` (through the build job) and shown on its card with a link to the analysis. `benign.exe` is
   compiled with mingw in the `cape` image at image-build time (today it is compiled in a throwaway Ubuntu
   container by the scripts), served by the control service; the scripts' `build_sample` helper then reads it
   from the image too, so there is one build of it.
10. **Defender is a per-guest property; verified by EICAR.** This resolves [open question 5](../features/tartarus-v1.md#open-questions)
    with *several guests* instead of the v1 proposal of one: the state is baked into each guest's snapshot,
    so "Windows 11, Defender on" and "Windows 11, Defender off" are two guests and the analyst picks one at
    submission (decision 6). The self-test writes the EICAR string (assembled at runtime from two halves,
    never stored whole in the repo, so no scanner on a dev machine quarantines it) and requires: **on**, the
    file is removed or a detection is logged within 30 s; **off**, it stays. A mismatch fails that guest's
    build. "Report what Defender did" in an analysis touches the ingest and the normalisers, not the
    wizard, so it **moves out of M6** to its own item. **Confirm.**
11. **The Tamper Protection pause is a state of the build, not a special case.** After provision, with Defender
    "off", the build enters `waiting_for_user` (job status `paused`, step `provision`), the guest stays
    running, the page shows the instructions and the build domain's desktop, and `[CONTINUE]` makes the
    control service re-run the Defender settings through the guest agent (`/execute`, `C:/` paths) and check
    `Get-MpComputerStatus`. If they still read "on", the pause comes back with the reason. Whether the
    settings take once Tamper Protection is off has never been observed; S0c settles it with the user.
12. **Sysmon and decoys are in, pafish is a stretch.** Sysmon (skipped in M0b) is installed from a pinned
    binary in `manifest.sha256` with `guest/sysmon-config.xml`; the check here is only that the service runs
    and its log has entries. Decoys are one provisioning script (documents, browser history, recent files)
    driven by a flag. pafish is built from a pinned source commit with mingw in the image and run through
    the guest agent after the self-test, its output shown as information only; it is the first thing cut if
    the milestone runs long.
13. **Windows 10 22H2 is accepted by the wizard but not verified.** Only a Windows 11 25H2 ISO exists here.
    The scan, the answer file and the domain make no Windows-11-only assumption beyond the TPM (harmless
    on 10), and the card says "verified on Windows 11 25H2".
14. **One job type, one feed.** The wizard is `JobType.GUEST_BUILD` on the M5 runner. The handler polls the
    control service and relays `(step, percent)`, the log tail and the paused state through the existing
    `job` messages. The control service, not the backend, owns the truth: after a backend restart the
    runner finds the running build and reattaches instead of marking it interrupted. One build or clone at a time.
15. **Cloning a guest.** `POST /guests/{name}/clone` makes a new guest from a `ready` one, as the same job type
    with a different front half of the pipeline. Build: preflight → define → install → provision → snapshot →
    register → self-test. Clone: preflight → **copy** → define → **reconfigure** → snapshot → register →
    self-test. Preflight, define, snapshot, register and the self-test are the same step files and the same
    code (rule 3); only copy and reconfigure are new.
    - **Copy from the source's base disk, never from its snapshot.** The snapshot's memory image holds the
      emulated hardware's state (MAC, device registers), so it cannot be restored under a new identity. The
      source's base `qcow2` is immutable (it is the snapshot's backing file) and holds the guest's state at the
      moment of the snapshot, so it is copied with `qemu-img convert` (sparse, independent of the source), together
      with the nvram (boot entries, Secure Boot variables). The copy cold-boots like a machine after a power
      cut. A new swtpm state is created rather than copied, so two guests never share a TPM identity.
    - **New identity:** UUID, MAC, SMBIOS and board and disk serials from `generate_identity`, the computer name
      the analyst gave (or a new random one; the same validation as a build, so never the source's), the next
      free IP. The copy is defined with these, so nothing of the
      source's hardware identity survives.
    - **Reconfigure** boots the copy at the source's old address (the source is powered off; an exclusion rule,
      decision 7, keeps analyses from using it at the same time), waits for the agent, then through the
      agent (`/execute`, `C:/` paths): sets the new IP, renames the computer, applies the requested changes, and
      reboots once. The settings that make sense on a copy are: **computer name**, **Defender** on or off,
      **decoys** (added), **resources** (vCPUs, RAM); inherited and shown greyed: ISO, edition, language,
      keyboard, username and password, disk size. The username is inherited because renaming an account
      leaves its profile folder (`C:\Users\<old name>`) behind, which is a worse giveaway than the name; a
      different username needs a build.
    - **Defender off** needs the Tamper Protection pause of decision 11 when the source had it on, exactly as in
      a fresh build (the desktop shows the copy at its temporary address). **Defender on** from a source that has
      it off is scripted; S0d checks that it takes.
    - The snapshot, registration and self-test then run as for a build, on the copy, with its Defender
      verdict (decision 10). A clone that fails ends `failed`, unregistered, with the source untouched.
    - **S0d decides the details** (new MAC and TPM under the same Windows, the cold boot from a crash-consistent
      disk, the IP change on the existing adapter); if the new MAC makes Windows treat the adapter as new, the
      reconfigure step finds it by hardware instead of by name, as `provision.ps1` already does.
      **Confirm.**
16. **Nothing in the guest says Tartarus.** M0b's guest has, readable by any process in it: the folder
    `C:\tartarus` (the agent, the installers and `provision.log`, kept for good), a firewall rule called
    "Tartarus agent", the password `Tartarus1!` in the autologon registry value, the username `Analyst`, a
    fixed computer name, and, during the build only, an install CD with the volume label `TARTARUS` and a
    `tartarus-provision.marker` file. The build and the clone change all of these:
    - the working folder is a per-guest neutral path chosen at build time (for example
      `C:\ProgramData\<random 8 letters>`, stored in `guest.json`; the scripts read it, `C:\tartarus` goes away
      from the scripts, `build-guest.sh` and `verify-guest.sh`), and it holds only what the agent needs after
      provisioning: installers and the log are removed at the end of provisioning (the log is fetched by the
      build first);
    - the firewall rule, the scheduled task and every other name the provisioning creates are neutral
      ("Windows Remote Assistance Service" style, one table in one place);
    - the install CD's volume label and marker are neutral and the CD is ejected before the snapshot as today;
    - username, computer name and password come from decision 3, not from constants.
    **A test is the gate:** the rendered answer file, the provision and reconfigure scripts and the step files
    are scanned, case-insensitively, for `tartarus`, `cape` and `sandbox` (a small allow-list of the files the
    CAPE agent itself needs); and the self-test runs `guest-facts.ps1` (extended) inside the guest, which looks
    for the same words in the computer name, accounts, scheduled tasks, services, firewall rules, `Run` keys and
    the top-level folders, and **fails the build** if it finds any. **Not fixed, and said so on the card:** the
    guest M0b already built (`win`, adopted by decision 5) keeps its `Analyst` account, `C:\tartarus`
    and its other names, and so does every clone of it except for the computer name; rebuilding is the way to a
    clean one. CAPE's own traces during a run (its analyzer folder in `%TEMP%`, the agent process) are CAPE's
    and are not addressed here.

17. **Guests are OS-independent; Windows is the first guest profile.** Decisions 3 (the Windows name rules),
    4, 10, 11, 12, 13 and 16 describe the **Windows profile**; everything else in this plan is generic and
    must not mention Windows in its code. The seam is drawn only where operating systems certainly differ,
    and it is data plus step files, not a plugin framework (no dynamic loading: a profile is a directory in
    the repo, installed in the `cape` image, so rule 3's warning against premature abstraction is met by
    drawing it where the variation is known and checking it against a second profile, below).
    - **A profile is a directory** `guest/profiles/<id>/` with:
      - `profile.json`, validated against one JSON schema: `id`, display name, family (`windows`, `linux`),
        CAPE `platform` and `tags`, `arch`, firmware (`uefi-secureboot-tpm` or `bios`), default resources and
        minimum disk, the **media inspector** it uses, the **options** it offers (each: key, label, type,
        default, help text, optional `requires_user_step`; Windows: `defender`, `decoys`, `sysmon`, `key`,
        `keyboard`), the **name rules** (username and computer-name patterns, reserved names, the giveaway
        list), the **clone** capabilities (which options can change on a copy, which names), the **pipeline**
        (the ordered step names for a build and for a clone; each is either a generic step or one of the
        profile's own), the **agent** (port and how to wait for it), the **self-test** (the sample file, the
        signals it must produce, the optional extras such as pafish), and the **packages** CAPE accepts for it
        (`exe`, `dll`, `doc`… for Windows; `elf`, `sh`… later);
      - `domain.xml.tpl`, the unattended-install templates, the provisioning and reconfigure scripts, the
        facts script and its steps. The Windows ones are today's `guest/` files, moved.
    - **The step contract:** a step is an executable that reads the guest's `guest.json` and the profile from
      its environment, writes progress lines (`STEP`, `PROGRESS n`, `LOG …`) and exits 0, non-zero, or with
      the code for "waiting for the user", in which case it first writes the instructions to show. The
      Tamper Protection pause (decision 11) is the Windows profile's use of that generic pause; a Linux
      profile could use it for anything else. A step is idempotent, so resume can re-run it.
    - **What becomes generic** (changes to earlier decisions): `guest.json` keeps `os` (the profile id) and an
      `options` object instead of a `defender` field; the cards and the Submit dialog show **badges the
      profile derives from the options** ("DEFENDER ON" for Windows), not a Defender flag; the wizard's
      settings step and the clone form are **rendered from the profile's option schema**
      (`GET /guests/profiles`), with the Defender explanation as the Windows option's help text; the
      media list is `GET /guests/media` (installation media of any kind: an ISO or a disk image), each entry
      tagged with the profile that recognised it; the package list of the Submit dialog comes from the chosen
      guest's profile; the self-test verdict (decisions 9 and 16) takes the **signals the profile lists**
      (Windows: process, file, registry, DNS, EICAR verdict, no giveaways; a Linux one would have no
      registry) and the facts script the profile names.
    - **What stays outside the seam:** how a run of that OS is **read** by Tartarus. The events of a Linux run
      need a normaliser for CAPE's Linux analyzer output ([the Normalizer protocol](../specs/data-model.md)), which
      is its own piece of work; until it exists a Linux guest could be built and run by CAPE but its analyses
      would show the report-level data only. The self-test of such a profile therefore lists only
      report-level signals, which the schema allows.
    - **The proof that the seam is right** is not a Linux build (post-v1) but three cheaper things: S0e reads
      CAPE's Linux support in the pinned commit and writes the Linux profile on paper, field by field, listing
      anything the schema or the step contract cannot express (fixed before C2); a **fake profile** in the
      tests (two trivial steps, one option, one pause) runs through the sequencer, the job, the form
      schema and the clone with no Windows file involved; and a CI test validates every profile in the repo
      against the schema and checks that each step it names exists.
    - **Docs:** a new spec, `docs/specs/guest-profiles.md` (the schema, the step contract, a checklist for
      adding an OS: media inspector, unattended install, provisioning, agent, CAPE platform and monitor,
      normaliser, self-test sample), linked from cape-integration, whose wizard section is cut down to what
      is generic. **Confirm.**

## Waves

Tasks marked **care** follow rule 5's extreme-task process on Sonnet: small steps that each end in a
check that can fail, a notes file (done / running / next), and the planner re-runs the checks and reads
the diff before committing. Every task is test-first; every visual one ends in screenshots and one
Artifact per screen (rule 4). Pure logic (parameter validation, template rendering, wiminfo parsing, the
step state machine, registration rendering, address allocation) is tested with no containers; anything
needing libvirt or a guest is a named `verify-*` script check.

### Wave 1: spikes (parallel; findings appended to this plan)

| ID | Task | Model | Question and check |
|---|---|---|---|
| **S0a** | ISO metadata | Sonnet, **care** | Does a loop mount plus `wiminfo` work in `cape` on the UDF ISO, and how long does it take? Editions, build, languages and architecture parsed from the real ISO; behaviour on an `install.esd`, an ISO9660 image and a non-Windows ISO (small fixtures); the 7-Zip fallback's time and scratch use |
| **S0b** | Two machines in CAPE | Sonnet, **care** | With the existing guest, define a clone domain at another IP and register both in one `guests.conf`: does CAPE list both; does `machine=<label>` run the task on the right one, with the right revert, ResultServer connection, rooter rule and callback; what restarting `cape` does to a running machine; can two machines share an IP (expected: avoid it); does anything in `cape/` hard-code `.10` (`finish-run`, `start-guest-network`'s DHCP range); which of `verify-cape`/`verify-guest` assume one machine. Nothing is committed |
| **S0c** | Tamper Protection | Planner with the user | The user turns Tamper Protection off on the live desktop of an interactive analysis; then `Set-MpPreference` through the agent: do the settings take? What the pause screen has to tell the user, step by step. **Needs the user (about 10 minutes).** Nothing is committed |
| **S0d** | Clone by hand | Sonnet, **care** | Without the product code: `qemu-img convert` the existing guest's base disk, copy its nvram, define a domain with a new UUID, MAC, serials and a fresh swtpm; does Windows cold-boot cleanly (no recovery or repair screen, no activation or Secure Boot complaint), does the agent answer, can the IP and computer name be changed through the agent and survive a reboot (and does the computer name the analyst chose, not the generated one, end up in `hostname`, the registry and the DHCP/NetBIOS view), is `provision.ps1`'s adapter lookup enough for a new MAC; time and disk of the copy; after a snapshot and registration, does an analysis on the clone behave like the source's. Also: does enabling Defender through the agent take on a guest whose Tamper Protection is off (needs S0c's state, so it runs after it). Nothing is committed |
| **S0e** | Linux profile on paper | Sonnet, **care** | Read CAPE's Linux support at the pinned `CAPE_REF` (guest requirements, agent, `platform = linux` registration, packages, the strace-based monitor and its output) and write the Linux profile as a filled-in `profile.json` plus a list of its step files, in this plan; for every field and step say whether the schema and step contract of decision 17 express it. Anything they do not is a change to decision 17 now, before C2. Also: how a Linux guest would be installed unattended (Ubuntu autoinstall or Debian preseed through a second ISO or cloud-init) and whether the same external-snapshot, static-IP and clone approach holds. Nothing is built, nothing is run in a guest |

### Wave 2 (parallel, disjoint files)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **C1** | Control service | Sonnet, **care** | `cape/bin/guest-control` and the HTTP boilerplate it shares with `finish-run` (one module, `finish-run` moved onto it, and made to take the guest address per request, within `GUEST_SUBNET`); token auth; the `tartarus-control` network, compose and `.env.example` (`GUEST_CONTROL_TOKEN`); `verify-cape` checks (token, refusal, isolation from other containers, libvirt TCP still off) | Handler tests with a fake runner: auth, validation errors (decision 3), unknown routes, `finish-run` tests still green with the per-request address; the new `verify-cape` checks fail before the service exists |
| **C2** | Build engine, registry and profiles | Sonnet, **care** | The profile schema and loader (decision 17), validation of every profile in the repo, the step contract and the generic pause; the fake profile for tests; `build-guest.sh` split into generic steps under `guest/steps/` and the Windows ones under `guest/profiles/windows/steps/`, installed in the image; the sequencer and per-guest `state.json` (resume from the last completed step, restart from scratch, a failed step keeps its log); the registry (`guest.json`), address allocation, the single-registration renderer and the adoption of the M0b `win` guest (decisions 2 and 5); delete guest; `make build-guest` as a wrapper | Bash tests (`scripts/tests/`) for every pure helper as today; registry tests: allocation skips taken addresses and deleted ones, the registration lists exactly the `testing` and `ready` guests, adoption writes the right `guest.json` from fixture XML; sequencer tests with fake steps: order, failure, resume, restart, interruption mid-step, pause and continue; the fake profile end to end (build and clone, no Windows file touched); a profile with a missing step file or a bad schema is rejected at load; the full real build is Wave 5 |
| **C3** | Media scan | Sonnet | `GET /media` in the control service: the inspector interface (media file in, `[{profile, variant, version, language, arch}]` out) and the Windows inspector per S0a: metadata parser (pure), cache keyed by name, size and mtime, error cases (unreadable, not Windows, no `install.wim` or `.esd`) | Parser tests on `wiminfo` output fixtures including a multi-language and an ESD sample; cache invalidation |
| **C4** | Clone pipeline | Sonnet, **care** | The copy and reconfigure steps of decision 15 as step files in the same engine as C2 (so C4 follows C2's step interface, and runs in parallel with it against an agreed one): disk and nvram copy, new identity, fresh TPM, the agent-driven reconfigure (`guest/clone/reconfigure.ps1`, safe to run twice), clone parameters and their validation (decision 3: source must be `ready`, name unique, Defender and decoys flags, resources) | The pure parts: parameter validation, the identity differs from the source's in every field, the reconfigure script renders with hostile names escaped, a computer name equal to the source's or on the giveaway list is refused, the step list for a clone is exactly the one in decision 15; sequencer tests with fake steps for a clone failing at each step and leaving the source untouched. The real copy and boot are Wave 5 |
| **G1** | Windows profile | Sonnet | `autounattend.xml.tpl` with optional product key, keyboard layout, the edition index and the computer name; `profile.json` for Windows with its options, name rules, pipeline and self-test signals; the neutral names of decision 16 in every script, template and step (working folder, firewall rule, scheduled task, CD label and marker) from one table; the name generators and the giveaway list (one module, used by the build, the clone and the form's hint); extended `guest-facts.ps1`; `provision.ps1` parameters for IP, Defender, decoys and Sysmon; `decoys.ps1`; `defender-settings.ps1` (safe to run twice); the Sysmon pin in the manifest; the keyboard-layout table (one table: layout name to `InputLocale`) | Render tests (well-formed XML, escaping, optional elements absent when unset: the silent-failure case of M0b); PowerShell parsed with `pwsh` syntax check where available; the scan of decision 16 (no `tartarus`, `cape` or `sandbox` in anything rendered, outside the allow-list), which fails on today's `provision.ps1`; the giveaway list refuses each listed word as a whole name and as a part, and accepts ordinary names; name generators always produce valid Windows names |

C1 first in time within the wave (C2 and C3 plug into it); they run in parallel against its handler interface, agreed up front.

### Wave 3 (backend, after C1 to C3)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **B1** | Guest client and read endpoints | Sonnet | `app/guest/`: `GuestControl` protocol and its HTTP implementation (token, timeouts, errors to `502`); `GET /guests` (each guest's domain, snapshot, resources, IP, Defender, state, health checks, last self-test), `GET /guests/{name}`, `DELETE /guests/{name}`, `POST /guests/{name}/check`, `GET /guests/media`, `GET /guests/profiles` (the option schema, name rules and badge rules the GUI renders from); `GuestCheck` reports aggregate health (ok when at least one is ready, degraded when some are not) and the old `GUEST_LABEL` setting goes away | Endpoint tests against a fake client for every state (none, one ready, several, one failed, busy, building, control down); delete and check refused while an analysis is active; the aggregate health table |
| **B2** | Build job | Sonnet, **care** | `guest_build` handler, `POST /guests/build` (validated against the scanned ISO list and unique name), `POST /guests/{name}/clone` (decision 15; same job, same handler, the clone's step list), `POST /guests/build/{job_id}/resume\|restart\|continue`; progress, log tail and paused state on the `job` messages; reattach after a backend restart; the `409` rules of decision 7; one build at a time | Handler tests with a scripted fake control: success, step failure then resume, restart, pause then continue, still-on-after-continue, backend restart mid-build, concurrent start refused, duplicate name refused; a clone of a guest that is not `ready`, of a missing one, and during an analysis is refused; a failed clone leaves the source `ready` |
| **B3** | Self-test | Sonnet, **care** | The self-test step per decision 9, the EICAR check of decision 10 and the "no giveaways" facts check of decision 16 in the handler; the bundled sample served by the control service; the `self-test` tag; the verdict stored in the guest's record | Verdict function (pure) against fixture event sets: each missing signal fails with its own message; EICAR rules for on and off |
| **B4** | Build desktop | Sonnet | `WS /ws/guests/{name}/desktop`: the existing tunnel with a target resolver for the build domain's display (rule 3: no second proxy); available only during install, provision and the pause | Admission and tunnel tests, extending `test_ws_desktop` for the new resolver; `4408` outside those states |
| **B5** | Choosing a guest | Sonnet | The `guest` option on `POST /analyses` (validated against ready guests, `409` otherwise), the default-guest setting in `GET/PUT /settings`, the machine passed to CAPE from the option, the accepted `package` values taken from the chosen guest's profile, the guest name and Defender state in the analysis, Dashboard row and report summary, the guest address passed to `finish` | Option validation (unknown, not ready, default, omitted); the CAPE call carries the right machine; the setting round trip; the report summary shows the guest; `finish` uses the guest's address |

B1 first; B2 to B5 are disjoint files and run in parallel after it. The planner regenerates the API client after B1, B2 and B5.

### Wave 4 (frontend)

| ID | Task | Model | Deliverables |
|---|---|---|---|
| **F15** | Guests page | Sonnet | The page and routing (`/guest`, `/guest/new`): one card per guest with health checks, `[RUN CHECKS]`, last self-test and pafish summary, disk, `[CLONE]`, `[REBUILD]`, `[DELETE]` (confirm dialog showing the size freed), the default marker; the header guest popover listing every guest's state (one shared health component); empty "guest VM not built" state with `[BUILD GUEST]`; states: loading, control down, busy, a guest failed, error. Screenshots, one Artifact |
| **F16** | Wizard steps 1 to 3 | Sonnet | A profile picker when more than one profile can read the media (one entry today, so it is hidden), the settings step **rendered from the profile's option schema** (one generic option control per type; no Windows-specific markup), media list with detected metadata and the "put the ISO in `data/iso`" empty state, settings with the name field (explained as "only Tartarus sees this name"), the username and computer name fields each with `[RANDOM]` and the giveaway message from the API, and the Defender explanation, review; validation messages from the API. Also the clone form (`/guest/clone/:name`, one page: the new name, the computer name (`[RANDOM]`), Defender, decoys and resources, the inherited settings greyed (username with the reason), the time and disk it will take, the review warning). Screenshots, one Artifact for the wizard and one for the clone form |
| **F17** | Build progress | Sonnet | Per-step progress, log tail, Retry, Resume, Restart, the Tamper Protection pause with the desktop, the failed and success states, the building state on the guest's card. Reuses the desktop component of the analysis page. Screenshots of every state, one Artifact |
| **F18** | Choosing a guest | Sonnet | The GUEST select in the Submit dialog (OS and the profile's badges, disabled with the reason for a guest that is not ready; none ready shows the reason and links to `/guest`), the default-guest field in Settings, the guest chip in the analysis header and the Dashboard row. Screenshots, one Artifact |

F15 first (it holds the page and the routing); F16, F17 and F18 are disjoint components and run in parallel.

### Wave 5: proof

- **Unit and integration suites** for every task above, in CI as today.
- **`make verify-wizard`** (new, slow, about 20 minutes: one build, then clones), through the backend API only:
  1. Build guest A (Defender on) from the real ISO to a passed self-test, with the adopted `win` still
     registered and ready throughout; CAPE lists both.
  2. Detonate the benign sample on `win` and then on A; each analysis records the right guest and runs on
     it (their IPs differ in the PCAP).
  3. The chosen username and computer name are what `guest-facts` reports from inside A, and the giveaway scan
     finds nothing; a build asked for the computer name `SANDBOX-01` is refused with a readable message.
  4. Make a build fail at its self-test on purpose: it ends `failed`, unregistered, and `win` and A can still
     run an analysis.
  5. Check the `409` rules both ways (analysis during a build, build and delete during an analysis).
  6. Clone A into C with decoys on and a chosen computer name and Defender unchanged (no human step): C gets its own IP, MAC, serials and
     computer name, passes the self-test, and an analysis on C runs on C. Making a clone fail at its
     reconfigure step on purpose leaves A `ready` and C `failed`, unregistered.
  7. Delete C, then A: `win` still runs an analysis, their files are gone.
- **The Defender-off clone** (guest B, cloned from A) with the user at the keyboard for the Tamper Protection
  step, once, followed by a detonation on B with EICAR showing the opposite of A's. This is the "no 14-minute
  wait" case from the requirement; its time from `[CLONE]` to `ready` (minus the human step) is recorded
  against the target of under 8 minutes.
- **The seam:** the CI test that validates every profile against the schema and checks its step files; the fake-profile run through the sequencer, the job endpoints, `GET /guests/profiles` and the clone; `grep` of the generic code (`app/guest`, the control service's engine, `guest/steps`, the guest components of the frontend) finding no `windows`, `defender` or `powershell`.
- **`make e2e`** gains the browser flow: the Guest page lists the guests, the wizard lists the ISO and
  starts (cancelled at review), the Submit dialog offers the guests and the chosen one is recorded.
- **`make verify-cape`** with the control-service checks; **`make verify-guest`** still green on `win` and
  on a guest the wizard built.
- Docs: `docs/specs/guest-profiles.md` (decision 17, written by a Haiku task from S0e's findings and the final schema, then read by the planner against the code), the specs listed in decisions 1 and 5, the M0b "Silent failures the wizard inherits" list turned
  into the tests that cover each, the overview's M6 row marked done with what was and was not verified.

## Risks

| Risk | Handling |
|---|---|
| CAPE mishandles several machines (shared IP, ResultServer, rooter, restart behaviour) | S0b before C2; distinct addresses by decision 5; `verify-wizard` runs both guests |
| Registering or deleting a guest (restarting `cape`) kills a running analysis | Decision 7: the `409` rules both ways, tested |
| Moving the bash into the image breaks the proven build | The steps are moved, not rewritten; `make build-guest` runs the same code and is re-run before anything else is built on it |
| The control service becomes a root-equivalent API (the container is privileged) | Narrow operations only, validation in decision 3, a token, a network shared with one container; `verify-cape` enforces all four. It still turns a backend compromise into "can build and delete guests", not "can run anything" |
| Tamper Protection off does not make `Set-MpPreference` work | S0c first; if so, the "off" option is withdrawn or reduced to documented guidance, and decision 10 changes before F16 |
| The profile seam is drawn wrong because only Windows exists to test it against | S0e writes the Linux profile on paper first; the fake profile exercises everything generic; the `grep` gate keeps Windows out of the generic code; the schema is versioned so a second real profile can extend it |
| An unusual ISO (ESD, Windows 10, another language) breaks the answer file silently | The well-formedness and escaping tests; only the verified combination is claimed (decision 13) |
| The build outlives the backend | Control service owns state; reattach in B2 (decision 14) |
| Disk: every guest is about 22 GB, and a build needs scratch for the ISO scan | Preflight computes it from the actual files and refuses with the number; the cap of 5 guests; per-guest size on the card |
| 14-minute builds make the loop slow | Everything except `verify-wizard` runs without a guest; one full build in the proof wave, the rest by cloning |
| A clone that boots wrongly (power-cut recovery screen, new MAC seen as a new adapter, fresh TPM refused) | S0d before C4; the reconfigure step finds the adapter by hardware; if a crash-consistent copy cannot be made reliable, the fallback is cloning from a source that has just been shut down cleanly by the control service (the source then needs a fresh snapshot afterwards, so it is the last resort) |
| Defender back **on** in a clone does not take by script | S0d checks it; if not, a clone may only turn Defender off (or keep it) and turning it on needs a build |
| A clone inherits something that identifies the source (a leftover profile name, recent-file entries, the Windows install date) | Accepted for the same-user, same-image guest; the card says the guest is a clone of A. The hardware identity, which is what sandbox checks read, is new |
| A giveaway list is never complete; a determined sample finds other tells (CAPE's own agent, the display adapter, timing) | Said plainly on the card and in the docs: this removes the cheap checks (names, folders, rules, the password), not all of them; the list is one file so it grows as tells are found |
| Agents report results optimistically | The planner re-runs every gate and reads each diff before committing; no task is accepted on its own report (rule 5) |

## Not in M6

A real Linux (or other) profile and the normaliser that reads its runs (decision 17; each is its own milestone, with S0e's paper design as the starting point); report what Defender did in an analysis (decision 10); analyses running on two guests at once (the one-at-a-time
rule stays); linked clones that share the source's disk to save the 22 GB (decision 5); changing a clone's
username, language, edition or disk size (those need a build); ISO
upload by drag and drop; Windows hosts; the remaining anti-VM tells of
[open question 10](../features/tartarus-v1.md#open-questions) (empty optical drives, display adapter).
