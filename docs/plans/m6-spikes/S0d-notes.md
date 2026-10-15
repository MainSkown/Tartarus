# S0d notes
Scratch: /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/7ecb9355-8642-4512-8a41-80cb1a8c2d4d/scratchpad/s0d
Baseline of win saved in scratch (win.dumpxml.before, win.snaplist.before, win.files.before).
Note: win-clean.qcow2 does NOT exist; the live overlay is win.1792021253 (backing win.qcow2). Baseline hashes include win.1792021253 and win_VARS.fd.

- done: baseline saved
- running: nothing
- next: identity, convert, nvram copy, define win2, cold boot

## Progress log (update)
- done: convert (11 s), nvram copy, win2 defined (uuid c03bf709-...), cold boot OK, agent at .10 after 53 s, facts before rename collected
- observed: clean boot, no repair screen; Kernel-Power 41 only; TPM cleared+re-provisioned by Windows (SRK changed); adapter same GUID/name/ifIndex, new MAC, but IPv4 came back as DHCP (static config lost; DHCP range is only .10 so it got .10)
- running: nothing
- next: set IP .11 + computer name through agent, reboot, verify; ACPI shutdown, boot, idle 60 s, snapshot, compare win baseline
