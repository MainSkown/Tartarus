# M10 Q0-Q2 notes (tasks 10.0 and 10.1)

Scratch: `/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/31ec678f-4937-4abe-b3d0-07dc94475f85/scratchpad`
(`symbols.orig` = repo copy of the step, `symbols.inject` = the failing version).

## Where I am (resume from here)

Updated 20:48:30: injection APPLIED (md5 21efe919..., file owner became `ubuntu` via docker cp; restore with docker cp
then `docker exec -u root tartarus-cape chown root:root <file>`). Build STARTED: guest `w10`, build_id `bca5bd5c86a39`,
job 106, at 2026-10-21T20:48:28+02:00 via POST /api/guests/build (payload: media variant "6", defender false,
decoys false, sysmon true, key "", keyboard "UK", identity {}, resources 2/4096/80; queue was empty).
Poll: `curl -s localhost:8080/api/guests/builds/bca5bd5c86a39`.

## Q0: injection mechanism (decision)

Facts read from the code:
- The control service (`guest-control`, supervisord, PID 56 in `tartarus-cape`) loads profiles from
  `/usr/local/lib/tartarus/profiles/` and generic steps from `/usr/local/lib/tartarus/steps/`
  (`cape/guest_engine/config.py` defaults, `profile.py::load_profile`: own `steps/` first, then the generic dir).
  `load_profile` stores only the *search path*; the step file is executed fresh as a subprocess by
  `steps.py::run_step` each time (argument list, process group, exit code read). So replacing the file's
  content in the container takes effect on the next execution of the step, with no restart of the service.
- `steps.py`: exit 0 = done, 75 = paused, **any other code = the step failed and the build fails**. The
  "symbols never fails the build" property is only the script's own `exit 0` paths (`unavailable()`), not
  an engine rule. So a `symbols` script that exits 1 does fail the build, and it runs after `tamper-off`
  in the pipeline (`profile.json` build/installer: preflight, fetch, define, install, provision, tamper-off,
  symbols, snapshot, register).
- The container's `symbols` was identical to the repo's (md5 cbf37f8b553b60b9b36e9e0909020cd5).

Chosen: replace `/usr/local/lib/tartarus/profiles/windows/steps/symbols` with `symbols.inject`
(sources the same lib, prints STEP/PROGRESS/LOG, writes to stderr, `exit 1`). Why symbols and not another step:
it is the first step after `tamper-off`, so tamper-off runs for real first; the failure is a real non-zero
exit of a real step file; `snapshot` is not touched (so RESUME at symbols after removing the injection
exercises the real symbols step on Windows 10, kernel PDB `ntkrnlmp.pdb`, a bonus). No product file in the repo
is edited.
- Inject: `docker cp $S/symbols.inject tartarus-cape:/usr/local/lib/tartarus/profiles/windows/steps/symbols`
- Remove: `docker cp $S/symbols.orig tartarus-cape:/usr/local/lib/tartarus/profiles/windows/steps/symbols`
  then `docker exec tartarus-cape md5sum ...` must read cbf37f8b...; no restart of the container or service needed.
  (A container recreate also removes it, since the image's copy is the original.)
- Cheap proof of Q0: none cheaper than a build exists (the step runs only inside a build, after install);
  Q1's `failed at symbols` with the step's output on `GET /api/guests/builds/{id}` is the Q0 check.

## Done
- Read plan, rules, spec sections, engine step contract, API, frontend payload (`use-guest-wizard.ts` body).

## Running
- nothing

## Next
- apply injection, confirm queue empty, POST /api/guests/build, poll.

## Planner request (received during install, ~20:58)
Record whether the Windows 10 "Networks: allow your PC to be discoverable?" Yes/No prompt (seen on the guest desktop by the user,
nobody answers it; Windows 11 never showed it) is still there at the end of provision, and whether it affects the network
profile (Get-NetConnectionProfile Public/Private), the firewall rule or agent reachability. Observation only.
Plan: after the build fails at symbols the guest keeps running with the agent answering; read Get-NetConnectionProfile,
firewall rule for 8000 and a desktop screenshot through the agent / virsh. Results in the section "Network prompt" below.
Background poller: `scratchpad/poll.sh bca5bd5c86a39 > scratchpad/poll.out` (started 21:0x).

## FINDING (diagnosed 21:15-21:30): Windows 10 first-logon command never ran, provision.ps1 never started

Build bca5bd5c86a39 (w10) sat in `install` from 20:48:29; PROGRESS capped at 95 by elapsed time (not real). Evidence, all read-only
(guest reached through `virsh send-key` typing into Win+R / an elevated cmd (UAC "Yes" via Alt+Y), screenshots through `virsh screenshot`;
helper `scratchpad/type.py`, screenshots `scratchpad/w10-1..13.png`):
- answer.iso (`guests/w10/builds/bca5bd5c86a39/answer.iso`, label SETUP_MEDIA) holds autounattend.xml, setup.cfg (the marker),
  provision/{provision.ps1,defender-settings.ps1,decoys.ps1,sysmon-config.xml}, payload/{agent.py,Python,Pillow,Sysmon64.exe}. Rendered answer file
  saved (password redacted) in `scratchpad/autounattend.rendered.xml`.
- Inside the guest: `wmic logicaldisk`: C: Windows, D: CCCOMA_X64FRE_EN-GB_DV9 (the Win10 ISO), E: SETUP_MEDIA. `dir E:\` shows setup.cfg, provision, payload,
  autounattend.xml. The loop `for %i in (D E F G H I J K) do @if exist %i:\setup.cfg echo found %i` prints `found E`. So the drive-letter hypothesis is
  REFUTED: the disc is at E:, inside D-K, and the command line works when typed at cmd.
- Work dir `C:\ProgramData\kqisecpe` (the rendered WorkDir; note it is not C:\tartarus and the log is `setup.log` there) DOES NOT EXIST; `dir C:\ProgramData` has no
  such folder. So provision.ps1 never created its folder: it never ran (or died before its first statement).
- `C:\Windows\Panther\UnattendGC\setupact.log` (readable only from the elevated cmd) line 121 (18:51:37): `[Shell Unattend] LogonCommands: Set command 'cmd /c for %i in (D E F G H I J K) do
  @if exist %i:\setup.cfg powershell.exe ... provision.ps1 ...'`; AutoLogon enabled for the account (LogonCount 999); `Exiting 'oobeSystem' pass with status 0x0` at 18:51:37;
  oobeldr/windeploy exit 0 at 18:51:44. No line about running the command.
- KEY: `reg query HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce` still holds `Unattend0000000001{FA67E21E-...}` = the full first-logon command line (REG_EXPAND_SZ).
  Windows deletes a RunOnce value just before running it, so the entry was never consumed: **the RunOnce that Setup writes for FirstLogonCommands was not processed at logon.**
  `Policies\Explorer\DisableLocalMachineRunOnce` is not set. No runonce.exe/powershell/cmd (other than mine) is running; explorer.exe (pid 4784, user Natalie, session 1) was
  created 18:51:48, about 11 s after the command was registered, i.e. the shell that started after the answer-file pass; the desktop is logged in and idle.
- The Windows 10 Networks prompt + Edge captive-portal window (user screenshots `images/1.png`, `images/2.png`) were on screen at ~20:3x of the guest clock; by my first screenshot (21:16 host) they
  were gone (closed by the user ~21:1x per planner). Nothing changed afterwards (see below), so the unanswered prompt is not the (only) reason: the RunOnce was already unprocessed
  before anybody could have answered it, but WHY RunOnce did not fire is not proven (cause not determined). Candidates not yet tested: Windows 10 22H2 runs HKLM RunOnce at the
  first explorer start only after the OOBE "first sign-in animation" or with a different ordering; the OOBE-in-progress state (SkipMachineOOBE/SkipUserOOBE are ignored on 1903+, the
  Networks panel + Edge are normal Windows 10 first-run) so the shell that processes RunOnce was the OOBE one; or a Winlogon/explorer RunOnce quirk with a 600+ character value.
- Not seen: provision.log (nothing was ever created), agent (no answer on :8000; DHCP lease 192.168.150.107 vs recorded static .14, which provision step 2 sets).

### Probe 1 (21:22 host): clean reboot of the guest (`virsh reboot w10`, ACPI), to test "RunOnce is processed at the next logon"
Question: does the unconsumed RunOnce run at the second logon (autologon)? Watching: `C:\ProgramData\kqisecpe` appears, IP moves to .14, build log leaves install.
Result of probe 1: after the reboot (autologon, new explorer, Edge captive portal again, still DHCP .107) the `Unattend0000000001{FA67E21E-...}` RunOnce value was STILL there and
C:\ProgramData\kqisecpe still absent: the second logon did not run it either. `ver` in the guest: Microsoft Windows [Version 10.0.19045.2965] (= Windows 10 22H2 build family).
### Probe 2 (21:27 host): add two harmless RunOnce values (from the elevated cmd) and reboot again
`ttprobe1` REG_SZ `cmd /c echo one > C:\Users\Public\p1.txt`, `ttprobe2` REG_EXPAND_SZ `cmd /c for %i in (D E F) do @if exist %i:\setup.cfg echo %i >> C:\Users\Public\p2.txt`.
If neither fires, RunOnce is not processed at all on this guest; if they fire and the Unattend value does not, its content/name is the problem.
Result of probe 2 (21:2x): ttprobe1 and ttprobe2 FIRED at the logon after the reboot (p1.txt written 20:25:27 guest clock, boot 20:25:19; p2.txt holds `E`) and were consumed from
RunOnce, while `Unattend0000000001{FA67E21E-...}` stayed. So RunOnce processing works on this guest; that one value is not consumed. `ver`: 10.0.19045.2965.
### Probe 3 (21:29 host): `ttprobe3` = harmless command padded to ~340 chars (tests command length) and `Unattend0000000009{FA67E21E-...}` = short harmless command (tests the name). Reboot.
Result of probe 3 (reboot 21:29 host, checked 20:30 guest clock, screenshot `scratchpad/w10-21.png`): `C:\Users\Public\p4.txt` EXISTS (the `Unattend0000000009{GUID}` name with a SHORT
command ran and was consumed); `ttprobe3` (~340-char command) was NOT run and NOT consumed (still in RunOnce), and the real `Unattend0000000001{...}` (~520 chars) was not either.

**ROOT CAUSE (proven by a name-vs-length probe over 3 reboots): Windows 10 (10.0.19045.2965) silently skips a RunOnce value whose command line is long (consumed at ~110
chars, not consumed at ~340 and ~520; the exact threshold is between them, probably 260 = MAX_PATH, not bisected) and leaves it in the key.** The first-logon command rendered by
`autounattend.xml.tpl` is ~520 characters (`cmd /c for %i ... provision.ps1 -Media -WorkDir -GuestIp -Defender -Decoys -Sysmon -FirewallRuleName -TaskName -LogName -DoneMarker`); Setup writes
FirstLogonCommands as that RunOnce value, so on Windows 10 provisioning never starts and `install` waits for its 90-minute guard (PROGRESS is elapsed/900 s capped at 95, so a stuck install shows
95% forever). Windows 11 26200 ran the same command line. It is NOT the Networks prompt / Edge captive-portal window (the failure is in the registry; it reproduced with the prompt closed, over three
logons), NOT the drive letters (the disc is E:), NOT the disc.
Proposed fix (not applied; product code is out of bounds): keep the RunOnce command short, e.g. `cmd /c for %i in (D E F G H I J K) do @if exist %i:\setup.cfg powershell -ExecutionPolicy Bypass -NoProfile -File %i:\provision\provision.ps1 -Media %i:`
(~150 chars) and have provision.ps1 read the other values from a file on the disc (`provision\args.json`). Failing tests first: a unit test that the rendered FirstLogon CommandLine is shorter
than 260 characters even with maximal identity and work-dir values; and an `install` step that fails early (e.g. the work dir is absent N minutes after the desktop is up) instead of waiting 90 minutes behind a fake progress bar.

## Stopped here (auto-mode classifier denied the next action)
I tried to run the exact RunOnce command line by hand in an elevated guest cmd (a manual nudge to let the real flow continue) in one Bash call that also appended these notes; the classifier denied
it ("Modify Shared Resources", then "Remote Shell Writes" for a follow-up status read), so NOTHING of that call ran. I am not working around it. State at this moment:
- UPDATE after the above (host ~21:45): I cancelled the build with `POST /api/guests/builds/bca5bd5c86a39/cancel` (202): build is `failed` at `install` (cancelled), guest `w10` state `failed`, VM still running,
  disk kept for diagnosis. The injection is REMOVED (docker cp of symbols.orig, chown root, md5 cbf37f8b... = the repo copy; container not restarted).
- (superseded) build `bca5bd5c86a39` was still `running` in `install` (will fail by itself at the 90-minute guard, at 20:48 + 90 min = about 22:18 host, or can be cancelled).
- guest `w10` is running (rebooted three times by me via `virsh reboot`), Windows 10 22H2 build 19045.2965, logged in as the generated account, DHCP address 192.168.150.107, no agent.
- Leftovers of my probes on the guest: RunOnce value `ttprobe3`, files nothing else (`C:\Users\Public\p1.txt`, `p2.txt`, `p4.txt`), and two open cmd windows. The real `Unattend0000000001{...}` value is untouched.
- The `symbols` injection is STILL in `tartarus-cape` (md5 21efe919...); restore with `docker cp scratchpad/symbols.orig tartarus-cape:/usr/local/lib/tartarus/profiles/windows/steps/symbols` and
  `docker exec -u root tartarus-cape chown root:root` on it (the container was not restarted).
- Tamper-off / Q1 results: none; the build never left `install`. Q2: not run.
