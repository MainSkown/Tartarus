# Plan: M7, foundations (small fixes, closing questions)

M7 is the first milestone of the [finish line](finish-line.md): four fixes and removals that are small and
already decided, two things that need a real-guest spike before any code (**the `+60s` button** and **the
anti-VM tells**), the wizard's browser test, and closing the open questions in the docs. Nothing here adds a
new event source or page; the only new screens are the `+60s` button with its countdown and, if decision 4 is
confirmed, a `[CANCEL]` button on the build page.

## Status

Planned 2026-10-17 from the finish-line roadmap and a read of the code the tasks touch. Decisions
marked **Confirm** change scope or a spec and wait for the user before their wave starts.

**Wave 1 done 2026-10-17** (C1, D1, R1; commits 5e3fb3e, 56724c7): failed guests are off the cap, `finish-run` is
gone, and a resumed `reconfigure` waits for an earlier apply instead of racing it (tested against the bash suite's
fake agent; the real-guest drill is P1). The `cape` image was rebuilt and the container recreated; `win`, `lab1`,
`lab3` and `lab5` are ready. **S1 done 2026-10-17** ([findings](m7-spikes/S1-findings.md)): `+60s` is a go, with the
reference point and cap now in decision 5. **X1a, X1b, F1 and F2 done 2026-10-17** (commits 48c781f, 11c5a57, 222396f,
3297ee1, c954aa4): the `+60s` backend, the `[+60S]` button (right after the RUNNING badge in the LIVE status bar, as
the user asked in review) and the shared countdown; the user approved the button from the screenshot Artifact after one
round. The real-stack proof is P2. **S2 done 2026-10-17** ([findings](m7-spikes/S2-findings.md)): the drives ship, no display adapter does (decision 6). X2 is next; W1 and E1 wait for the answer to decision 4.

## Outcome

- Resuming a clone's `reconfigure` step never races an earlier apply, and a resume after a *finished* apply no
  longer fails on "the MachineGuid has to change".
- A `failed` guest does not count towards the five-guest cap, in the control service and in every message.
- `finish-run` is gone from the `cape` image, its tests and the docs; the backend still ends runs, through
  `guest-control` as it does today.
- New guests and clones have **no optical drives** and no ghost drive left in the registry. The self-test fails when
  a drive comes back or the display adapter is a worse one than today's; the Basic Display Adapter stays and is
  reported as a known tell (decision 6).
- `+60s` works on interactive runs: the analyst's deadline is kept in the analysis, enforced by the backend, and
  shown as a countdown in the analysis header and the LIVE status bar.
- `make e2e` includes a short browser flow of the build wizard against the real backend.
- [v1 open questions](../features/tartarus-v1.md#open-questions) 2, 3 and 10 say what was built, and the specs
  say Sysmon is final-phase only.

## What exists and what is missing

| Exists | Missing |
|---|---|
| `cape/guest_engine/validation.py:91` `_refuse_when_full` counts every guest in the registry against `MAX_GUESTS = 5`, whatever its state | Only `building`, `testing` and `ready` guests should count |
| `guest/profiles/windows/steps/reconfigure` reads the identity once at its start (`GUID_BEFORE`, `BOOT_BEFORE`), applies, waits for the guest's `rebooting <token>` log line, then checks the boot time moved | No wait for an apply that an earlier run left in flight; `verify_identity` requires the GUID to differ from the one read *this* run, which a resume after a finished apply can never satisfy |
| `finish-run` (supervisord program, `cape/bin/finish-run`, `scripts/tests/test_finish_run.sh`, `GUEST_IP` in `entrypoint.sh`, lint paths in the Makefile) next to `guest-control`'s own `/tasks/{id}/finish`; `finish_logic.py` and `control_http.py` are shared by both | Nothing uses `finish-run`: the backend calls `guest-control` (`backend/app/guest/client.py:201`) |
| `guest/domain/domain.xml.tpl` always renders two `sata` cdrom drives; `snapshot` redefines the domain with `define_domain run` but the drives stay (empty); `<video><model type='vga'/>` shows as "Microsoft Basic Display Adapter"; `guest-facts.ps1` already reports `cdrom.name` and `video.name` | Run-mode domains without the drives; a spiked display adapter; the self-test verdict acting on the two facts |
| `POST /analyses/{id}/finish` (409 until the monitor has started), the runner's 2 s poll of CAPE, `options.timeout` (60 to 1200), `remaining_s` in the live status computed from `options.timeout`, `LiveEndRunButton`/`use-end-run.ts` | A stored deadline, a backend that enforces it, `POST /analyses/{id}/extend` (listed in the backend spec, not built), the `+60s` button, a countdown that follows an extension |
| Guest build job, `Retry`/`Resume`/`Restart` on the build page; `make verify-wizard` (clone path, about 6 minutes, public API) | A browser flow for the wizard; no way to stop a build (the engine refuses only the guest being built, and a 14-minute install cannot be abandoned) |
| Playwright e2e specs for submit, annotations and the desktop, started by `scripts/e2e.sh` | A wizard spec |

## Decisions

1. **Failed guests do not count towards the cap; they still hold their name, address and disk.** The cap is
   `building + testing + ready`. A failed guest keeps its name and static address (the unique-address and
   unique-name checks still see it), so nothing can collide with a guest the analyst may still resume. Its disk
   (about 22 GB) stays until deleted, so the Guests page keeps showing disk used per card; no new limit.
   *Decided by the user 2026-10-17.*
2. **The resume race is fixed in the step, not by a longer sleep.** `reconfigure` first looks for the log an
   earlier apply left in the guest (it is unique per run by `TOKEN`). If one exists, the earlier run applied or
   was applying: the step waits for the guest to announce its reboot and come back (boot time moved from the one
   in the first report), then verifies and discards the log. The "before" identity (`GUID_BEFORE`,
   `BOOT_BEFORE`) is written once to the build directory and read back by a resume, so a finished apply is
   verified against the identity the copy *came with*. Only a guest with no log of an earlier apply is applied
   to. Hypothesis to confirm with the first failing test: today a resume after a completed apply fails at
   `verify_identity`.
3. **`finish-run` goes; `finish_logic.py` and `control_http.py` stay.** They are `guest-control`'s own
   modules. Their docstrings, `wrong_method_status` (which exists only for `finish-run`) and the
   `finish_run_ends_the_run` e2e function (it tests the backend's finish through `guest-control`) are renamed or
   trimmed so no word of `finish-run` is left. `GUEST_IP` in `entrypoint.sh` loses its last reader there (the
   guest scripts have their own `GUEST_IP` from the guest record and are not touched).
4. **A build can be cancelled. Confirm (scope addition).** The roadmap asks for a *short* wizard flow against the
   real backend, but handing over to the build page starts a real build, and a real build is 14 minutes with
   analyses refused for all of them. There is no stop: the engine refuses to delete the guest being built. The
   smallest honest fix is a cancel: `POST /guests/builds/{id}/cancel` (control service, backend job route,
   `[CANCEL]` on the build page behind a confirm) that stops the running step's process group (the sequencer
   already does this on shutdown) and leaves the build `failed` ("cancelled"), after which the guest can be
   deleted. It is also what an analyst needs after a typo in a 14-minute install. **If declined,** the e2e covers
   the fields, the validation errors and a 409 (cap or name taken) hand-over, and the real hand-over stays in
   `make verify-wizard`.
5. **`+60s` is enforced by the existing runner loop, not a new timer. Go, per the S1 spike
   ([findings](m7-spikes/S1-findings.md)).** The runner already polls every active analysis every 2 s and
   re-reads it from the database after a restart, so a deadline kept in the analysis record is enforced and
   survives a restart with no extra component (S1 restarted the backend mid-run: the analysis stayed `running`,
   the live socket reattached after 8 s, and a finish call 45 s later ended it like any other). What S1
   measured, and the design that follows from it:
   - **Equivalence.** A task submitted with `timeout=1200` and ended by the finish call gives the same result as
     one CAPE ends itself: the same 13 signatures, 12 techniques, 14 detections, score, artifact names, report,
     pcap and status path in all four runs; event and process counts vary as much between two CAPE-ended runs
     (4415 and 4175 events) as between a CAPE-ended and a finish-ended one.
   - **CAPE's own timeout counts from the sample's execution in the guest, not from `started_at`.** The sample
     starts 20.6 to 24.5 s after `started_at` (5 to 6 s after the first `logs/*.bson`). A deadline measured from
     `started_at` would cost the analyst about 22 s of sample time, so **the reference point is the moment the
     runner first sees the monitor started** (the same test `POST /finish` uses).
   - **The 409 window is shorter than documented:** the finish call is accepted from 16.0 to 17.5 s after
     `started_at` (first bson 15.3 to 19.6 s), not 25 s. A 60 s deadline is always past it, and a finish call
     that comes early still ends the run normally, so a retry on 409 at the next poll is all the runner needs.
   - **End latency:** the status leaves `running` 3.6 to 4.6 s after a finish call at a real deadline (11.7 to
     14.7 s when the sample has not started yet), `done` follows in about 87 s. The countdown stops at 0 and reads
     "ending"; it does not add the latency.
   - **CAPE's own 1200 s limit fires at `started_at` + 1222.6 s at the earliest** (measured once at 1223.7 s; the
     status left `running` at 1244.5 s because the guest took 16 s to shut down 45 processes).
   Design:
   - **Storage:** a nullable `deadline_at` on `analysis` (Alembic migration), set by the runner the first poll it
     sees the monitor started on an *interactive* analysis, to that moment plus `options.timeout`, but never past
     the cap below. `options` stays what the analyst asked for.
   - **Submit:** an interactive task goes to CAPE with `timeout=1200` whatever `options.timeout` says; other
     tasks are unchanged.
   - **Enforce:** when `now >= deadline_at` and the analysis is `running`, the runner calls the same finish path
     as `POST /finish` (idempotent), and retries on the next poll while that is refused.
   - **The cap:** `deadline_at <= started_at + 1200 s`, which leaves CAPE at least 22 s of margin before its own
     timer. A 1200 s request on an interactive run therefore ends at the cap, about 17 s short of 1200 s of
     monitored time; the Submit dialog's interactive hint says the run lasts "up to" the timeout.
   - **Extend:** `POST /analyses/{id}/extend` with `{seconds}`; `409` unless `running`, interactive and
     `deadline_at` already set; the deadline moves later up to the cap; the answer is the `AnalysisRead` with the
     new deadline. The live socket sends a `status` message at once so every open page updates its countdown.
   - **Read model and live status:** `deadline_at` in `AnalysisRead`; `remaining_s` is `deadline_at - now` once
     there is a deadline; before the monitor is up (or for a non-interactive run) it is `options.timeout -
     elapsed` as today.
   - **Frontend:** `+60s` beside END RUN on the LIVE tab and in the header (interactive and `running` only,
     disabled at the cap with the reason as its title); the countdown in the header and in `LiveStatusBar`
     switches to the warning colour for the last 30 s, follows an extension, and reads "ending" at 0.
6. **Only the drives ship; the display adapter stays. Decided by the S2 spike
   ([findings](m7-spikes/S2-findings.md)).** Removing the two cdrom `<disk>`s from the run-mode domain (the sata
   controller stays) was measured on clones of `lab3`: boot, agent, snapshot and revert (2 s), a normal analysis
   (capemon events, 12 signatures and detections as the baseline), the desktop and a clone of the result all work, and
   `Win32_CDROMDrive` goes from two rows to none. **No display candidate meets the criterion:** every one that boots
   and draws binds the inbox Basic Display driver (`Podstawowa karta graficzna Microsoft` on the pl-PL guests);
   `bochs` is identical to `vga`, `virtio` (`VEN_1AF4`) and `qxl` (`VEN_1B36`) name the hypervisor and are worse,
   `ati-vga` gives Code 43 and a black screen, and this QEMU 9.2.2 build gives the standard VGA no PCI vendor or device
   id property. A real GPU name would need vfio passthrough, which is out of scope. What ships:
   - **Run-mode domain without drives** (install mode keeps both: the installer and the answer ISO).
   - **A Windows pre-snapshot step that removes the ghost drives.** Windows keeps two non-present CD-ROM device nodes
     and their `Enum\SCSI\CdRom&...` keys from the install, which a sample can still read;
     `Get-PnpDevice -Class CDROM | Where-Object { -not $_.Present }` piped to `pnputil /remove-device` removes them as
     the agent user, and the removal survived a real snapshot and revert. It runs through the profile's
     `agent.pre_snapshot` hook (null today), which the spike did not exercise: P3 proves it on a real clone.
   - **The facts check.** The self-test fails when `cdrom.name` is not empty. It does *not* fail on `video.name` (it is
     localised, so a match would fail every guest or none); instead a language-independent `video.pnp` fact
     (`Win32_VideoController.PNPDeviceID`) fails only on a worse vendor (`PCI\VEN_1AF4`, `VEN_1B36`, `VEN_15AD`,
     `VEN_80EE`, `VEN_1013`) or a `ConfigManagerErrorCode` other than 0, and reports `VEN_1234&DEV_1111` and the
     Basic Display name as known tells without failing.
7. **Guests built before M7 keep their drives.** Their memory snapshot was taken with the hardware they have;
   redefining the domain without the drives under it would break the revert. A *clone* of an old guest is
   rendered from the new template and retakes its snapshot, so cloning is the way to a guest without drives.
   Recorded in the spec; `win` (the adopted M0b guest) stays as it is.

## Waves

Rule 5 applies, and **the user asked for as much work as possible on Haiku**. Everything with a written spec or
an existing pattern to copy is Haiku, including work that depends on a spike once the spike's findings turn it
into a spec. Sonnet is kept for the three things that are discovery or real judgment: the two spikes and the
resume-race fix in a bash step that runs against a real guest, plus the build cancel's process handling, all
**care** (small steps ending in a check that can fail, a notes file, the planner re-runs the checks and reads
the diff). Haiku tasks get the same review (the planner reads every diff; Haiku's report is not the evidence),
and **a Haiku task that fails its tests twice is handed to Sonnet** instead of a third attempt. No Opus. Every task is test-first (rule 2) and ends green on `make test`,
`make test-cape` and `make lint` for the files it touched. Tasks that need the real stack **exclude each other**
(restarting `cape`, one guest at a time, the 22 GB per throwaway clone), so waves 2 and 5 run one task at a time.

### Wave 1 (parallel, disjoint files, no real guest)

| ID | Task | Model | Tests first |
|---|---|---|---|
| **C1** | Failed guests off the cap (decision 1). `validation.py` counts the three live states; the message says "ready or building guests"; the backend passes the text through (find where the Guests page and the wizard word the cap: grep the frontend for the count and for `409` handling on `/guests/build` and `/clone`, and fix any hard-coded "five" or disabled `[+ NEW GUEST]` that counts failed guests); spec text in cape-integration and the GUI spec | Haiku | `test_validation.py`: five guests with one `failed` allows a build and a clone; five live ones still refuse with the new text; a failed guest's name and address still collide. Frontend: the Guests page test with a failed guest at the cap |
| **R1** | Resume race (decision 2). `reconfigure` and its `windows.sh` helpers | Sonnet, **care** | `test_clone_reconfigure_script.py` with the fake agent: (a) a log of an earlier apply present and the guest mid-reboot, so the step waits and applies nothing; (b) a log present and the guest back with a new GUID, so the step verifies against the saved "before" and passes; (c) no log, as today; (d) the "before" file survives a second run. A failing test for (b) first, to confirm the hypothesis |
| **D1** | Remove `finish-run` (decision 3): `cape/bin/finish-run`, its supervisord program and comments, `GUEST_IP` in `entrypoint.sh` and its comment, `scripts/tests/test_finish_run.sh`, the Makefile lint paths, `verify-cape.sh`'s listener check, the e2e function and the docs mentions (architecture tree, compose comment, `control_http.py` and `finish_logic.py` docstrings) | Haiku | `test_control_http.py` and `test_guest_control_finish.py` stay green with `wrong_method_status` removed; `verify-cape.sh`'s port check no longer lists the finish port, and a grep test finds no `finish-run` left outside `docs/plans` and `docs/history` |

### Wave 2: spikes (one at a time on the real stack; findings in `docs/plans/m7-spikes/`)

Start from a rebuilt `cape` image with wave 1 in it. Check `df` on the guest volume first: a spike clone is
22 GB, and the host already holds `win`, `win2` and several `lab*` guests; delete the spare ones.

| ID | Task | Model | Question and check |
|---|---|---|---|
| **S1** (done) | `+60s` | Sonnet, **care** | On a real interactive run (the benign sample on a Defender-off guest): (1) submit with `timeout=1200`, let the backend, by hand through `POST /finish`, end it at 120 s, and compare with an identical run that CAPE ends at `timeout=120`: processes, per-lane event counts, files, screenshots, PCAP, report fields, the status path; (2) the 409 window: how long after CAPE says `running` the monitor starts, and what a deadline of 60 s (the minimum) does against it; (3) how long after the finish call the status leaves `running` (measured before: 11 to 18 s) and whether the countdown should read "ends at" the deadline or the deadline plus that; (4) one run left to CAPE's own 1200 s limit, to learn how close to `started + 1200` an extension may go before CAPE itself ends the run (the margin in decision 5); (5) restart the backend mid-run: is the run still ended at the deadline. Output: findings file; decision 5 amended |
| **S2** (done) | Anti-VM tells | Sonnet, **care** | On a throwaway **clone** of a ready guest (never the only good guest): (a) render the run-mode domain without the two cdrom `<disk>` elements and the `sata` controller kept: `Win32_CDROMDrive` empty, the snapshot taken, the revert, `verify-guest`, an analysis; (b) display adapter candidates, each judged by what `Win32_VideoController` (`Name`, `AdapterCompatibility`, `PNPDeviceID`) reports to a sample and by the break list in decision 6: the current `vga`, `bochs` (`bochs-display`), `virtio` (no driver, so Basic Display again), `qxl` (its Red Hat driver is a tell of its own), the standard VGA with a real vendor's PCI IDs set through QEMU device properties (check that they exist in the patched QEMU under `cape/build`), and any candidate that needs a driver inside the guest, with where that driver would come from (the `fetch` step's pinned, hashed downloads) and whether it loads at all. Output: a table of candidate against result, one chosen or none |

### Wave 3 (parallel, disjoint files)

X1a, X2, W1a and E1 start together; X1b follows X1a and W1b follows W1a (same files).

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **X1a** | `+60s` backend, data and endpoint (decision 5, as S1 amends it) | Haiku | Migration and `deadline_at`; interactive submit with `timeout=1200`; `POST /analyses/{id}/extend` (a CRUD-shaped endpoint beside `/finish`); `AnalysisRead`, `remaining_s`, the live `status` push; regenerate the API client (`make api-sync`) | Pure: the deadline arithmetic and the cap. API: extend moves the deadline, `409` for a queued, finished or non-interactive analysis and at the cap, validation of `seconds`; `remaining_s` from the deadline |
| **X1b** | `+60s` backend, enforcement | Haiku (after X1a; the planner reads this diff line by line) | The runner's deadline check calling the finish path `POST /finish` already uses, in `_track` | Runner with fakes: a deadline in the past ends the run once the monitor is up and retries while it is not; a restart (new runner, same database) still ends it; non-interactive runs never get a deadline |
| **X2** | Anti-VM fix (decision 6, from S2's recommendation) | Haiku | (1) `domain.xml.tpl` and `render_domain.py`: an `${install_drives}` placeholder after the system disk, filled with the two cdrom disks in install mode and empty in run mode; the template's header comment corrected; (2) a Windows pre-snapshot step that removes non-present CD-ROM devices through the agent, wired as `agent.pre_snapshot` in `profile.json`; (3) `guest-facts.ps1` gains `video.pnp`; the self-test verdict fails on a non-empty `cdrom.name` and on a worse display vendor or a display `ConfigManagerErrorCode` other than 0, and reports the Basic Display name and `VEN_1234&DEV_1111` without failing (the tell list lives next to the giveaway list); no display fragment and no `hardware.display` field | `test_render_domain.py`: install mode two cdrom disks, run mode none, the drive-less XML still parses and keeps the sata controller (the existing run-mode test changes from "no cdrom source" to "no cdrom disk"). `test_windows_profile.py`: the profile names the step and the step file exists and is valid. `test_selftest_checks.py`: each tell fails the verdict, a clean fact set (empty `cdrom.name`, Basic Display, `VEN_1234`) passes. The real check is P3 |
| **W1a** | Cancel a build, engine (decision 4, **if confirmed**) | Sonnet, **care** | Sequencer/engine `cancel`: stop the step's process group (as `shutdown` already does), mark the build `failed` with the reason "cancelled", no registration change | Sequencer: cancelling a running stub step leaves no process and a `failed` build that `resume` and `delete` accept; a cancel when nothing runs is a 409 |
| **W1b** | Cancel a build, routes and button (after W1a) | Haiku | Control service route, backend route and job message (the `resume` route is the template), the build page's `[CANCEL]` with a confirm (the `Restart` button is the template), regenerated client | Route and error-mapping tests copied in shape from `resume`; vitest for the button's phases |
| **E1** | Wizard browser e2e | Haiku | `frontend/tests/e2e/wizard-flow.spec.ts` and a step in `scripts/e2e.sh` (opt-out like the others, the check counted in the total): the ISO listed with edition, build and language; the name, username and computer-name fields with their rules (a giveaway such as `sandbox-1` refused with the form's message, a name already taken refused); `[RANDOM]`; the review step; the submit hands over to the build page, which shows the first step running and a log line; then (with W1) `[CANCEL]`, and the guest is deleted so the stack is as it was | The spec is the test. A vitest for any form helper it needs; if the wizard needs a `data-test` hook, the unit test for the component comes first |

### Wave 4 (frontend, after X1 and the regenerated client)

| ID | Task | Model | Deliverables | Tests first |
|---|---|---|---|---|
| **F1** | `+60s` button and countdown | Haiku | A `use-extend-run` composable (the `use-end-run` shape: confirm-free, one request in flight, the cap as a reason), `LiveExtendButton` placed beside `LiveEndRunButton` and in `AnalysisHeader`, the countdown in `LiveStatusBar` and the header following `deadline_at` with the last-30-seconds warning (shared helper, not a second formatter) | vitest: the composable (pending, 409 at the cap, success), the button's visibility rule (interactive and running only) and title, the status bar's countdown after an extension and its warning state |
| **F2** | Screenshots and the review Artifact (rule 4) | Haiku | The harness fixtures for each state; **one Artifact for the LIVE tab and header** (default with 3:20 left, warning in the last 30 s, extending, at the cap and disabled, a non-interactive run with no button, a narrow window, the 409 error toast) and **one for the build page** if W1 landed (`[CANCEL]` default, confirm, cancelling, cancelled). The planner checks every screenshot for overflow and collisions before publishing | Not applicable; the screenshots are the check |

Wait for and address comments on both Artifacts before wave 5 (rule 4, steps 5 and 6).

### Wave 5: proof and docs (one at a time on the real stack)

| ID | Task | Model | Check |
|---|---|---|---|
| **P1** | The stop-and-resume drill again | Sonnet, **care** | On a real clone: start it, stop `guest-control` (or restart the backend) while `reconfigure` is applying, resume at once, then after it settled; both end `ready` with the self-test passed. This is the drill that failed in M6 |
| **P2** | Real `+60s` run | Haiku, driven by a script; the planner re-runs it | An interactive run through the public API: `extend` twice, the run ends at the moved deadline, the report has the same sections as a normal run, and a backend restart in the middle still ends it |
| **P3** | The suites | planner | `make e2e` (with the wizard flow), `make verify-guest` and `make verify-wizard` on a guest cloned after X2 (the `pre_snapshot` hook, which S2 did not run, must remove the ghost CD-ROM nodes: no `CDROM` PnP device and no `Enum\SCSI\CdRom` key after the clone's snapshot and revert), and the facts check holds; `make verify-guest` is hard-wired to `win`, so the same checks are run on the clone. S2 also left one decision-7 premise unmeasured (an old guest's memory snapshot breaking when drives are removed from under it): nothing tries it, the rule stays |
| **D2** | Close the questions in the docs | Haiku | `tartarus-v1.md` open questions 2, 3 and 10 say what was built; specs: `backend.md` (`/extend` row, the cancel route, the deadline field), `cape-integration.md` ("Extend" row, the cap, drives and display, **Sysmon is collected at the end of the run**), `data-model.md` (Sysmon is a final-phase source, no live forwarder), `gui.md` (the button and countdown), `guest-profiles.md` (the `hardware` block's new field), `overview.md` (M7 row), `finish-line.md` (status, and the roadmap's M7 list ticked), the "CAPE says `running` about 25 s earlier" statements in `backend/app/api/analyses.py` (docstring) and `backend.md` (S1 measured 13 to 14 s), the README's `make` list if it changed, and this plan's Status filled in as M6's was |

## Risks

| Risk | Handling |
|---|---|
| CAPE ends an interactive run at 1200 s before the analyst's last extension would | The cap is `started_at + 1200 s`, 22 s before CAPE's earliest measured end (S1, one 1200 s run); the button says so when disabled |
| A task ended through the finish call yields less than one CAPE ended itself | **Measured by S1: it does not** (decision 5); the planner re-checks it in P2 |
| The display adapter breaks capemon or the desktop | S2 runs on a throwaway clone; the drives ship alone (decision 6) |
| Removing the drives disturbs the snapshot or the agent | The same S2 break list; decision 7 keeps old guests as they are |
| Two spikes want the one stack | Wave 2 is sequential, S1 then S2; neither runs while a build or a clone does |
| The resume fix passes against the fake agent but not a real guest | P1 is the real drill, and the failing-first test of R1 (b) is derived from what the M6 run printed |
| Agents report results optimistically (found again in M6) | The planner re-runs every wave's checks and reads each diff before committing, and wave 5 runs through the public API |

## Not in M7

Sysmon, ETW, Volatility3 and Defender's verdict (M8); PCAP import, search and parallel analyses (M9); the
Windows 10 and English ISO proofs, and the manual Defender pause (M10); the logo, CI, security review and docs
cleanup (M11). Extending a non-interactive run: CAPE's own timeout stays.
