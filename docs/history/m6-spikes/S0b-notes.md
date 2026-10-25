# S0b notes

- done: everything. Findings in S0b-findings.md. Registration restored (win.conf byte-identical, sha a93d0859...), guests.conf and callback listener removed, orphan tcpdumps killed, win and win2 shut off, win2 unregistered. `make verify-guest` after restore: 12 OK, 0 FAIL (run twice).
- running: nothing
- next: planner reads S0b-findings.md (decisions 5, 6, 7, 15 changes; DHCP pool recommendation; finish-run by guest name; registration owns the whole kvm.conf.d dir)
