# Plan: M10, guest proofs

The four guest proofs of the [finish line](finish-line.md#m10-guest-proofs), run for real: a Windows 10 22H2 build with its
clone and self-test, an English-language build, the manual Defender pause, and a failing install step with RESUME and
RESTART. M10 adds no feature; what it finds becomes a fix (test-first, rule 2), a spec correction, or a `verify-*` check.

## Status

**Started 2026-10-21. Nothing built yet; the media scan is done.** The user supplied
`data/iso/Win10_22H2_EnglishInternational_x64v1.iso` (one ISO for both ISO proofs), next to the verified
`Win11_25H2_Polish_x64_v2.iso`.

### What the scan said (through `GET /api/guests/media`, the wizard's own inspector)

| | Win10 ISO | Win11 ISO (verified) |
|---|---|---|
| Product | Windows 10, `10.0.19041` (22H2 shares the 19041 build family with 20H1 to 21H2; the file name is the only 22H2 claim) | Windows 11, `10.0.26200` |
| Language | **en-GB** (English International), not en-US | pl-PL |
| Arch | amd64 | amd64 |
| Editions | 11, Pro is index 6 | 10, Pro is index 5 |

Both of the user's checks pass at the scan level: it is Windows 10 and it is English. Two caveats the proofs must
respect: English here is **en-GB**, which has the same UI strings as en-US for everything the profile reads, so this
proves "English names" and not a third language; and 19041 is not proof of 22H2, so the guest's own
`CurrentBuild`/`DisplayVersion` is recorded after the build.

### Where a Windows 10 guest may differ (read from the profile, none of it run)

- **Windows Security's toggle fallback.** `security-ui.ps1` finds Tamper Protection by name (English is listed, never
  seen) and otherwise as the **fifth** `settingToggle`. Windows 10's *Virus & threat protection settings* page has fewer
  toggles than Windows 11's, so the fallback index may point at nothing or at the wrong switch. The name path is the one
  that matters on Windows 10; the fallback is exactly what the manual-pause proof exercises.
- **Names that say Windows 11:** `profile.json` has `display_name: "Windows 11"` and the CAPE tag `win11`, and
  `adoption.media` and `build-guest.sh` default to the Win11 ISO. A Windows 10 guest would be registered with a `win11` tag.
- **Setup keys written for Windows 11:** the `LabConfig` bypass keys and `BypassNRO` in `autounattend.xml.tpl` are
  harmless on Windows 10, but the first-logon and OOBE behaviour of build 19041 (no "Hide online account" parity) was
  never observed.
- **Installed-software assumptions:** CAPE's analyzer, Python 3.11.9 32-bit, Sysmon and the Defender event-log export
  were proven on 26200 only.

### Findings so far (from watching a real build)

- **F1, nothing on the build page tells the user what is running in the background** (seen 2026-10-21 on the `w10`
  build, 6 min in, user report). The desktop is live and the cursor moves, but the screen does not change (Edge on
  the INetSim page, an unanswered "Networks" prompt), and the build log's PROGRESS lines are bare numbers
  (`PROGRESS 22`, `PROGRESS 23`, ...) that mean nothing to a reader. The user concluded the install was stuck. In truth
  Windows was installed and the guest's first-logon `provision.ps1` was running (Windows Update off, firewall, Python,
  the agent, Sysmon...); the step stays `RUNNING` until provisioning writes its done marker. The percentage itself is not progress: the
  `install` step computes it from elapsed time over a typical install time (`steps/install`, `WAIT_PROGRESS_FROM/TO`),
  so it rises whatever the guest is doing. The page must say what is
  being done now, in words: see task 10.9.

- **F2, a Windows 10 build never starts provisioning** (found by Q1, 2026-10-21; evidence in
  [Q0-Q2-notes.md](m10-notes/Q0-Q2-notes.md)). Setup writes the answer file's `FirstLogonCommand` into the
  `RunOnce` key, and **Windows 10 (19045.2965) silently skips a RunOnce command that is long and leaves it in the
  key**; Windows 11 ran the same command. Probes over three reboots: a ~110-character command fired and was consumed,
  a ~340-character one did not, the real one (388 characters when rendered) did not; RunOnce itself works on the
  guest. The threshold is not bisected, probably 260 (MAX_PATH). `provision.ps1` never started, so the guest sat on
  DHCP with no agent while `install` waited behind the elapsed-time percentage (see F1). The Networks prompt and the
  Edge captive-portal window are Windows 10 first-network behaviour and are not the cause. Fix: task 10.5a.

- **F3, Tamper Protection's switch is not found on Windows 10, so an ordinary build pauses** (found by the second
  `w10` build, 2026-10-21, after F2's fix let it reach `tamper-off`). The window is found (English title "Windows
  Security"), but `Find-TamperToggle` collects switches by `AutomationId = settingToggle`, which Windows 11 sets on all
  five and **Windows 10 leaves empty on its four** (`Real-time protection`, `Cloud-delivered protection`, `Automatic
  sample submission`, `Tamper Protection`: ControlType Button, class `ToggleSwitch`). The English name "Tamper
  Protection" is what the script already lists, so the by-name path was never reached. The old fallback, the fifth
  switch, would also be wrong there (it is the fourth); on both versions it is the **last**. The step ended with
  `toggle=not-found`, exit 75, the instructions and the desktop on the page: **the manual-pause path ran for real on
  Windows 10**, which is half of Q5. Windows 10 also shows `IsTamperProtected = False` before the step touches
  anything. Fix: task 10.5c. UI dump kept as a test fixture.

## Spikes and proofs (all on the real stack; notes file each under `m10-notes/`)

The engine runs one build or clone at a time and a build takes about 16 minutes, so the order is chosen to get the
most proofs out of the fewest builds.

| ID | Proof | How | Check that can fail |
|---|---|---|---|
| **Q0** | **Failure injection without shipping a hook.** How to make one step fail, and the Defender step exit 10, on a real build | The profile is baked into the `cape` image (`COPY guest/profiles/`), so a modified step or `security-ui.ps1` can be put into the running container with `docker cp` (lost on recreate, never committed). Decide there, not in product code | A deliberately broken `symbols` step fails the build with the step's output on the page |
| **Q1** | **Windows 10 Pro en-GB build, Defender off** (`w10`), with a `symbols` failure injected | The build goes through `install`, `provision`, `tamper-off` in **English on Windows 10**, then fails at `symbols` | `tamper-off` verifies `IsTamperProtected = False` and the EICAR survives; the build is `failed` at `symbols`, not earlier |
| **Q2** | **RESUME from the real build page** | Remove the injection, press RESUME on `w10` | Resumes at `symbols`, not at `install`; finishes `ready`; the self-test passes |
| **Q3** | **Clone `w10` to Defender on** (`defender-on` step, English) and its self-test | `POST /api/guests/w10/clone` with Defender on | `defender-on` finds the toggle by an English name; the test file is removed; self-test passes |
| **Q4** | **RESTART** | A second Windows 10 build (`w10b`, Defender on) with `provision` failing after `install`, then RESTART from the build page | Restart re-runs from `preflight` (a domain left by the first attempt is removed) and ends `ready` |
| **Q5** | **Manual Defender pause** | A throwaway clone of `w10` with Defender off, `security-ui.ps1` broken so the toggle is not found: the build pauses with instructions, the desktop is on the page, the analyst switches the toggle by hand, CONTINUE | Build is `paused` (exit 75), the instructions show, CONTINUE re-runs the step and `IsTamperProtected` reads `False`, the EICAR proof passes |
| **Q6** | **A run on `w10`** | Submit a benign sample to the Windows 10 guest, as `make e2e` does | Events from capemon and Sysmon, a Defender section, screenshots; no Windows 11 assumption in the normaliser |

Q1 to Q3 are the Windows 10 proof; Q1 and Q3 are also the English proof (the Polish names were all that was ever seen).
Q5 is the only place the fallback index matters, and it should be run **on Windows 10** because the page layout differs
there (a Polish Windows 11 run would not say anything new).

Disk: 380 GB free, each guest is an 80 GB thin disk plus a 4 GiB memory snapshot. Per the cleanup rule, `w10b` and the
Q5 clone are deleted when their proof is recorded; `w10` stays as the Windows 10 guest.

## Tasks for agents (rule 5)

**S+** = Sonnet with a notes file (done/running/next) and a check the planner re-runs. Real-guest steps are long and
single-file (one build at a time), so they run one after another, not in parallel; the planner reads every diff.

| ID | Task | Tier | Depends on | Check that can fail |
|---|---|---|---|---|
| 10.0 | Q0: injection mechanism, written into the notes | S+ | none | a broken step fails a throwaway build |
| 10.1 | Q1 and Q2: the `w10` build, failure, RESUME | S+ | 10.0 | see table |
| 10.2 | Q3: the English `defender-on` clone | S+ | 10.1 | see table |
| 10.3 | Q4 and Q5: RESTART and the manual pause | S+ | 10.2 | see table |
| 10.4 | Q6: an analysis on the Windows 10 guest | S | 10.1 | see table |
| 10.5 | Fixes from what 10.1 to 10.4 found, one commit each, each with a failing test first | S | each | the regression test |
| 10.5a | **F2 fix.** The first-logon command stays short (well under 260 characters with the longest identity, work-dir and rule-name values) and `provision.ps1` reads the rest of its parameters from a file on the answer disc, written by the same code that renders the answer file (one source of truth, rule 3) | S | none | tests first: the rendered `CommandLine` is under the limit for worst-case values, and the disc's parameter file round-trips every value `provision.ps1` takes; then a real Windows 10 build gets past `install` |
| 10.5b | **F2 follow-up.** `install` fails early with a readable message when provisioning has not started a few minutes after the desktop is up (the work dir or the guest's agent is absent), instead of waiting 90 minutes. Together with F1 (10.9) so a stuck step never looks like a working one | S | 10.5a | a fake-agent test: no work dir after the grace period fails with that message; a slow but live provision does not |
| 10.5c | **F3 fix.** The switches are found by toggle behaviour, not by `AutomationId`; the pick is a pure function (by name, else the last switch), tested against the Windows 10 dump and a Windows 11 shape with real PowerShell when `pwsh` exists | S | none | tests first (fail on the old `Find-TamperToggle`); then the paused `w10` build CONTINUEs and passes `tamper-off` on Windows 10 |
| 10.6 | Profile neutrality: `display_name`, the `win11` tag and the Win11-only defaults come from the media, not the profile | S | 10.1 | a unit test that a 19041 image registers a tag that says Windows 10 |
| 10.7 | `verify-*` for what can be automated (the failure and RESUME path through the public API, the clone's Defender flip), `make` target | S | 10.3 | the check fails when the injection is left in |
| 10.8 | Spec: supported-guests table, Defender section ("not exercised for real" removed), per-ISO differences, README note | H | 10.5 | `grep` for "not exercised" and "only Polish" finds nothing stale |
| 10.9 | **F1:** the build page names what is running now and what it is doing, in words. A phase line under the progress bar, e.g. for `install`: "Windows is installed; the guest is running its first-logon script (now: installing Python)"; the percentage shown as an estimate (or replaced by the real sub-step count once the guest's own log can be read live), and each `PROGRESS n` in the log shown with a label, never a bare number; a visible "last activity N s ago" from the newest log line, so a silent minute reads as quiet and not as hung; and a note that the desktop is live but idle by design and nothing is needed unless the build pauses. The desktop stays interactive. Sub-step names come from the steps' own `LOG`/`PROGRESS` output (`provision.ps1` has to emit them through the guest log the build already reads back), not a list hard-coded in the frontend (rule 3) | S | none | component test for the phase line, the labelled progress and the activity age; the screenshot loop (rule 4): install running, provisioning with a quiet log, paused, failed |

10.4 and 10.6 are independent of 10.2 and 10.3, but they need the `w10` guest and the engine is busy during a build,
so they follow Q1/Q2 and share its window.

## What the user does

- Watches the build page for Q1 to Q5 only if they want to; the pause in Q5 needs the desktop on the page and one
  manual toggle (or the planner drives it through the desktop WebSocket).
- Nothing blocks on the user: both ISOs are in place.
- No new screen, so no screenshot Artifact round (rule 4) unless a fix changes the build page.

## Risks

| Risk | Handling |
|---|---|
| Windows 10's Security page has no toggle the fallback index finds, so the pause path fires in an ordinary build | That is a finding, not a failure of the proof: fix `Find-TamperToggle` (test-first) and record it |
| An agent reports a proof that never ran (an injection left in, or a passing check with the code under test removed) | The planner re-runs each check itself, and `verify-*` fails when the injection is present |
| The injected failure leaves the engine in a state a real failure would not | The injection is a real non-zero exit from a real step, not a patched engine |
| 22H2 vs another 19041 build | The guest's own `DisplayVersion` is recorded in the notes |
| Disk | Delete throwaway guests and the memory dumps when each proof is recorded |
