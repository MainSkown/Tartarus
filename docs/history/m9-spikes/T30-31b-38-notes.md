# T3.0 / 3.1b / 3.8 real-stack checks, resume file

Start 2026-10-21 17:35. df / at start: 412132160 KiB free (78% used). HEAD 32da431. Scratch: the session scratchpad `.../scratchpad`.
Stack was DOWN at start.

## Temp changes (all to be reverted)
- (E1, REVERTED by the cape image rebuild at 18:08) analyzer hot-patch IN THE RUNNING cape container only: /opt/CAPEv2/analyzer/windows/analyzer.py gets `self.MONITORED_DCOM = True` after `INTERACTIVE_MODE = True` (experiment, vanishes with `docker compose up --build`/recreate; the real fix is the image patch)
- scratch: scratchpad/t30, benign.exe, iso*.log, up*.log (deleted at the end); cape container /tmp/dbg*.py /tmp/s1.ppm (deleted)
- the real change that stays: cape/patches/leave-dcom-launch-alone.py, cape/Dockerfile, cape/tests/test_analyzer_patches.py, docs/specs/cape-integration.md

## Done
- 17:35 read plan, findings, notes
- 17:40 first image build failed (Launchpad PPA 503, transient), retried; 17:46 stack up, all 5 containers healthy, images from HEAD 32da431
- 17:47 FACT: the cape engine migrated all four real guests (win, lab1, lab3, lab5) itself at service start, before a throwaway clone could be tried first: log 'isolated the network port of <g>' x4; every persistent domain and the tartarus-clean snapshot XML now carry isolated='yes' and tartarus-clean is still the current snapshot (snapshot redefine accepted by libvirt)

## Running
(nothing)

- 17:49 Step 1: verify-isolation lab3 lab5 (both started by snapshot revert): 17 OK, exit 0 (iso1.log). Reverted both again, taps vnet2/vnet3 'isolated on' after revert. Set 'isolated off' on both taps: script 17 lines, 6 FAIL (8000, 445, ping, both ways), make 'Blad 1' = script exit 1. Restored by destroy + rerun: exit 0, 17 OK, 0 FAIL, guests off.

- 17:41 Step 2 (3.1b): analyses 386-388 on lab3 back to back: done in 79/69/67 s, sysmon.xml each, no marker, missing_exports [] (see plan section)
- 17:46-18:13 Step 3 (3.8): reproduced (161 s), cause = DcomLaunch injection (analyzer _handle_interop), fix cape/patches/leave-dcom-launch-alone.py + cape/tests/test_analyzer_patches.py + Dockerfile; cape image rebuilt, 5 runs x 20 s with sysmon.xml
- 18:15 cleanup: analyses 386-398 deleted via API (204), cape /tmp scratch removed

## Next
(nothing: commit, stop the stack)
