# S0b findings: two machines in CAPE

Date: 2026-10-15. Everything here was observed on the real stack (cape and postgres running, nothing else) with
`win` (192.168.150.10, the M0b guest) and `win2` (192.168.150.11, the clone S0d left). Only
`/var/lib/libvirt/tartarus/kvm.conf.d/`, the temporary `callback.conf` listener and the `cape` supervisor program
were touched; nothing in `cape/`, `backend/`, `frontend/`, `guest/`, `scripts/` or any other doc was edited.
Raw outputs (run logs with the per-3-s poll, evidence per task, the backups) are in
`/tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/7ecb9355-8642-4512-8a41-80cb1a8c2d4d/scratchpad/s0b/`.

## Answer

**YES: CAPE serves two registered machines and routes by label.** One `kvm.conf.d/guests.conf` listing `win,win2`
with distinct IPs works; `machine=<label>` ran the task on exactly that domain, with its own snapshot revert, the
agent at the right IP, the ResultServer connection, the rooter rules for the right address, the right PCAP source
address, the INetSim answer and the callback (tasks 194 on `win`, 195 and 202 on `win2`). The traps are all around
the registration, not the routing: the file must be the only one in `kvm.conf.d/` (a later-sorting file wins),
`machine` must always be sent (omitted alternates between the guests), a restart of `cape` kills the running task,
and `finish-run` and the DHCP range are hard-wired to `.10`.

## The registration file that worked

```
[kvm]
machines = win,win2

[win]
label = win
platform = windows
ip = 192.168.150.10
snapshot = tartarus-clean
arch = x64
interface = tt-guest
tags = windows,win11

[win2]
label = win2
platform = windows
ip = 192.168.150.11
snapshot = tartarus-clean
arch = x64
interface = tt-guest
tags = windows,win11
```

Each section is `win.conf`'s keys, nothing added. `win.conf` itself was removed from the directory while this was
in place (see 1). Copy of the file: `.../s0b/guests.conf`.

## 1. One registration file

- `Config("kvm")._get_files_to_read()` (CAPE's `lib/cuckoo/common/config.py`) returns, in order:
  `conf/default/kvm.conf.default`, `conf/kvm.conf`, `custom/conf/kvm.conf`, then `sorted(glob(custom/conf/kvm.conf.d/*.conf))`,
  and `configparser.read()` merges them: sections accumulate, a key set twice takes the **last** value.
  `custom/conf/kvm.conf.d` is a symlink to `/var/lib/libvirt/tartarus/kvm.conf.d` (`cape/Dockerfile:132`).
- **Two files vs one, observed.** With `win.conf` (`machines = win`) and `guests.conf` (`machines = win,win2`) both in
  the directory, the files list was `[..., kvm.conf.d/guests.conf, kvm.conf.d/win.conf]` and
  `Config("kvm").kvm.machines` printed `win`. `win.conf` sorts after `guests.conf` ("w" > "g"), so it won and `win2`'s
  section was ignored. `cape` was not restarted in that state; it is the same value CAPE reads at start.
  After `rm win.conf`, only `guests.conf` is read and `machines = win,win2` takes effect.
  **So: the control service must delete or rename every other `*.conf` in the directory (including adopted `win.conf`)
  when it writes `guests.conf`; otherwise whichever sorts last decides which guests exist.**
- `supervisorctl restart cape` with only `guests.conf` present: `cape: stopped / cape: started`, uptime stable
  (no crash), and in the log:
  ```
  13:49:56,398 [lib.cuckoo.core.machinery_manager] INFO: Using MachineryManager[kvm] with max_machines_count=10
  13:49:56,416 [lib.cuckoo.core.machinery_manager] INFO: Loaded 2 machines
  13:49:56,417 [cuckoo-rooter] INFO: Disabling inetsim route.   (twice, once per machine's IP)
  13:49:56,444 [lib.cuckoo.core.scheduler] INFO: Waiting for analysis tasks
  ```
- `GET apiv2/machines/list/` (token and URL as in `verify-guest.sh`):
  `win` ip 192.168.150.10, `win2` ip 192.168.150.11; both `platform: windows`, `arch: x64`, `interface: tt-guest`,
  `snapshot: tartarus-clean`, `tags: [win11, windows]`, `locked: false`, `status: poweroff`,
  `resultserver_ip: 192.168.150.1`, `resultserver_port: 2042`, `reserved: false`.
  `apiv2/cuckoo/status/` agreed (`machines: total 2, available 2` at the shared-IP and ghost steps below).
- **CAPE recreates the machine rows at every `cape` start** (`Machine` ids 58 -> 59/60 -> 61/62 ...; `abstracts.py`
  `initialize()` calls `db.clean_machines()` first). `tasks.machine` keeps the label, `tasks.machine_id` goes stale.
  Not harmful, but the backend must key on the label, never on the machine id.
- **A registered machine that is not defined in libvirt blocks `cape` silently.** I registered a third section `ghost`
  (never defined) in `guests.conf` and restarted: `supervisorctl status cape` says `RUNNING`, but the process is
  `bash wait-then-exec ... registered-guest -- python cuckoo.py`, the log says
  `wait-then-exec: waiting for registered-guest before starting /opt/CAPEv2/.venv/bin/python`, and
  `cuckoo/status` still reports `machines: total 2, available 2` (stale rows), so `POST tasks/create/file` would be
  accepted and stay `pending`. Reverted at once. The order must be: define the domain, then register; unregister,
  then undefine.

## 2. Routing by label

Every task: `benign.exe` built with `scripts/lib/benign-sample.sh` (the throwaway ubuntu+mingw container),
`route=inetsim`, `package=exe`, `timeout=60`, `POST apiv2/tasks/create/file/`. A temporary `tt-callback` container and
`reporting.conf.d/callback.conf` were in place as in `verify-guest.sh` and removed afterwards.
The per-3-s poll is in `run-win.log` and `run-win2.log`; `evidence-194.txt` and `evidence-195.txt` hold the rest.

| | `machine=win` (task 194) | `machine=win2` (task 195) |
|---|---|---|
| Scheduler | `found useable machine win` | `found useable machine win2` |
| Domain that ran (`virsh list --all`, polled) | `win=running win2=shut off` for the whole run | `win2=running win=shut off` for the whole run |
| Revert to `tartarus-clean` | QEMU started with `-incoming defer`; the domain XML's overlay changed `win.1792021253` -> `win.1792072265` | `-incoming defer`; overlay `win2.1792071621` -> `win2.1792072390` (CAPE's revert replaces the overlay, as S0d saw) |
| Agent | `Guest is running CAPE Agent 0.23 (id=win, ip=192.168.150.10)` 2 s after the start | `... (id=win2, ip=192.168.150.11)` |
| Sniffer | `Started sniffer ... host=192.168.150.10, dump path=.../194/dump.pcap` | `... host=192.168.150.11 ...` (the `tcpdump` command line filters `host 192.168.150.11`) |
| ResultServer | `cuckoo.log`: `Task 194: Process 9344 ... benign.exe`, `Process 7072 ... cmd.exe`; `logs/9344.bson`, `7072.bson`; `ss` mid-run: 4 established connections `192.168.150.1:2042 <- 192.168.150.10:*` (task 203) | `Task 195: Process 6500 ... benign.exe`, `2892 ... cmd.exe`; 4 connections from `192.168.150.11:*` (task 202) |
| Rooter while running (`iptables -t nat -S`) | 11 `CAPE-rooter` rules, all `-s 192.168.150.10/32` (14 lines in the dump; none with `.11`) | 11 rules, all `-s 192.168.150.11/32`, e.g. `-A PREROUTING -s 192.168.150.11/32 -p udp -m udp --dport 53 ... -j DNAT --to-destination 192.168.150.1:53`; also `INPUT ... -s 192.168.150.11/32 --dport 22 DROP`, `OUTPUT -s 192.168.150.11/32 DROP`, `LIBVIRT_FWO -s 192.168.150.11/32 -i tt-guest ACCEPT` |
| After the run | `Disabled route 'inetsim'`; rule count back to 2 (the two global `MASQUERADE` rules that were there before), no `.10` source left | same, back to 2, no `.11` left |
| PCAP source addresses (`dump.pcap`) | 1045 packets from 192.168.150.10, 942 from 192.168.150.1, nothing else | 513 from 192.168.150.11, 468 from 192.168.150.1, nothing else |
| DNS `tartarus-selftest.example` | query `192.168.150.10.64214 > 192.168.150.1.53`, answer `A 192.168.150.1` (INetSim) in the PCAP; in `report.json` `network.dns` (its `answers` list is empty, as before) | query from `.11`, answer `A 192.168.150.1`; in the report the same way |
| Report | `reports/report.json`; processes `benign.exe`, `cmd.exe`; 249 and 224 calls (the M0b numbers); summary files 7, write_files 1, keys 27, write_keys 2, executed_commands 1; `info.machine.name/label = win` | same processes, 247 and 224 calls, same summary counts; `info.machine.name/label = win2` |
| Callback | `CALLBACK {"task_id": 194}` at the listener | `CALLBACK {"task_id": 195}` |
| Timing | submit 13:51:04, `completed` 13:52:03 | submit 13:53:09, `completed` 13:53:58 |

Task 202 (`win2`) and 203 (`win`) repeated this with the ResultServer `ss` capture taken once the `.bson` logs existed:
listener `LISTEN 192.168.150.1:2042 0.0.0.0:*` (one socket for both guests), and the connection peers were `.11` for
202 and `.10` for 203. CAPE maps a connection to a task **by the guest's source IP**
(`resultserver.py`: `self.tasks[ipaddr] = task_id`, `self.tasks.get(ipaddr)`; "ResultServer did not have a task for
IP" otherwise), which is why distinct IPs matter (4).

**`machine` omitted** (two machines registered, both free): task 196 ran on `win`, the next, 197, on `win2`
(`found useable machine win` then `win2`). `find_machine_to_service_task` in
`lib/cuckoo/core/data/machines.py` orders by `Machine.locked, Machine.locked_changed_on` and takes the first, i.e. the
least recently used free machine, so omitted alternates, and when both are free the analyst cannot predict which. If
the named machine is busy the task waits (`return None` when `machine.locked`). **Omitting `machine` is not safe;
the backend must always send it.** (Whether two *omitted* tasks submitted back to back would run on both guests at
once was not tried, deliberately: only one task at a time here.)

**`machine=nosuch`** (not registered): `HTTP/1.1 200 OK` with
`{"error":true,"error_value":"Machine 'nosuch' does not exist. Available: win, win2"}`. No task was created
(the task list is unchanged). The backend must read `error`, not the HTTP status, to turn this into its 409.

## 3. Restart behaviour (what registering or deleting a guest does)

**`supervisorctl restart cape` with task 198 running on `win2`** (agent working, `.bson` logs flowing):

```
13:57:37,222 INFO waiting for cape to stop
13:57:37,222 [lib.cuckoo.core.scheduler] INFO: received signal 'SIGTERM', waiting for remaining analysis to finish before stopping
13:57:37,226 [lib.cuckoo.common.abstracts] INFO: Shutting down machine 'win2'
13:57:37,656 INFO stopped: cape (exit status 0)
13:57:37,658 INFO spawned: 'cape' with pid 9444
13:57:38,514 [root] INFO: Updated running task ID 198 status to failed_analysis
```

- Despite the "waiting for remaining analysis" line it does not wait: **the machine is destroyed on the way down**, in
  the stop, 0.2 s after SIGTERM (libvirt's `win2.log`: `13:57:37.428: shutting down, reason=destroyed`). The whole
  stop took 0.4 s (`stopwaitsecs=30` was not reached).
- The task ends `failed_analysis`, set by the **next start** ("Updated running task ID 198 status to
  failed_analysis"). DB: `started_on` set, `completed_on` empty, `machine_id` stale (60), `errors: []`, no
  `report.json`, no callback. The DB machine rows after the restart: `win`, `win2` unlocked, `poweroff`.
- `rooter` rules: 11 before, 2 after (`Disabling inetsim route.` at start).
- **Leak: the sniffer's `tcpdump` (pid 9195) survived** the restart and kept running (and writing to `198/dump.pcap`)
  until I killed it by hand. Same for the kill below (pid 9725). They were the only side effect that outlives a
  restart; I killed both, `pgrep tcpdump` was empty afterwards. A real restart during an analysis leaves a stray
  `tcpdump` until the container is recreated.

**Decision 7's claim, checked: "`cuckoo.py` powers off a running registered machine when it starts".** Confirmed for a
crash and corrected for a restart. With task 199 running on `win2` I sent `kill -9` to `python cuckoo.py`; supervisor
respawned it (`WARN exited: cape (terminated by SIGKILL; not expected)`, `spawned: 'cape' with pid 9889`) and
13:58:29-31 later the domain was gone: `win2.log: 13:58:31.234: shutting down, reason=destroyed`, i.e. **the start path
destroys a running registered machine** (`Machinery._initialize_check` -> `shutdown_running_machines`), then
`Updated running task ID 199 status to failed_analysis`. So both paths power the guest off. The correction: with a
graceful `supervisorctl restart` the machine goes down in the *stop* (above), not "at start", and the task is failed
at the next start. Either way the running analysis is lost.

After both, the snapshots were intact: later tasks on `win2` (201, 202, 205) reverted and ran normally.

**A registration that removes a machine, with a task already queued for it.** `supervisorctl stop cape`, submit
`machine=win2` (task 200: `pending`, accepted because the DB still listed it), write `guests.conf` with only `win`,
`supervisorctl start cape`:

```
13:59:29,186 [lib.cuckoo.core.machinery_manager] INFO: Loaded 1 machine
13:59:29,215 [lib.cuckoo.core.scheduler] INFO: Task #200: Failing unserviceable task because no matching machine could be found. Requested tags: 'x64'. Available machine tags: ...
```
Task 200 ended `failed_analysis` (no `machine_id`, no `started_on`, `errors: []`) within 1 s of the start. So deleting a
guest fails every task queued for it, silently (no message in the task). Queued tasks for the *remaining* machines
were not tested.

## 4. Shared IP

`guests.conf` with `win2`'s `ip = 192.168.150.10` (same as `win`), `supervisorctl restart cape`: **accepted, no
warning, no error.** `Loaded 2 machines`, `machines/list` shows both with `192.168.150.10`, `cuckoo/status` total 2,
available 2. No analysis was run in this state. From the code: the DB has no uniqueness on `ip`
(`add_machine`), and the ResultServer, the rooter rules, the sniffer filter and the agent URL are all keyed by IP, so
two guests with one IP would be indistinguishable to CAPE (and a `win2` reverted from its `.11` snapshot would not
answer at `.10` at all). Nothing in CAPE protects against it, **so the control service has to refuse duplicates**.
Distinct IPs restored afterwards.

## 5. Hard-coded addresses

`grep` over `cape/` (bin, entrypoint, supervisord, templates, conf):

| Where | What |
|---|---|
| `cape/entrypoint.sh:17` | `export GUEST_GATEWAY_IP="....1" GUEST_IP="....10"`: the one `.10` that everything below derives from |
| `cape/templates/tt-guest.xml:13` and `cape/bin/start-guest-network:17` | the libvirt DHCP range is `${GUEST_IP}` to `${GUEST_IP}` (a single address, `.10`) |
| `cape/supervisord.conf:58` | `finish-run` gets `GUEST_AGENT_URL=http://%(ENV_GUEST_IP)s:8000` (always `.10`) |
| `cape/bin/finish-run:10,24` | `DEFAULT_AGENT_URL = "http://192.168.150.10:8000"` |
| `cape/conf/*`, `cape/templates/cape-conf.d/*`, `cape/bin/wait-then-exec` | **no address and no label**: `wait-then-exec registered-guest` reads `Config("kvm").kvm.machines` and checks every machine is defined, so it already handles N guests |

The label `win` appears nowhere in `cape/`. It lives in `docker-compose.yml:75` (`GUEST_LABEL`), `.env.example:33`,
`scripts/build-guest.sh:31` and `scripts/verify-guest.sh:11`.

**DHCP.** `virsh net-dumpxml tt-guest` and `/var/lib/libvirt/dnsmasq/tt-guest.conf`:
`dhcp-range=192.168.150.10,192.168.150.10,255.255.255.0,10m`, `dhcp-lease-max=1`, router and DNS options `.1`.
- Guests started from the snapshot do not use DHCP while they run: after tasks on `win` (.10) and `win2` (.11),
  `virsh net-dhcp-leases tt-guest` was empty. (Consistent with the spec: the in-memory state already has its address.)
  A static `.11` guest therefore needs nothing from the DHCP range, and `win2` ran at `.11` with the range
  `.10` only.
- A cold-booting guest on DHCP (S0d: `win`'s base disk, so every clone before its reconfigure) can only be offered
  `.10`, and only one at a time. I could not cold-boot `win`/`win2` (forbidden), so I probed dnsmasq with two
  synthetic clients from inside the container (raw DHCP packets bound to `tt-guest`, fake MACs `02:00:00:aa:00:01`
  and `...bb:00:02`, both released afterwards, lease list empty again): client A got `OFFER`/`ACK 192.168.150.10`
  (lease expiry +10 min); client B's `DISCOVER` while A held it got **no reply**. (On a first attempt A got no reply
  and B got two offers; two repeats gave the A-then-B result above, so I report that one; I did not find out what the
  first one was.)
- What follows: a clone or a first boot on DHCP collides with a registered guest that sits statically on `.10`
  (it would be offered an address a live guest already has) and a second DHCP boot within 10 minutes of the first gets
  nothing. If the guests keep static addresses `.10 ... .14` and cold boots need DHCP, the range should become a
  separate pool that is not any guest's static address (for example `.100`-`.119`, `dhcp-lease-max` raised or removed),
  and `GUEST_IP` stops meaning "the DHCP address". **This is a recommendation only; I changed no network.** It does not
  have to be removed entirely: the Cirros probe in `verify-cape.sh` needs DHCP to give it `.10` today (check 3), and
  S0d showed `win`'s base disk boots on DHCP.

**`finish-run` against `win2`.**
- Interactive task 201 on `win2` (`options=interactive=1,nohuman=yes`, `timeout=300`). Creating the finish folder
  through win2's agent directly: `md5("cape-201") = c48bcd3038d61eadc8bbaf9d67bd469f`,
  `curl --data-urlencode "dirpath=C:\Windows\Temp\c48bcd30..." http://192.168.150.11:8000/mkdir` at 14:01:06.36
  answered `{"message": "Successfully created directory"} HTTP 200`; `Task #201: Analysis completed successfully` at
  14:01:12, task `completed` 14:01:13 (it had run 29 s of 300), then `reported` 14:01:22. So the mechanism works on
  `win2` unchanged, and ended the run about 6 s after the folder appeared.
- The real `finish-run` (`POST http://cape:8001/tasks/205/finish`, task 205 interactive on `win2`, `.11`, short
  timeout, `win2` temporarily registered again): `{"error": "the guest agent is unreachable (URLError)"} HTTP 502`,
  log `finish-run: POST /tasks/205/finish -> 502 (the guest agent is unreachable (URLError))`: it tried `.10`. The
  analysis ran to its 90 s timeout. So until `finish-run` takes the guest's name (decision 6), "Stop" only works for
  the guest at `GUEST_IP`.

## 6. Scripts that assume one machine or the label `win` (read only)

`scripts/verify-guest.sh`
- `LABEL=${GUEST_LABEL:-win}` (line 11): all of it is about one label.
- `guest_addresses()` sets `GUEST_IP=<subnet>.10` and `AGENT=http://$GUEST_IP:8000`: the agent check, the facts
  script and `restore_snapshot_and_reach_agent` all go to `.10`.
- `machines_list_has_guest` greps `"$LABEL"` in the whole list: works with two machines, but also with a registration
  that no longer has the guest in a section.
- `submit_sample` sends `machine=$LABEL`; `cleanup()` destroys only `$LABEL`; check 12 asserts only `$LABEL`
  survives the container recreate.
- It never touches `kvm.conf.d`, so with `guests.conf` listing `win,win2` it works unchanged (as long as `GUEST_LABEL`
  names one of them and the guest answers at `.10`). Passed here with `win.conf` only.
- `resultserver_bound` checks `192.168.150.1:2042`: fine for any number of guests.

`scripts/verify-cape.sh`
- `REGISTRATION_DIR` / `stash_other_registrations`: moves **every** `*.conf` in `kvm.conf.d` (so also `guests.conf`)
  to `kvm.conf.d.verify-cape` and back with `mv`; one registered machine at a time is assumed by design (comment at
  line 143) and by the probe being the only machine.
- The probe is registered at `GUEST_IP=<subnet>.10` and expects `ip=.10/24` (check 3), the rooter rule
  `-s .10/32` (check 4) and a DHCP lease of `.10` (Cirros uses DHCP). Any DHCP range change must still offer `.10`
  to the probe, or the script changes with it.
- `scripts/tests/test_verify_guest.sh` and `test_verify_cape.sh` have fixtures with `192.168.150.10` and `win`.

**ResultServer binding.** `cuckoo.conf [resultserver]` binds one socket, `192.168.150.1:2042` (listener seen in the
`ss` output above), and each machine's row says `resultserver_ip 192.168.150.1`, `resultserver_port 2042`. Two guests
share that socket; the task is picked by the connection's source IP, so nothing needs configuring per guest as long
as the IPs differ. `cuckoo.py` also has a `multiworker` mode (one port and process per guest, `base_port + index`,
`SingleVMResultServerWorker`); not needed while one task runs at a time and not tried.

## What decisions 5, 6, 7 (and 15) must change

**Decision 5**
- "Two machines sharing one IP is the part CAPE ... might not tolerate": CAPE **tolerates it silently** (accepts, no
  warning), which is worse; uniqueness must be enforced by the control service (and the IP assigned from a free list).
  Distinct addresses are confirmed to work end to end.
- "One registration: a single `guests.conf`": confirmed, with the format above. Add: the control service owns the
  whole directory, writes `guests.conf` atomically and **removes every other `*.conf`** (adoption of `win` must delete
  `win.conf`, or rename it to something not ending in `.conf`), because the last file in sorted order decides
  `machines`.
- Order of operations: define the domain, then register; unregister (rewrite `guests.conf`, restart `cape`) **before**
  `virsh undefine`, else `cape` never starts (silent wait, `supervisorctl` still says RUNNING, the API still accepts
  tasks that stay pending). The check after a restart should be `machines/list` (the number of machines), not
  `supervisorctl status`.
- Do not use CAPE's machine `id` anywhere; it changes at every `cape` start.
- Networking: the DHCP range `.10`-`.10` with `lease-max=1` only serves one cold-booting guest at a time and offers
  an address that a registered guest owns. Widen it into a separate pool (recommendation, untested), keep it for
  clones and first boots; guests restored from a snapshot do not use it.

**Decision 6**
- `machine` must always be sent: omitted alternates between the guests (least recently used first). The default
  guest comes from the backend, not from CAPE.
- A `machine` CAPE does not know returns HTTP 200 with `{"error": true, "error_value": "Machine '...' does not exist.
  Available: ..."}`; the backend maps `error` to its 409.
- `finish-run` taking the guest's name: confirmed necessary (502 against `win2`), and confirmed sufficient to design
  for: the agent call (`POST /mkdir`, `dirpath=C:\Windows\Temp\<md5("cape-<task id>")>`) works on `win2`'s `.11` unchanged
  and ended the analysis in about 6 s. Its `GUEST_AGENT_URL` default and `supervisord.conf:58` go away.

**Decision 7**
- The claim is right in effect and imprecise in mechanism: a graceful `supervisorctl restart cape` powers the running
  guest off **in the stop** (`Shutting down machine 'win2'`, `reason=destroyed` 0.2 s after SIGTERM), a crash is
  handled in the **start** (`reason=destroyed` 2 s after the respawn), and in both the task becomes `failed_analysis`
  at the next start with no report and no callback. Rewrite the sentence; the exclusion rule itself is justified.
- Queued tasks are lost too: a task already queued (`pending`) for a guest that a registration removes is failed at the
  next start ("Failing unserviceable task"); the exclusion therefore also has to cover *pending* analyses, as it
  already says ("queued, starting or running").
- A restart leaves the sniffer's `tcpdump` running; if a restart during an analysis can ever happen (a crash,
  an operator), something should clean up `tcpdump` (not part of S0b).
- Narrowing the exclusion to the register step (the "possible refinement") is plausible, since the restart is the
  only operation seen here that harms a running analysis, but it was not tested with a build running.

**Decision 15 (from S0d, now with S0b's side)**: the reconfigure step waits for the agent at the address the source
booted at; with the DHCP range `.10` only, a clone of `win` will always be at `.10` and a clone of `win2` at `.11`
(static), so cloning two guests at once collides, and the DHCP pool above removes the `.10` special case.

## Restore and proof the original guest works

- `win.conf` restored from the byte copy (`sha256 a93d08596bf387b2e3571218284376fc4df41c1029458c2d0f6cbd3773871a5e`,
  same as before; owner root, mode 644, mtime reset to 2026-10-13 02:28). `kvm.conf.d` holds only `win.conf`; no
  `guests.conf`; no `reporting.conf.d/callback.conf` (that directory did not exist before and is gone again after
  `make verify-guest` recreated the container); `tt-callback` removed; no `tcpdump` left; `win` and `win2` shut off;
  `machines/list` lists only `win`.
- `docker compose exec cape virsh dumpxml win` and `win2` differ from the backups **only** in the overlay path
  (`win.1792021253` -> a newer `win.<n>`, `win2.1792071621` -> a newer `win2.<n>`): every CAPE task reverts the
  snapshot and replaces the overlay, so no run can leave that file as it was. `snapshot-list win` and `win2` are
  identical to the backups (`tartarus-clean`). sha256 of `win.qcow2` (`29d04a0b...`), `win-clean.mem` (`104888b9...`),
  `win_VARS.fd` (`39e3de79...`) and both `tpm2-00.permall` match the values taken before; `win2`'s base disk, memory
  file and nvram have no earlier hashes to compare (S0d did not record them), only unchanged sizes and mtimes for the
  first two; `win2_VARS.fd`'s mtime moved 13:40 -> 14:03 (libvirt rewrites the nvram when a domain starts or stops).
- `make verify-guest` after the restore, run twice (once after the main work, once after the final
  `finish-run` experiment and a second restore). Result both times, verbatim counts:
  **12 `[ OK ]`, 0 `[FAIL]`**: snapshot exists, registration lists `win`, resultserver listens on
  `192.168.150.1:2042`, snapshot restores and the agent answers at `192.168.150.10:8000`, benign.exe built, task
  accepted (204, then 206), runs to `reported`, live `.bson` logs, `report.json`, INetSim name resolution in the
  report, callback (`CALLBACK {"task_id": 206}`), and the recreate-persistence check.
- Tasks created by this spike remain in CAPE: 194-206 (194, 195, 196, 197, 201, 202, 203, 204, 205, 206 `reported`;
  198, 199, 200 `failed_analysis`).

## Could not verify

- Two tasks running at once on two guests (kept to one at a time): the effect of omitted `machine` with one guest busy
  is code reading only (`find_machine_to_service_task` returns the other free machine).
- A cold boot of `win` or `win2` under this registration (not allowed), so the DHCP findings come from a synthetic
  client, not from a real guest, and the proposed DHCP pool was not applied or tested.
- Whether a pending task for a **remaining** machine survives a restart that removes another one.
- An analysis with two machines sharing one IP (not run on purpose); everything under 4 beyond "accepted" is from code.
- A build or a clone running while an analysis is in progress, and `multiworker` mode.
- That the `callback`, `INetSim` and screenshots behave the same for `win2` under `route=internet` (only
  `inetsim` was run).
- The first anomaly of the DHCP probe (see 5) was not explained.
- `win2`'s base-disk, memory-file and nvram hashes before the work (no baseline), so "unchanged" rests on sizes
  and mtimes for the first two.
