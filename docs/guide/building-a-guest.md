# Building a guest

A guest is the Windows VM that samples run in. Tartarus builds it from a Windows ISO that you supply. Each analysis starts from a clean snapshot of the guest, so a sample never sees a previous one.

Tested: Windows 11 25H2 (Polish) and Windows 10 22H2 (English International). Other languages were not tested; the keyboard list covers thirteen layouts.

## Before you start

1. Copy your Windows ISO into `data/iso/` inside the repository folder. The folder is mounted read-only into the `cape` container. Nothing is uploaded from the browser.

   ```bash
   cp ~/Downloads/Win11_25H2.iso data/iso/
   ```

2. Open **Guest VM** in the menu and press `[+ NEW GUEST]`. The wizard opens at `/guest/new`.

Until a guest is ready, samples cannot run. The Submit dialog then says `No guest is ready`.

## The wizard

**1. CHOOSE MEDIA.** Every file in `data/iso/` is listed with its size and the profile that recognised it. The list also shows the version, build, language, architecture and number of editions. A file that Tartarus does not recognise is listed disabled, with the reason. Press `[RELOAD]` after you copy a new file in.

**2. SETTINGS.** Four groups:

- **GUEST.** The guest's name, shown only to Tartarus: 2 to 32 lowercase letters, digits and hyphens, starting with a letter. The name must be free and must not be `kvm` or end in `-clean`. If the ISO has several editions, pick one here.
- **INSIDE THE GUEST.** The account, the computer name and the password. Leave them blank and Tartarus generates realistic ones. `[RANDOM]` clears a field so it is generated at build time.
  - Account: starts with a letter, up to 20 letters, digits, `_` or `-`. `Administrator`, `Guest`, `DefaultAccount`, `SYSTEM` and `WDAGUtilityAccount` are reserved.
  - Computer name: up to 15 letters, digits or hyphens, not all digits, not `localhost`.
  - Password: 8 to 64 printable characters.
  - The account and computer name must not contain words that tell a sample what the machine is: `tartarus`, `sandbox`, `malware`, `virus`, `cuckoo`, `cape`, `test`, `admin` or `analy...`. The wizard says which word it refused.
- **RESOURCES.** vCPUs (default 2), RAM (default 4 GB) and disk (default 80 GB, at least 64 GB for Windows).
- **OPTIONS.** For Windows:
  - **Microsoft Defender**, on by default. Leave it on to see how a sample meets Defender. Turn it off for samples that Defender would remove before they run. With it off, the build turns Tamper Protection off with a scripted step.
  - **Make it look used**, off by default. Adds documents, downloads, pictures and a recent-files trail.
  - **Sysmon**, on by default. Logs process, network, file, registry, DNS and WMI activity.
  - **Product key**, optional. Without one, Windows installs unactivated.
  - **Keyboard layout**, default `Polish (Programmers)`.

**3. REVIEW.** Check the values and press `[BUILD GUEST]`. The page warns that the build takes about 15 minutes and that no analysis can start until it is done. In the tests a build took about 16 minutes.

## The build page

After you press `[BUILD GUEST]` the page opens at `/guest/builds/<id>`. It shows:

- a phase badge (`RUNNING`, `PAUSED`, `FAILED`, `SELF-TEST`, `READY`, `SELF-TEST FAILED`) and the percent;
- one row per step, with its status and duration: `preflight`, `fetch`, `define`, `install`, `provision`, `tamper-off` (Defender off only), `symbols`, `snapshot`, `register`;
- the `BUILD LOG`;
- the `DESKTOP` panel, which shows the guest's screen during the steps that need one. You can click into it to help a step.

After `register`, Tartarus runs a **self-test**: a short analysis that checks the guest reports what it should. If it passes, the guest becomes `READY`. If it fails, the guest becomes `FAILED`.

### When a step waits for you

If the scripted Defender step cannot find the Tamper Protection switch, the build pauses. An amber `WAITING FOR YOU` block appears. On the desktop below it, open Windows Security, go to the threat protection settings, switch Tamper Protection off, and press `[CONTINUE]`.

### When a step fails

A red block names the failed step and its error. Then choose one:

- `[RESUME]` runs the failed step again. Steps before it are kept.
- `[RESTART]` starts again from `preflight` and throws away what was done.

A guest that failed during a build step has no snapshot and no self-test, so `[RE-RUN SELF-TEST]` is not offered. Resume or restart the build instead.

### Cancelling

`[CANCEL BUILD]` asks first. The running step is stopped, the build ends as failed, and the guest is kept. You can then resume, restart or delete it. A paused build can be cancelled too.

## Cloning a ready guest

On a `READY` guest's card, press `[CLONE]`. The clone copies the source disk and gets its own identity, in about 5 minutes and about 22 GB.

- You choose the new name, the computer name, vCPUs and RAM.
- You can switch Defender and "Make it look used" on or off.
- The account, password and disk size are the source's and cannot be changed. A different account needs a full build.

## The guest cards

The **Guest VM** page shows one card per guest. Each card shows its state (`BUILDING`, `TESTING`, `READY`, `FAILED` or `BROKEN`), its badges, and its account and password. Press `[REVEAL]` on the password to log into the guest desktop yourself.

On a `READY` guest:

- `[RUN CHECKS]` checks the domain, the snapshot, the CAPE registration and the agent.
- `[CLONE]` makes a copy, as above.
- `[DELETE]` removes the guest's VM, disk and snapshot and unregisters it from CAPE. Analyses that used the guest keep their data. This cannot be undone.

A `FAILED` guest can be deleted, and it keeps its name and address until you do.

## Limits and rules

- **Five guests at most** can be building, testing or ready. A `FAILED` guest does not count, but it keeps its name and disk until you delete it.
- **Each guest is a full copy** of about 22 GB on disk.
- **Builds, clones and deletes wait for analyses.** They are refused while an analysis is queued, starting or running on any guest. Registering or deleting a guest restarts CAPE, and that would kill a running analysis.
- **Analyses wait for builds.** While a guest is building or testing, the backend refuses new analyses with `A guest is being built`.

Details are in [the guest profiles spec](../specs/guest-profiles.md) and [the CAPE integration spec](../specs/cape-integration.md#building-checking-deleting-and-analysing-exclude-each-other).

## From the command line

`make build-guest` builds the Windows guest without the wizard. It reads the `GUEST_*` values in `.env`. The wizard is the way the app documents; use the command only if you need it. See [the README](../../README.md#the-guest).
