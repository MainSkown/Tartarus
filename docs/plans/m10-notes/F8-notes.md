# M10 F8 notes (PowerShell sample stalls the guest agent on w10)

## State: running (spike)

- done: read F8/F9, event-logs module, analyzer patches. Queue was empty at start.
- done: OpenSearch evidence from analyses 436/438 (below).
- running: run A (baseline reproduction with host-side sampling).
- next: interactive=true run (existing DcomLaunch patch applies), then decide.

## Evidence from the stored events (read-only, analyses 438, 436, 437)

- 438 `capemon.api` by process.entity_id: powershell.exe pid 1660 18,337 events (all within 8 s, 20:54:11 to 20:54:20),
  explorer.exe pid 4388 6,752 events (to 20:55:14), ping.exe 560, cmd.exe 211, `svchost.exe -k DcomLaunch -p` pid 812: 20 events
  (20:54:12 to 20:55:05). 436 is the same shape. 437 (Windows 11): powershell.exe only, 977 events, no explorer, no svchost.
- So in the non-interactive Windows 10 run CAPE's analyzer injected the monitor into Explorer (`_handle_shell`) and into
  the DCOM launcher (`_handle_interop`). Both messages come from the monitor in powershell. This is the F7 mechanism
  (docs/specs/cape-integration.md, "The DCOM launcher is not monitored in an interactive analysis"), whose patch
  (`cape/patches/leave-dcom-launch-alone.py`) sets `MONITORED_DCOM` only in the interactive branch.
- Last API event of the run 20:55:15; next events 20:55:20 to 20:57:45 are single sysmon-less stragglers; `network_http`
  etc. signatures stamped 20:57:49 (report time). The agent stall is therefore 20:55:12 to about 20:57:49.
run A id 440 23:19:05

## Run A: analysis 440 (same sample, w10, ps1, timeout 60, non-interactive), 21:19 to 21:21

- Sampling every 8 s from the host: `virsh domstats w10 --cpu-total` and GET :8000/status through the cape container.
- Result: NO STALL this time. Analyzer completed 21:20:26 (analysis task 454), Sysmon exported at once: 4,854 events;
  Defender export FAILED differently: `Invalid base64-encoded string: number of data characters (13) cannot be 1 more
  than a multiple of 4` (the agent's answer to the powershell export was not base64; an F9 case of its own).
  Analysis ended `done` in 125 s, 28,583 events (27,429 capemon.api: powershell 22,011 in 9 s, explorer 4,861, DcomLaunch svchost 691).
- Explorer (pid 4388) and `svchost -k DcomLaunch -p` (pid 812) were injected again, as in 436/438.
- The guest's two vCPUs were pinned for the whole 60 s (cpu.time grows 16 s per 8 s sample) even after powershell had
  ended at +9 s and API logging had fallen to under 100 events/s; agent /status answered in 1 to 7 ms throughout.
- So the stall is intermittent (2 of 3 runs). Next: repeat identical (run B) to measure it; screenshot on stall.
run B id 441 23:24:34

## Run B: analysis 441 (identical to A), 21:24 to 21:26 UTC

- NO STALL again. Analyzer completed 21:25:58, Sysmon 10,303 events exported immediately, Defender 0 events (ok), no
  missing_exports. 31,291 events. Same injection of explorer and DcomLaunch. CPU again pinned on both vCPUs for the whole run.
- Screenshot at +20 s: Edge open on the desktop (INetSim page for msftconnecttest.com/redirect, NCSI captive-portal check) with
  a "Restore pages" bubble; no hung window.
- Timeline of the earlier stalled runs (UTC): 436 20:46:40 to 20:50:52, 438 20:53:55 to 20:58:07, while the planner's Q5 proof
  clone `w10-q5` existed (analysis 435 ran on it at 20:44) and the host was busy with the planner's other work. 440/441 ran
  with only w10 up. A host-load cause is untested. Reproduction rate now: 0 of 2 (was 2 of 2).
- Next: run C, a trivial `Write-Output hi` .ps1 on w10, to see whether the pinned CPU is the guest's own background load.
run C id 442 23:33:40

## Run C: analysis 442, TRIVIAL sample (`Write-Output "hi"`), w10, ps1, timeout 60, non-interactive: STALL REPRODUCED

- Analyzer completed 21:35:08 (task 456). From 21:35:05 (23:35:17 local) GET :8000/status stopped answering for 150 s
  (every probe `000`, 4 s connect/read timeout) until the run was torn down; Sysmon export `Read timed out (120)` at 21:37:08,
  Defender `Read timed out (30)` at 21:37:38. Both vCPUs stayed pinned (24 s CPU per 12 s) the whole stall.
- The sample is irrelevant: the one-line script gave 47,107 capemon.api events (powershell 19,512 in 6 s, explorer 18,507,
  ApplicationFrameHost 3,990, three RuntimeBroker 1,662/1,627/866, dllhost 791, DcomLaunch svchost 252). So hypothesis (a)
  (hooks looping in PowerShell 5.1 makes the guest stall) is REJECTED as the stall cause: 19k events in 6 s is just PowerShell
  5.1's .NET start-up under the monitor on Windows 10 (4,994 NtAllocate / 4,919 NtFree virtual memory), and it ended after 6 s.
- Screenshot during the stall (scratchpad shot-442-20.png): the agent's `wevtutil.exe` console window is open, black and empty,
  on top of the Edge window: the process the agent started never got to run. This is the F7 symptom exactly (a new process
  started after the analyzer ends hangs; /status itself also hangs here because the agent's server is one thread blocked on it).
- What differed from the non-stalling runs 440/441: extra Store-app processes were injected through COM activation
  (ApplicationFrameHost -Embedding, RuntimeBroker -Embedding x3, dllhost /processid, `wwahost` for microsoft.microsoftofficehub).
  All of them are children of the hooked DcomLaunch service. Runs 440/441 also had the DcomLaunch hook but fewer such children.
- Stall tally with explorer and DcomLaunch both injected: 436, 438, 442 stalled; 440, 441 did not (3 of 5).
- Hypotheses: (b) a CPU-hungry payload process: no, the payload (powershell) is gone 6 s in, and the CPU stays pinned in
  every run (also the clean ones) so CPU use alone does not discriminate; (c) slow wevtutil: no, 440/441 export 4,854 and
  10,303 events in 1 to 3 s; (d) agent blocked by a still-running execute: no execute is running, the agent is blocked by
  the new process it just started (the wevtutil window).
- Next: interactive=true runs of the same q6 sample (the existing patch sets MONITORED_DCOM there, so DcomLaunch is not injected):
  3 clean exports in a row (chance of that without the fix at 3 of 5 per run: about 6 %) would support the DcomLaunch hook as the cause.
  The product fix would be the same patch for non-interactive runs; I cannot test it directly (changing analyzer.py in the container
  is not a config value, outside this spike's rules).
run D (interactive) id 443 23:42:59

## Run D: analysis 443, q6 sample, interactive=true (existing DcomLaunch patch active), 21:42 to 21:45 UTC

- No stall: analyzer completed 21:44:07, Sysmon 4,832 events exported 3 s later. No `svchost.exe -k DcomLaunch` and no Store-app
  processes in the events (processes: powershell, explorer, ping, cmd, edgeupdate, notepad, sppsvc). Defender export FAILED
  with the same `Invalid base64-encoded string: number of data characters (13)` as run A (440), and not in run B (441).
  27,096 capemon.api events (powershell 22,864): the API count stays 25x the Windows 11 run, interactive or not.
- 1 clean of the interactive series so far (need 3). Next: runs E and F the same way.
run E (interactive) id 444 23:51:37

## Run E: analysis 444, interactive=true, 21:50 to 21:53 UTC
- No stall: analyzer completed 21:52:52, Sysmon 4,761 events and Defender 0 events (ok) exported within 5 s. 2 clean of 2 interactive.
- Next: run F (interactive again).
run F (interactive) id 445 00:00:17

## Run F: analysis 445, interactive=true, 22:00 to 22:02 UTC
- No stall: Sysmon 4,795 events exported 3 s after the analyzer; Defender export failed with the `Invalid base64 ... (13)` error again
  (A, D, F fail, B, E ok: a separate flaky Defender export, not the stall; the module should record the agent's raw answer).
- 3 of 3 interactive runs (DcomLaunch not injected) exported Sysmon; 0 of 3 had a DcomLaunch or Store-app process in the events.
  Non-interactive with DcomLaunch injected: 436, 438, 442 stalled, 440, 441 did not.

## State: DONE

- Cause: the monitor injected into `svchost.exe -k DcomLaunch` (by CAPE's `_handle_interop`, on a COM message from the monitored
  powershell) and left there after the analyzer exits; when COM activation has started Store-app processes (ApplicationFrameHost,
  RuntimeBroker, dllhost, wwahost) the next process the agent starts (wevtutil) never runs and the agent's single thread stays
  blocked until the guest is shut off. Same mechanism as F7, whose patch is limited to interactive analyses.
- Fix: set `self.MONITORED_DCOM = True` for every analysis, not only interactive (`cape/patches/leave-dcom-launch-alone.py`).
- Nothing was changed in the container or the repo (only this file). 25k API events is PowerShell 5.1's start-up on Windows 10 and
  is unrelated to the stall; not reduced (no public option reaches capemon's options).
