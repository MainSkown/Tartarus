# T3.6 real-stack proof of wave 3, resume file

Start 2026-10-21 19:54. df / at start: 392G free (78% used). HEAD eb19828. Scratch: /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/c9689fac-df10-4bbf-b5b7-5153d091d85e/scratchpad/t36
Stack was DOWN at start (docker ps empty; only exited leftovers). git status clean.

## Big files that exist right now
(none)

## Done
- 19:54 read plan, P3 findings, PROOF-notes, T30 notes

## Running
(nothing)

## Next
- rebuild images, start stack, proofs 1-9, plan section, cleanup
- 19:56 stack up (images from HEAD eb19828), http://127.0.0.1:8080
- 19:59 solo runs: 399 lab3 (616 events? see lane counts), 400 lab5, both done, benign unique copies, timeout 60
- 20:02 pair 1: 402 (lab3) + 401 (lab5) submitted at the same moment, both done (64 s, 83 s); solo 399 lab3, 400 lab5. Pair-time checks done on the way: /system/queue lists both (elapsed), 409 naming both on build/clone/delete/continue/check, PCAP import 403 done in about 8 s while both ran. Lane diff: lab5 401 vs solo 400 registry 28 vs 12, process 27 vs 24: all extra events are MicrosoftEdgeUpdate.exe (guest background); checking with a second solo lab5 and a second pair whether this is noise
- result files in scratchpad t36/ (live_*.jsonl, sysws_pair.jsonl, queue_pair.txt)
- 20:09 pair 2: 406 lab3 + 405 lab5 done; more solos 404 lab5, 407 lab3, 408 lab3 for the noise band. Lane counts: process/file/registry equal in pair 2 and for lab3 pair 1; lab5 pair 1 (401) had Edge-updater background (+3 process, +16 registry), not seen in 2 solo or pair 2 => guest background, record as noise. network solo lab3 108/106/120, parallel 107/129 (guest's own flows to .1). PCAPs of tasks 417,418,421,422 each hold only own guest IP + 192.168.150.1 and own MAC + bridge MAC. Live feeds 401/402: own entity_id prefix only, other sample name in 0 events. Queue ws: 13 queue pushes, shows both running.
- Next: Q run (two long runs + queued + idle-guest + verify-isolation), then interactive pair (7), make e2e, plan section, cleanup
- 20:14 Q run: 409 lab3 + 410 lab5 (timeout 150 but benign.exe ends the analysis after about 64 s, so not long enough for verify-isolation), 411 lab3 queued (position 1), 412 lab1 idle: started 3 s after submit while 411 waited. verify-isolation #1 during the Q run: lab5 probes did not finish (banner only), lab3 ok; #2 ran after 409 ended: exit 0 (not a valid while-running proof). Redo with two interactive runs (held until /finish) together with step (7). TODO investigate lab5 probe failure under analysis.
- 20:16 lesson: verify-isolation must not overlap an analysis that can start or end on its guests (my second run collided with queued 411 on lab3: its CAPE task stalled 4.5 min, agent dead, my fault, not a defect); lab5 left running by it, destroyed. 411 started 3 s after 409 ended (guest freed). Now: interactive pair (7) + verify-isolation (5) while both held.
- 20:19 interactive pair 413 (lab3, task 429, vnc 5900) + 414 (lab5, task 430, vnc 5901): both desktop tunnels via scripts/lib/live_client.py open at once, first frame 0.03 s, guacd had one ESTABLISHED connection to each of 5900 and 5901 for the whole time; verify-isolation during them: 17 OK exit 0; /finish 413 at 18:18:15 -> done 18:18:29 (14 s), /finish 414 18:18:23 -> done 18:18:40 (17 s), both sysmon.xml (8.0, 10.1 MB), missing_exports []; tunnels closed 1000 at run end (guacd 515), 413's 8 s before 414's. After both ended: DELETE unknown guest 404 (gate passed), POST /guests/lab1/check 200.
- Done so far: (1)(2)(3)(4)(5)(6)(7)(8). Left: (9) make e2e, plan section, cleanup (analyses 399-414 + e2e ones, scratch), stop stack, commit
- running: make e2e (log /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/c9689fac-df10-4bbf-b5b7-5153d091d85e/scratchpad/t36/e2e.log) started 20:19
- 20:27 make e2e run 1: 120 OK, 10 FAIL, all in (b)(c)(d)(j): they submitted 2-3 default-guest analyses and expected the 2nd to queue; with wave 3 they run on three guests. Fixed test-first: options_on_the_guest_of (e2e-api.sh, test in test_e2e_cleanup.sh), e2e.sh (b,c) and e2e-finish.sh (j) pin to the first one's guest. Rerunning make e2e.
- 20:33 make e2e run 2: 129 OK, 0 FAIL, exit 0. Next: pair 3 + verify-isolation during non-interactive pair (reproduce lab5 probe failure), then plan section, cleanup
- 20:37 pair 3 (430 lab5, 431 lab3) with verify-isolation during it: exit 0, 17 OK (the first-attempt lab5 failure did not recur); Defender export of 431 lost once (recorded). Plan section "Wave 3 proof" written. cleanup: analyses 399-414, 430, 431 deleted (204), no dumps, scratch removed, stack down. df / at end: 391G free (79% used) (start 392G free).

## Final state
All steps done. Nothing running, no big files.
