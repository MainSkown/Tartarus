# P1 and P3 results: the stop-and-resume drills and the drive-less guest, on the real stack

Run 2026-10-17 on the live stack (API `http://127.0.0.1:8080/api`) with the images as they were: R1's reconfigure
fix, X2's drive-less domain, the `remove-ghost-drives` pre-snapshot step and the new facts check were all in the
running `cape` image (the repo's `reconfigure`, `windows.sh`, `profile.json`, `remove-ghost-drives` and
`domain.xml.tpl` were diffed against the copies in the container before the first clone: identical). No product code, compose or
docker file was changed and no image rebuilt. Source of both clones: `lab3` (Defender off, only ever the source of
a clone through the public API). Times are the host clock (UTC+2); guest log lines carry UTC (16:17 UTC is 18:17
host time). Scratch scripts and raw outputs are in the session scratchpad
`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/45a210d4-5788-495f-b69b-8cc2b979bccb/scratchpad/p1/`
(not in the repo).

## Failures and anomalies first

**No drill and no check failed.** Both resumes ended in `ready` with the self-test passed. Things that are not
clean, plainly:

1. **The M6 failure ("did not start its reboot within 90 s") did not reproduce, but the narrowest race was only
   brushed.** In drill A the resume (3.1 s after the stop) found the earlier apply's log at 18:17:55, the same
   second the guest wrote its `rebooting` line (the apply was still in "clear the event logs" from 16:17:36 to
   16:17:55). I cannot resolve it more finely than that second. What the run proves: a resume issued 3 s after the
   kill, while the guest was applying (static IP, rename, new MachineGuid and the event-log clear were all
   happening in the guest after the control service was already stopped; the guest's own log shows its apply
   starting 2 s *after* the stop) did not apply again and verified the identity after the reboot. It did **not**
   hit the case "log exists, no `rebooting` line yet, guest still up" for the full 90 s wait; that case is only covered
   by R1's bash tests against the fake agent.
2. **Drill A's `ip=` and hostnames.** The copy first answers on `lab3`'s own address `192.168.150.13` (it is the
   source's static one), takes `.14` after the apply. Normal, as the script's header says.
3. **The lab3 baseline run had more network noise than the clones**: analysis 266 on `lab3` has 563 events (network
   lane 76, 70 flows, 4 DNS, 2 HTTP) against 517 and 515 on `m7-a` (network lane 29 and 25). Every other lane
   matches within one or two events (api 467 / 468 / 470, process 15, registry 3, file 2), the 12 signatures,
   13 detections, 10 techniques and artifact names are identical in all three. S2's baseline spread was 510 to 518, so 563 is
   outside it; the extra events are network flows only. Not explained (a guest with Defender off that is not a
   fresh clone talking to something extra is my guess, not measured). It does not point at the drives.
4. **Ordinary analyses were submitted with the spike's `submit.py`** (route `inetsim`, package `exe`, timeout 60), not
   the UI.
5. **A CAPE task outside Tartarus.** The `verify-guest` equivalent submits straight to CAPE's apiv2 (as the script
   does), so CAPE task 256 exists in CAPE's database with no Tartarus analysis. Deleted afterwards through
   `apiv2/tasks/delete/256/`.
6. **Deleting a guest restarts `cape`** (supervisord, by design): uptime reset after each delete, and the check-12
   equivalent recreated the container once on purpose. No guest was touched by either.
7. `win2` (a libvirt domain the API does not know) was left alone, as asked.

## Method

- Clone through the public API with the body shape of `scripts/verify-wizard.py`: `POST /guests/lab3/clone
  {"name": "m7-a", "options": {"defender": false}}`. `verify-wizard.py` flips Defender against the source; I kept
  `lab3`'s (off) so the clones are comparable to lab3 and to S2's baseline. Both finished with badge `DEFENDER OFF`.
- A watcher script (`p1/drill.py`) polled `GET /guests/builds/{id}?tail=200` every 0.5 s, and at the trigger ran
  `docker compose exec -T cape supervisorctl stop guest-control`, then `start`, waited for the build to read
  `failed`, and `POST /guests/builds/{id}/resume`. It printed every new build-log line with the host time.
  Drill A trigger: `PROGRESS 55` inside the `reconfigure` step after `STEP Giving the copy its own identity`
  (the identity script started in the guest). Drill B trigger: `STEP Waiting for the reboot`, then 120 s with the
  service stopped before starting it again.
- After each clone: build log from the job (`GET /jobs/{id}`), `virsh dumpxml`, a revert of `tartarus-clean` and a
  probe through `guest_agent.py` (the helper the steps use) with `p1/p1-probe.ps1` and the repo's real
  `guest-facts.ps1`, and the control service's own `POST /guests/{name}/selftest/checks` (the exact facts the
  verdict judges). Then, for `m7-a` only, the analyses and the verify-guest checks. Everything deleted afterwards.

## Drill A (P1): stop `guest-control` while `reconfigure` applies, resume at once

Timeline (host clock):

| Time | Event |
|---|---|
| 18:16:34 | `POST /guests/lab3/clone` -> 202, build `be408a7d10162`, job 52. `preflight`, `copy` (overlay, seconds) and `define` pass |
| 18:17:32 | `reconfigure`: before-identity read (`machine_guid=2da5f343-...`), `STEP Giving the copy its own identity`, `PROGRESS 55`. **Trigger.** `supervisorctl stop guest-control` (0.5 s) |
| 18:17:34 | the guest's own log: `reconfiguring as DESKTOP-M2L2OZT at 192.168.150.14` (the agent had accepted the async script; it keeps running with the service down) |
| 18:17:35 | `supervisorctl start guest-control` (2.0 s). Build reads `failed`, message `the control service was stopped while this step was running; resume it`. `POST .../resume` -> 202, job 53 (3.1 s after the stop) |
| 18:17:37 | resumed `reconfigure` starts; "Finding the copy on the network" takes 18 s (the guest is changing its address) |
| 18:17:55 | `Looking for an earlier attempt`: found; `an earlier attempt already applied; waiting for its reboot, not applying again`. The guest wrote `rebooting` this second |
| 18:18:31 | agent reachable again after the reboot; the guest's log is retrieved and printed; `PROGRESS 70`, `Waiting for the reboot` |
| 18:18:41 | `verified: hostname=DESKTOP-M2L2OZT ip=192.168.150.14 machine_guid=bd007d9a-...` (against the saved before `2da5f343-...`) |
| 18:18:43 | `reconfigure` done (resumed step: 66 s). `tamper-off` 18:18:45 to 18:19:10 |
| 18:19:10 to 18:21:16 | `snapshot` (including `Removing the leftover optical drives`, 60 s idle), 18:21:16 `register`, 18:21:20 all steps succeeded |
| 18:22:42 | job 53 `done`, guest `ready`, self-test `all checks passed`, analysis 264. Clone to ready: 6 min 8 s |

The resumed `reconfigure` step, from the build log (nothing else of the step is missing; there is no `Reading the
identity the copy came with` and no `Giving the copy its own identity`, i.e. nothing was applied again):

```
== step reconfigure
STEP Starting the copy
PROGRESS 5
STEP Finding the copy on the network
PROGRESS 15
LOG the copy is at 192.168.150.14
PROGRESS 25
PROGRESS 35
STEP Looking for an earlier attempt
PROGRESS 40
LOG an earlier attempt already applied; waiting for its reboot, not applying again
PROGRESS 55
LOG guest: 2026-10-17 16:17:34  reconfiguring as DESKTOP-M2L2OZT at 192.168.150.14
LOG guest: 2026-10-17 16:17:34  STEP static IP 192.168.150.14/24, gateway and DNS 192.168.150.1
LOG guest: 2026-10-17 16:17:36    ok (adapter 'Ethernet' set to 192.168.150.14)
LOG guest: 2026-10-17 16:17:36  STEP computer name DESKTOP-M2L2OZT
LOG guest: 2026-10-17 16:17:36    ok
LOG guest: 2026-10-17 16:17:36  STEP MachineGuid
LOG guest: 2026-10-17 16:17:36    ok (now bd007d9a-bda2-415e-97be-f81b087b714e)
LOG guest: 2026-10-17 16:17:36  STEP decoys (only when asked)
LOG guest: 2026-10-17 16:17:36    ok (not requested)
LOG guest: 2026-10-17 16:17:36  STEP clear the event logs
LOG guest: 2026-10-17 16:17:55    ok (1192 logs)
LOG guest: 2026-10-17 16:17:55  rebooting e4af6ab2-657b-464b-95d5-fca41322ace6
PROGRESS 70
STEP Waiting for the reboot
PROGRESS 90
LOG verified: hostname=DESKTOP-M2L2OZT ip=192.168.150.14 machine_guid=bd007d9a-bda2-415e-97be-f81b087b714e
PROGRESS 100
```

The only "earlier attempt" lines are `STEP Looking for an earlier attempt` and `an earlier attempt already applied;
waiting for its reboot, not applying again`. The MachineGuid in the guest log (`bd007d9a-...`) is the single one
the first run's apply generated; it is also what was verified.

### Drill A checks (P3) on the finished `m7-a`

| # | Check | Result |
|---|---|---|
| 1 | `virsh dumpxml m7-a` has no `device='cdrom'` disk and keeps the sata controller | **PASS.** `grep -c "device='cdrom'"` = 0; `<controller type='sata' index='0'>` present; one `device='disk'` on the overlay `m7-a.1792254132`; `<video><model type='vga' vram='16384' heads='1' primary='yes'/>` |
| 2 | Build log has the pre-snapshot step with `found=` / `removed=` | **PASS.** `STEP Removing the leftover optical drives` / `LOG RESULT found=2` / `LOG RESULT removed=2` / `LOG remove-ghost-drives.ps1: found=2; removed=2` (between "Waiting for the agent" and "Letting the guest idle for 60s"). First time the `agent.pre_snapshot` hook has run for real |
| 3 | After a revert: no CDROM PnP device, no `Enum\SCSI\CdRom*` key, `Win32_CDROMDrive` empty; record `Win32_VideoController` | **PASS.** Revert in 1 s, agent answered in 1 s. `Get-PnpDevice -Class CDROM` count 0 (present or not); `Enum\SCSI` holds only `Disk&Ven_SAMSUNG&Prod_MZ76E120`, CdRom* keys 0; `Win32_CDROMDrive` 0 rows; `DriveType=5` none; `[IO.DriveInfo]` only `C:\ Fixed`; SATA AHCI controller still `PCI\VEN_8086&DEV_2922`, present. Video: `Name=Podstawowa karta graficzna Microsoft`, `PNPDeviceID=PCI\VEN_1234&DEV_1111&SUBSYS_11001AF4&REV_02\3&11583659&0&08`, `ConfigManagerErrorCode=0`, `Status=OK` |
| 4 | Self-test verdict | **PASS.** `GET /guests/m7-a`: `selftest.message = "all checks passed"`, analysis 264 tagged `self-test`, `giveaways: []`, signals (process 2, file 2, registry 3, report, DNS answered) and the Defender proof all ok. The facts the verdict judges (read with the control service's `POST /guests/m7-a/selftest/checks`, and with the real `guest-facts.ps1` through the agent): `cdrom.name=` (empty), `video.pnp=PCI\VEN_1234&DEV_1111&SUBSYS_11001AF4&REV_02\3&11583659&0&08`, `video.name=Podstawowa karta graficzna Microsoft`, zero `GIVEAWAY` lines. Note: the backend keeps only five of the facts in the guest record (`facts_summary`), so `video.pnp` and `cdrom.name` are not in `GET /guests/m7-a`; they were read again, not from the build-time run |
| 5 | Ordinary analysis (non-interactive, 60 s, `benign.exe`) like a run on lab3 | **PASS with a caveat (anomaly 3).** `m7-a`: 265, 515 events, 2 processes, 12 signatures, 13 detections, 10 techniques, score 6.0, artifacts `benign.exe`, `cmd.exe`, `tartarus-benign.txt`, pcap 35 731 B, done in 48 s. The self-test run, 264: 517 events, same everything. `lab3`: 266, 563 events (extra network flows only), same 12 signatures / 13 detections / 10 techniques / artifact names, score 6.0 |
| 6 | Interactive analysis with the desktop probe | **PASS.** Analysis 267 (timeout 120): the canvas lit after 2.0 s with 1 022 831 lit pixels (S2's baseline: 1 022 831), a click at the Start-button coordinates changed the frame (`click_changed_frame: true`), no page errors; `POST /analyses/267/finish` -> 200, status `done` 12 s later, 364 events, score 5.7, `deadline_at` set (the +60s backend) |
| 7 | `make verify-guest` checks 8 to 12 | **PASS for 8, 9, 10 (minus callback), 11, 12**, reproduced by hand with the script's own commands (`p1/verify-eq.sh`): 9 snapshot `tartarus-clean` exists; 9 `apiv2/machines/list` lists `m7-a`; 11 ResultServer listens on `192.168.150.1:2042`; 8 revert + agent HTTP 200 at `192.168.150.14:8000` after 1 s; 10 apiv2 task 256 accepted, reached `reported`, `.bson` logs appeared while `running`, `report.json` exists, `tartarus-selftest.example` in the report; 12 `docker compose up -d --wait --force-recreate cape` (17 s): domain, snapshot `tartarus-clean` and the machines/list registration all survived (registration back 18 s after the recreate) |

Cleanup: analyses 264 to 267 deleted (204 each), `DELETE /guests/m7-a` -> 204 at 18:29:20, `cape` back and the guest list
showed only `win`, `lab1`, `lab3`, `lab5` (all `ready`) at 18:29:26; CAPE's machines list showed the same four at 18:29:32; no
`m7` image left in `/var/lib/libvirt/images`.

## Drill B (P1): resume after a FINISHED apply

Timeline (host clock). Hit on the first attempt (one attempt was enough):

| Time | Event |
|---|---|
| 18:29:32 | `POST /guests/lab3/clone` -> 202, build `b1d53f6cf666c`, job 54 |
| 18:30:31 | `Giving the copy its own identity`, `PROGRESS 55` (before-identity saved: `machine_guid=2da5f343-...`, `boot_time 2026-10-17T14:29:54Z` in `reconfigure-before.json`) |
| 16:30:33 to 16:30:53 UTC | the guest applies: static IP, rename `LAPTOP-HHBEZ1U`, new MachineGuid `df30ad10-...`, event logs cleared, `rebooting 7514bfae-...` at 16:30:53 |
| 18:31:28 | the step's log reaches `PROGRESS 70` / `STEP Waiting for the reboot` (the step only saw the announcement 35 s after the guest wrote it, because the guest was rebooting and its agent was away). **Trigger**: `supervisorctl stop guest-control` |
| 18:31:28 to 18:33:29 | 121 s with the service stopped; the guest finished rebooting and settled (nothing touched it) |
| 18:33:29 | `supervisorctl start guest-control` (1.3 s). Build `failed` (`the control service was stopped while this step was running; resume it`). `POST .../resume` -> 202, job 55 |
| 18:33:31 | resumed `reconfigure`: copy at `.14`, `an earlier attempt already applied; waiting for its reboot, not applying again`, the guest's log printed, `PROGRESS 70`, `Waiting for the reboot` |
| 18:33:41 | `verified: hostname=LAPTOP-HHBEZ1U ip=192.168.150.14 machine_guid=df30ad10-ff93-45fc-a714-90692a94c7db` (the copy came with `2da5f343-...`, taken from the saved before-file, not from this run) |
| 18:33:43 | `reconfigure` done (12 s resumed). `tamper-off`, `snapshot` (`found=2` / `removed=2` again), `register`; 18:36:12 all steps succeeded |
| 18:37:35 | job 55 `done`, guest `ready`, `all checks passed`, analysis 268 tagged `self-test`, giveaways `[]`. Clone to ready, including the 2-minute settle: 8 min 3 s |

Resumed step log (identical in shape to drill A's, with no `Reading the identity ...` and no `Giving ...`):

```
== step reconfigure
STEP Starting the copy                  PROGRESS 5
STEP Finding the copy on the network    PROGRESS 15
LOG the copy is at 192.168.150.14       PROGRESS 25, 35
STEP Looking for an earlier attempt     PROGRESS 40
LOG an earlier attempt already applied; waiting for its reboot, not applying again
PROGRESS 55
LOG guest: 2026-10-17 16:30:33  reconfiguring as LAPTOP-HHBEZ1U at 192.168.150.14
  ... the same six guest lines as in drill A ...
LOG guest: 2026-10-17 16:30:53  rebooting 7514bfae-a6ab-4ec8-b27a-1ddded5933a5
PROGRESS 70
STEP Waiting for the reboot
PROGRESS 90
LOG verified: hostname=LAPTOP-HHBEZ1U ip=192.168.150.14 machine_guid=df30ad10-ff93-45fc-a714-90692a94c7db
PROGRESS 100
```

Drill B checks on `m7-b` (1 to 4):

| # | Result |
|---|---|
| 1 | **PASS.** 0 `device='cdrom'` disks, `<controller type='sata' index='0'>` present |
| 2 | **PASS.** `Removing the leftover optical drives`, `found=2`, `removed=2` |
| 3 | **PASS.** Revert 2 s, agent 2 s. 0 CDROM PnP devices, `Enum\SCSI` holds only the Disk key, 0 `Win32_CDROMDrive` rows, no DriveType 5, SATA controller present. `Win32_VideoController`: `Podstawowa karta graficzna Microsoft`, `PCI\VEN_1234&DEV_1111&SUBSYS_11001AF4&REV_02\3&11583659&0&08`, `ConfigManagerErrorCode=0`, `Status=OK` |
| 4 | **PASS.** `all checks passed`, analysis 268 (`self-test` tag, 513 events), giveaways `[]`; facts through the control service and the real script: `cdrom.name=` empty, `video.pnp=PCI\VEN_1234&DEV_1111&...` |

Cleanup: analysis 268 deleted, `DELETE /guests/m7-b` -> 204 at 18:38:36; at 18:38:44 CAPE listed `lab1`, `lab3`, `lab5`, `win`, the
guest list showed the four `ready`, no build followed, no leftover `m7` image or domain.

## Final state

`win`, `lab1`, `lab3`, `lab5`: `ready` in the API, registered in CAPE (`apiv2/machines/list`), all domains `shut off`.
No analysis of mine is left (264 to 268 deleted; CAPE task 256 deleted). The container's scratch directory
`/tmp/p1-profile` was removed. `git status` is clean apart from this file.

## Not verified

- **The old code was not run.** R1's hypothesis (a resume after a finished apply fails at `verify_identity` on the
  old step) was not reproduced here; nothing was rebuilt. These runs prove the new step is right, not that the old one
  failed.
- **"Log exists, no `rebooting` line yet, guest still up" for the whole 90 s wait**: drill A reached the log within the
  same second as the reboot line, so that exact path ran only against the fake agent (R1's tests). Drill A is the
  closest real case (a resume 3 s after the kill, with the apply running in the guest).
- **That the guest's log is discarded** after a resumed run was not read from the guest (the build went on, and the step ends with
  `discard_guest_log`); not checked directly. Also not run: the `fail_and_let_a_resume_apply_again` path (a verify
  failure) and the "log but no saved before-file" branch.
- **A resume after the backend job restarted**, or a backend restart instead of a `guest-control` stop (P1's
  alternative wording). Only the control-service stop was drilled.
- **`make verify-guest`, `make verify-wizard` and `make e2e` as literal commands**: not run. `verify-guest.sh` is
  hard-wired to `win`; checks 8 to 12 were reproduced by hand; its callback reporting check (10) and the sample being
  built with mingw-w64 were not (the S2 `benign.exe` was used). The wizard's own paths (second clone refused
  while building, analysis refused) were not re-checked; the clone body is `verify-wizard.py`'s with Defender kept off.
- **Defender-on clones** (`lab1`, `lab5` as source) and a **build from an ISO** (install mode with the drives, then
  the ghost-drive removal after a real install): not run; the ghost-drive step was proven on clones only (both found 2
  ghosts inherited from `lab3`'s disk).
- **Decision 7's premise** (an old guest's memory snapshot breaking if the drives are removed under it) is still
  untested and nothing here tried it.
- **The display adapter** is unchanged by design (`VEN_1234&DEV_1111`, Basic Display); only the known tell is
  reported, as decided.
- **Why lab3's own ordinary run had about 45 extra network events** (anomaly 3) and whether ordinary-run
  event counts on a drive-less guest differ systematically from a guest with drives at larger sample sizes: two to
  three runs, not a statistic.
- Timings are polled at 0.5 to 3 s, not instrumented.
