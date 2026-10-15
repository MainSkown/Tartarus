# C4 notes (done / running / next)

Baseline before any change: `pytest -q` in cape/ -> 1202 passed, 1 skipped.

## Done (each piece: test written and seen failing, then the code)
- `cape/tests/test_clone_pipeline.py`: the REAL windows profile loads with the REAL generic steps dir
  (failed first with "no executable step 'copy'", then 'reconfigure'); green now.
- `guest_agent.py` additions, `cape/tests/test_clone_agent.py` (failed first): `TT_AGENT_HOST` (address
  to talk to instead of the recorded one) and `run --async` (new `GuestAgent.start_script`, `run_script`
  untouched in behaviour; its 33 tests still pass).
- `guest/steps/copy` + copy tests in `scripts/tests/test_clone_steps.sh` (all failed first: step missing).
- `guest/profiles/windows/reconfigure.ps1` (phases Report / Apply / Discard) +
  `cape/tests/test_clone_reconfigure_script.py` (failed first: script missing).
- `guest/profiles/windows/steps/reconfigure` + its tests in `test_clone_steps.sh` (failed first: step missing).
- Additions to shared libs: `GUEST_NETWORK=tt-guest` in `guest/steps/lib/common.sh`; `result_field` and
  `log_guest_file` in `guest/profiles/windows/steps/lib/windows.sh`. No existing function changed.
- Mutation checks: copy 23 mutants (the survivors were equivalent code, removed: the per-file ownership
  copy and the redundant `rm .part`); reconfigure step 28 mutants, 5 survived at first and got tests
  (decoys upload, ipv4 filter, newest lease, prefix from subnet, generated token); all killed after.
  reconfigure.ps1: 14 mutants against the static tests, 1 survived (Prefix type) and got a test.
- Real PowerShell (docker mcr.microsoft.com/powershell, Linux): all .ps1 parse with 0 errors; Apply and
  Discard were executed there: the Windows cmdlets are missing so every step logs FAILED softly, the
  log still ends with `rebooting <token>`, Discard removes it, a bad -Phase is refused by ValidateSet,
  exit code 0. That run found that Set-ItemProperty/New-NetIPAddress/Set-DnsClientServerAddress errors
  are non-terminating (the step would have logged "ok" over them): they now carry -ErrorAction Stop
  (static test added).

## Findings and decisions
- work_dir and account are consistent already: `validate_clone` returns a spec with `source.work_dir`,
  and the source's account and password (`test_validation.py::test_a_bare_clone_inherits_everything...`
  asserts it). The clone's `guest.work_dir` is therefore the source's; the step uses `guest.work_dir`,
  not `source.work_dir`. No change to cape/guest_engine, no engine bug found.
- `copy` reads the source domain with `virsh dumpxml` (current disk and `<nvram>`) instead of
  `domblklist`: one call gives both and needs no table parsing. The base disk is the last file of
  `qemu-img info --backing-chain --output=json` (its `full-backing-filename` when the chain has one).
  Virtual size of that base must equal the clone's recorded `disk_gb` GiB.
- `copy` does not chown: the build's `qemu-img create` does not either, and libvirt labels files at start.
  (S0d chowned by hand; not verified that it is unnecessary for a copied disk.)
- Reboot detection: the Apply script runs async and is the only thing that can say "I am about to
  reboot": it logs `rebooting <token>` (a fresh uuid per run, so an earlier run's log is never taken
  for this one's) to `<work_dir>\<log_file from names.json>`; the host reads that file through the
  file API (no script run, so the driver files of Apply cannot be clobbered), waits a few seconds,
  then polls the Report phase at the FINAL address until `boot_time` differs from the one read before
  Apply. Then it compares hostname (case-insensitive), the single non-link-local IPv4 and MachineGuid
  against the context (MachineGuid must differ from before), logs what it found, and asks Discard to
  delete the guest-side log.
- Address finding: first the final address (a re-run), else the newest IPv4 lease of the clone's MAC
  in `virsh net-dhcp-leases tt-guest`; never the source's address.
- The agent's `/execute` with `async=1` is S0d's call; the fake agent in the tests only records the flag.
- Tests for reconfigure use a subclass of the fake agent written inline in test_clone_steps.sh (it
  answers on every loopback address, only on those a scenario lists before/after Apply, scripted
  outputs per call), because scripts/tests/fake_guest_agent.py was not mine to edit.
- The provision step has its own copy of the "log every line of a guest file" loop; `log_guest_file`
  in windows.sh is the shared version (provision not refactored: not my file).

## Not verified
- Nothing ran against a real guest or real libvirt/qemu-img (all stubs / fake agent / Linux pwsh).
- Real formats assumed: `virsh net-dhcp-leases` columns, `qemu-img info --backing-chain` JSON,
  `virsh dumpxml` of a domain with an external snapshot.
- Whether `Set-ItemProperty` on HKLM:\SOFTWARE\Microsoft\Cryptography, `wevtutil cl`, `Rename-Computer`
  and the IP change behave as S0d/decision 15 expect when run from this script (S0d never tried
  MachineGuid or the event logs; clearing the logs itself writes events 1102/104).
- Whether the async driver's `finally` (deletes reconfigure.ps1, decoys.ps1, run.ps1) runs before the
  shutdown kills it; if not, those neutral-named files stay in the work folder.

## Running
- nothing

## Next
- final report
