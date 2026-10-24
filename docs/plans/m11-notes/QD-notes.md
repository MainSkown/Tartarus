# QD notes: quiet-desktop fails on a Windows 11 clone (done / running / next)

## Done
- Reproduced without a clone: `virsh snapshot-revert lab1 tartarus-clean` in tartarus-cape, then
  `guest_agent.py run quiet-desktop.ps1 --with desktop-apps.ps1 --timeout 400` from inside the cape
  container (profile copied to /tmp/qd): exit 71 after 4.4 s, not after the timeout.
- Raw agent answer: `200 3.08s {"message": "Successfully executed command", "stdout": "", "stderr": ""}`
  (no output at all, not even the EXITCODE line). A trivial script prints fine.
- Cause: on Windows 11 the agent's powershell runs hosted in Windows Terminal. A probe script (t2.ps1) printed
  `chain=powershell.exe <- pythonw.exe <- svchost.exe` and `win WindowsTerminal title=Administrator:
  C:\Windows\Sysnative\WindowsPowerShell\v1.0\powershell.exe`. WindowsTerminal has a main window and is not in
  desktop-apps.ps1's $KeptProcessNames, so quiet-desktop.ps1 CloseMainWindow()s / force-stops the terminal that
  hosts the script itself and the script dies before printing anything. Windows 10 uses conhost, which is kept.

## Running
- nothing

## Next
- regression test (kept list holds WindowsTerminal), fix desktop-apps.ps1, proof on the stack.

## Update
- Regression test first: WindowsTerminal added to KEPT_SCRIPT_HOSTS in cape/tests/test_windows_profile.py; it failed
  (`test_the_shell_and_the_script_hosts_are_kept`, 1 failed), then desktop-apps.ps1 keeps WindowsTerminal: 176 passed.
- Live check on the reverted lab1 with the fixed list: exit 0, `RESULT closed=` `RESULT left=`, 4.4 s. lab1 destroyed after.
- Image bakes guest/profiles/ (cape/Dockerfile:181): desktop-apps.ps1 was `docker cp`ed into the running tartarus-cape at
  /usr/local/lib/tartarus/profiles/windows/ so the proof runs on it; a `make up` rebuild produces the same file.
## Running
- make verify-wizard (clone of lab1), then --source w10-q.
- verify-wizard (default source) run 1: all [ OK ], exit 0. Now --source lab1 then --source w10-q (log scratchpad/vw2.log).
- verify-wizard --source lab1: all [ OK ] (rc 0), twice (default source run + explicit lab1).
- verify-wizard --source w10-q: FAILED once (job 138): quiet-desktop worked (closed=msedge; left=), then self-test
  "the clean snapshot has an open app: WinStore.App". Not obviously caused by the WindowsTerminal change (kept list only
  grew). Investigating: rerun to see if deterministic.
- w10-q rerun: all [ OK ], rc 0. The WinStore.App failure was a one-off (a Store window appearing after quiet-desktop,
  Windows 10 only); not reproduced, not fixed. make test-scripts, test-cape (after one load-flaky test_steps timeout test
  that passes alone), lint green.
## Running
- nothing
## Next
- nothing; rebuild the cape image (make up) so the fixed desktop-apps.ps1 is baked in.
