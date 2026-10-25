# G2: cape container privileges and secrets (F1, F4, F6, F7, F11, F12, F13 of C2; F3, F9 of C3)

Status: PAUSED by the user after the first image build, BEFORE any change was applied to the running stack. Nothing committed.

Rollback: the working tree was clean at the start (git HEAD 3030b8a), so `git diff` shows exactly the G2 edits and
`git show HEAD:docker-compose.yml` / `HEAD:cape/Dockerfile` / `HEAD:cape/supervisord.conf` / `HEAD:cape/entrypoint.sh`
are the original files. Original cape service had `privileged: true`, `devices: [/dev/kvm:/dev/kvm]`, no cap_add, no security_opt.

Initial state: stack healthy; `virsh list --all` in the container: lab1, w10-q, win2 shut off.
Baseline: `id cape` = uid=999(cape) gid=995(cape) groups=995(cape),106(libvirt),107(kvm),993(suricata);
container `suricata` gid 993 == host `disk` gid 993; host /dev/nvme0n1p2 is root:disk 0660.

## Log
- Done: read C2 F1/F4/F6/F7/F11/F12/F13, C3 F3/F9, G1 notes, Dockerfile/entrypoint/supervisord/compose.
- Baseline proven vulnerable: `docker exec tartarus-cape runuser -u cape -- test -r/-w /dev/nvme0n1p2` -> READABLE, WRITABLE.
- Baseline analysis (lab1, inetsim): done, 779 events, network dns/http rows present (script `<scratchpad>/analyse.py GUEST ROUTE`).
- CYCLE 1 (Dockerfile + web settings; steps 1, 2, 4, 5/F12, 3/F13 healthcheck): tests first in
  cape/tests/test_image_hardening.py (red: 5 fail) and cape/tests/test_web_settings.py (red: 6 fail), then
  cape/Dockerfile, cape/web/local_settings.py, cape/web/tartarus_urls.py (green).

## PAUSE CHECKPOINT (user requested)

DONE and verified: nothing on the live stack. Steps 1 to 7 are not applied or proven yet.
Evidence gathered (baseline, unchanged stack): `cape` reads AND writes /dev/nvme0n1p2 (container group suricata gid 993 ==
host disk gid 993); `id cape` = groups cape,libvirt,kvm,suricata; sudoers.d/tcpdump `cape ALL=NOPASSWD: /usr/bin/tcpdump`;
analysis lab1/inetsim = done, 779 events, dns/http rows (so the check script works).

IN PROGRESS: CYCLE 1 = steps 1 (group), 2 (tcpdump setcap), 4 (web settings), 5/F12 (root-owned CAPE tree), F13 (healthcheck).
Written test-first (red then green: `cd cape && uv run --no-project --with pytest pytest -q tests/test_image_hardening.py tests/test_web_settings.py`
-> 13 passed). The full cape suite was NOT re-run after the edits. The image was built (`docker compose build cape`, exit 0) but
NOT deployed and NOT verified.

Image tags: the running container still uses the OLD verified image 912bce88f278 (= `tartarus-cape:latest`, restored by
`docker tag 912bce88f278 tartarus-cape:latest`). The new, unverified image is `tartarus-cape:g2-cycle1` (b45d4743b35e).
Rebuilding (`docker compose up -d --build cape`) is cache-warm now.

Working tree (git status --short; HEAD 3030b8a otherwise clean):
- M cape/Dockerfile: sudoers lines removed; CAPE tree COPY without --chown (root-owned); `gpasswd -d cape suricata`;
  chgrp cape + chmod 0750 + setcap cap_net_raw,cap_net_admin=eip on /usr/bin/tcpdump; install -d -o cape for storage, storage/analyses,
  log, /var/lib/cape-web; empty cape-owned data/yara/index_memory.yarc; event_logs.py and cape/conf COPY without --chown;
  `COPY cape/web/ /opt/CAPEv2/web/web/` and a build-time secret_key.py (settings.py would write it, a root tree refuses); healthcheck
  feeds the token to `curl -K -` through printf (builtin) instead of `-H` on the command line.
- ?? cape/web/local_settings.py (DEBUG False, ALLOWED_HOSTS cape/cape-internal/localhost/127.0.0.1/$CAPE_INTERNAL_IP, ROOT_URLCONF
  web.tartarus_urls, siteauth.sqlite moved to /var/lib/cape-web)
- ?? cape/web/tartarus_urls.py (apiv2 only)
- ?? cape/tests/test_image_hardening.py, cape/tests/test_web_settings.py
- ?? docs/plans/m11-notes/G2-notes.md (this file)
Not yet edited: supervisord.conf, entrypoint.sh, docker-compose.yml, cape/bin/*, scripts/*, Makefile.

Stack state at the pause: all five containers healthy; `nft list tables` shows `inet tartarus_guest` and `bridge tartarus_guest`;
`virsh list --all` (in the container): lab1, w10-q, win2 shut off; no analyses or guests of mine left (analysis 492 was deleted).

Known risks to check on resume (cycle 1):
- F12 needs an empirical pass: after deploy look for PermissionError / "Permission denied" in `docker logs tartarus-cape`,
  in one real analysis AND its processing; add any further cape-writable path to the Dockerfile `install` line AND to
  test_cape_owns_only_what_it_writes_while_running. Also check that the rooter's imported files are not cape-writable
  (python -c import of utils/rooter.py, test -w as cape on each module and its directory).
- ALLOWED_HOSTS: verify-isolation's `cape-web` control probes the container's IP:8000 (Host = that IP, listed via CAPE_INTERNAL_IP);
  the backend uses Host `cape`; the healthcheck 127.0.0.1.
- tcpdump: with file capabilities, `no-new-privileges` would DISABLE them; do not set it in step 6. The bounding set must keep
  NET_RAW and NET_ADMIN once `privileged` is replaced.
- DEBUG False: `GET /submit/` and `/` must answer 404, `/apiv2/cuckoo/status/` 200 with the token, 401 without.
- Step 2 proof: a real analysis must still yield dump.pcap and DNS/HTTP rows in the network view (analyse.py prints them).

## NEXT steps (in order) and exact resume commands
1. `cd cape && uv run --no-project --with pytest pytest -q` (whole suite) and `make lint`.
2. `docker compose up -d --build cape` (never `down`); wait healthy; then:
   - `docker exec -u cape tartarus-cape sh -c 'test -r /dev/nvme0n1p2'` must fail; `docker exec tartarus-cape id cape` has no suricata;
     `supervisorctl status` all RUNNING; `getcap /usr/bin/tcpdump`; `ls /etc/sudoers.d`.
   - `docker exec tartarus-cape curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/submit/` -> 404; `docker top tartarus-cape`
     shows no token; `docker inspect --format '{{json .State.Health.Log}}' tartarus-cape`.
   - `make verify-isolation GUESTS="lab1 w10-q"`, then `python3 -I <scratchpad>/analyse.py lab1 inetsim`
     (scratchpad = /tmp/claude-1000/-home-mainskown-Pulpit-Coding-Tartarus/fd294e31-e4f8-404a-abc0-7c8ec6a3339d/scratchpad; it submits benign.exe + random bytes, waits, prints events/network, deletes the analysis).
   - If anything fails: `docker tag 912bce88f278 tartarus-cape:latest` is the old image (HEAD); revert the offending step only.
3. Step 3 (secrets per program): test first (cape/tests: parse cape/supervisord.conf, assert only the listed programs get CAPE_DB_PASSWORD /
   CAPE_API_TOKEN / GUEST_CONTROL_TOKEN; cross-check against the secret names in the compose cape environment), a wrapper script
   (cape/bin/ ... unsets every known secret except `--keep NAME`s, then execs) prefixed to every program's command. Planned keeps:
   guest-control {GUEST_CONTROL_TOKEN, CAPE_API_TOKEN}; cape, cape-processor, cape-web {CAPE_DB_PASSWORD}; api-token {CAPE_API_TOKEN,
   CAPE_DB_PASSWORD}; everything else none (confirm the rooter needs no DB password: cuckoo.conf interpolates CAPE_DB_* when Config loads).
   Prove with /proc/<pid>/environ variable NAMES per program.
4. Step 5 remainder: F11 memory service (cape/bin/memory_logic.py: O_NOFOLLOW / dir_fd / chown follow_symlinks=False, test in
   cape/tests/test_guest_control_memory.py or test_memory_logic.py first).
5. Step 6 (drop `privileged: true`): iterate cap_add / devices / security_opt empirically; revert to privileged if it cannot run (acceptable
   outcome, record the exact failure). Extend scripts/smoke.sh `only-cape-privileged` accordingly. Optionally add scripts/verify-cape-hardening.sh.
6. Step 7: verify-isolation, `make verify-wizard SAMPLE=<benign.exe>`, two real analyses (lab1, w10-q), `make test-cape test-scripts smoke lint`;
   guests shut off; delete `tartarus-cape:g2-cycle1` if unused.

## RESUME LOG (2026-10-25)

- Found after the pause: backend, frontend, opensearch were Exited (stopped ~3 h earlier, the user's machine was restarted/idle); postgres+cape
  came back with my `docker compose up -d --build cape`. Started the rest with `docker compose up -d` (no down): all 5 healthy.
- The scratchpad of the previous session was wiped: recreated sample/benign.exe (built from guest/profiles/windows/selftest/benign.c with the
  cape container's mingw: `docker exec -i tartarus-cape sh -c 'x86_64-w64-mingw32-gcc -O2 -s -x c - -o /tmp/benign.exe -lws2_32' < benign.c`)
  and analyse.py in the current scratchpad (…/fd294e31-…/scratchpad/{analyse.py,sample/benign.exe}).
- Full cape suite 2152 passed; `make lint` green (after fixing test_event_logs.py, which asserted `COPY --chown=cape:cape` for event_logs.py,
  and long lines in the new tests).
- CYCLE 1 deployed (`docker compose up -d --build cape`). Two real problems found empirically and fixed test-first:
  1. CAPE's startup `create_structure()` must create `data/feeds` -> cape-owned dir added (Dockerfile + test). `cape` was FATAL before.
  2. CAPE's startup `check_tcpdump_permissions()` wants the user in group `pcap` (else it prints "Pcap generation wan't work…"). Using the
     image's `pcap` group (gid 994 = host `clock` group) would be a gid collision, so `groupmod --gid 64010 pcap`, cape joins it, tcpdump
     is `root:pcap 0750` with `cap_net_raw,cap_net_admin=eip` (test: test_tcpdump_runs_for_the_pcap_group…, test_the_pcap_group_has_a_gid…).
- Verified on the deployed cycle 1 (no guest needed):
  - `id cape` = cape,libvirt,kvm,pcap(64010) (no suricata); `docker exec -u cape tartarus-cape test -r /dev/nvme0n1p2` -> not readable (STEP 1 OK).
  - `getcap /usr/bin/tcpdump` = cap_net_admin,cap_net_raw=eip; `ls /etc/sudoers.d` = README only (STEP 2 install OK; the PCAP proof needs a guest).
  - from inside: GET /submit/ 404, / 404, /apiv2/cuckoo/status/ no token 401, with token 200 (STEP 4 OK, DEBUG False).
  - `supervisorctl status`: everything RUNNING (api-token and guest-network exit by design); no "permission denied" in docker logs.
  - healthcheck passes (container healthy) with the token fed through `curl -K -` (F13).
- BLOCKER (host, not the code): the first real analysis FAILED with `Unable to open /dev/net/tun, is tun module loaded?: No such device`
  (libvirt cannot create the guest's tap). The host runs kernel 7.2.10-arch1-1 but /lib/modules only has 7.2.11-arch1-1 (pacman upgraded it
  underneath the running kernel), `lsmod` has no `tun`, and `python3 -c os.open('/dev/net/tun')` on the HOST fails with ENODEV. `sudo` needs
  a password, so I cannot load it. NO guest can start until the host is rebooted into 7.2.11 (or tun is loaded). CAPE has also marked
  w10-q dead in its pool: after the host is fixed run `docker exec tartarus-cape supervisorctl restart cape`.
  => verify-isolation, any analysis, verify-wizard and step 6 (capabilities/devices) CANNOT be verified until then.
- STEP 3 DONE (deployed, healthy): test first (cape/tests/test_secret_scoping.py: 22 tests, red 20 then green), then cape/bin/keep-secrets
  (unsets every secret not named; refuses unknown names / missing `--`), and every `command=` in cape/supervisord.conf starts with it:
  guest-control keeps CAPE_API_TOKEN+GUEST_CONTROL_TOKEN, cape/cape-processor/cape-web keep CAPE_DB_PASSWORD, api-token keeps
  CAPE_API_TOKEN+CAPE_DB_PASSWORD, everything else (virtlogd, libvirtd, guest-network, rooter, inetsim, guacd, suricata, share-storage) none.
  Evidence (/proc/<pid>/environ NAMES in the live container): guacd, libvirtd, virtlogd, rooter, suricata, inetsim, share-storage = none;
  guest-control = CAPE_API_TOKEN,GUEST_CONTROL_TOKEN; cuckoo.py = CAPE_DB_PASSWORD; supervisord itself = all three (root, unreadable by cape).
  gunicorn/process.py show an empty environ (setproctitle rewrites that memory), so for those two the proof is the wrapper test +
  `GET /apiv2/tasks/list/` 200 (the DB works) and the rooter imports fine without the DB variables. Cross-check test: the wrapper's secret
  list == the TOKEN/PASSWORD names of the compose cape environment. Not yet proven end to end (needs a guest): a processed analysis.
- STEP 5/F11 DONE (deployed): memory_logic.py works on directory descriptors (O_NOFOLLOW from the storage chain, mkdirat/unlinkat/rmtree dir_fd,
  O_EXCL|O_NOFOLLOW file creation, fchown/fchmod on fds). 5 regression tests added first (red on the old code), 2 coupled tests moved to
  the new mechanism (os.fchown, os.open order). Live check as root in the container: results end up uid 999 mode 644; an analysis folder
  swapped for a symlink is refused and the victim directory stays untouched.
- STEP 5/F12 DONE (root-owned CAPE tree, deployed; cape/cape-web/cape-processor start, API 200). Open: a processed analysis end to end.
- Added scripts/verify-cape-hardening.sh + `make verify-cape-hardening` (no guest needed): 6 checks green on the deployed stack
  (host block devices closed to cape, no sudo rule, tcpdump caps + 0750, per-program secrets, web API-only 404/401, rooter's 92 imported
  files/dirs not writable by cape). Negative proof: an extra `env -i CAPE_DB_PASSWORD=x sleep 30` made the secrets check FAIL.
- `make lint` green, cape suite 2180 passed, `make test-scripts` all passed, `make smoke` (static) no FAIL.

## STEP 6 (drop `privileged: true`): NOT DONE, stack left PRIVILEGED. What was found (a throwaway container and one experiment on the real stack)

Probe (throwaway `docker run --network none --entrypoint bash`, script in the scratchpad `probe-inner.sh`: libvirtd + virtlogd, bridge, nft, iptables,
mknod, /dev/kvm, and a paused KVM domain without NIC), image tartarus-cape, docker default seccomp (the host has no AppArmor):
- privileged: all pass. Default caps + `NET_ADMIN SYS_ADMIN SYS_PTRACE` pass. Removing one at a time:
  without NET_ADMIN: bridge and nft fail; without SYS_ADMIN: libvirt cannot set `trusted.libvirt.security.dac` xattr (and needs a mount namespace);
  without SYS_PTRACE: "Kernel does not provide mount namespace". SYS_NICE, SYS_RESOURCE, IPC_LOCK were NOT needed by the paused domain
  (a real guest with TPM/UEFI/tap might still need SYS_RESOURCE/IPC_LOCK: untested).
- Dropping the default caps one at a time: CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID, SETPCAP, SYS_CHROOT, MKNOD are needed (domain fails);
  FSETID, AUDIT_WRITE, SETFCAP, NET_RAW(!), KILL, NET_BIND_SERVICE did not matter to the probe, but keep NET_RAW (tcpdump's file capability must be
  inside the bounding set or exec fails), KILL (root stopping cape-owned programs) and NET_BIND_SERVICE (INetSim ports < 1024).
- Candidate that boots everything but one thing: cap_drop ALL; cap_add CHOWN DAC_OVERRIDE FOWNER KILL SETGID SETUID SETPCAP SYS_CHROOT MKNOD NET_RAW
  NET_BIND_SERVICE NET_ADMIN SYS_ADMIN SYS_PTRACE (+ maybe SYS_RESOURCE IPC_LOCK SYS_NICE); devices /dev/kvm /dev/net/tun /dev/vhost-net;
  device_cgroup_rules `b 7:* rmw`, `c 10:237 rmw` (loop devices for the ISO scan); NO security_opt; NO no-new-privileges.
  Experiment on the real stack with an override file (`docker compose -f docker-compose.yml -f <scratchpad>/override-caps.yml up -d cape`, then
  restored with plain `docker compose up -d cape`; privileged=true confirmed): all programs start, nft tables and the hook load, BUT
  `start-guest-network` fails: `cannot write to '/proc/sys/net/ipv6/conf/tt-guest/disable_ipv6': Read-only file system` (libvirt writes that
  sysctl for every bridge it creates; Docker mounts /proc/sys read-only for a non-privileged container) -> container unhealthy, no guest network.
- Why it was not pushed further: (1) the only ways to make that write work are `security_opt: systempaths=unconfined` (a root process can then write
  host-wide sysctls such as kernel.core_pattern, i.e. host code execution: no gain over privileged for that class) or a mount dance in the entrypoint
  (bind /proc/sys/net rw, then /proc/sys ro) that needs SYS_ADMIN anyway; and SYS_ADMIN (needed by libvirt's mount namespace + xattr; `qemu.conf`
  `namespaces = []` + `remember_owner = 0` might remove that need, untested) already lets a root process remount /proc/sys rw. (2) Nothing that needs
  a tap device or a started guest could be verified because the host lacks the tun module (BLOCKER above). A broken stack is not acceptable, so
  `privileged: true` stays.
- RESIDUAL RISK of staying privileged: a `cape`-user code execution no longer reaches the host disks (gid collision gone, step 1), nor root via sudo
  (step 2), nor the other secrets (step 3), nor root-run code (F12), but a root-in-container compromise (guest-control, libvirtd, a QEMU escape landing as
  libvirt-qemu then escalating) still has all host devices and capabilities. With the capability candidate above the host disks/SYS_MODULE/SYS_RAWIO would be
  gone but core_pattern-style escapes via SYS_ADMIN would remain, so the gain is partial. Worth revisiting after trying `namespaces = []`,
  `remember_owner = 0` (to drop SYS_ADMIN) and a rw /proc/sys/net only.

## STATE AT THE END OF THIS SESSION
- Deployed and healthy: steps 1, 2 (install part), 3, 4, 5 (F11, F12), F13. Stack: 5 containers healthy, cape privileged, both tartarus_guest nft tables,
  lab1, w10-q, win2 shut off, no analyses or guests of mine left (the failed analysis 493 was deleted by analyse.py).
- NOT VERIFIED because the host cannot start a guest (tun module missing, kernel 7.2.10 running with only 7.2.11 modules installed; needs a reboot):
  `make verify-isolation GUESTS="lab1 w10-q"`, a real analysis on lab1 and w10-q (done + events + network view with a PCAP: the proof of step 2's
  setcap tcpdump and of the root-owned CAPE tree during processing/reporting), `make verify-wizard`, `make e2e`.
- RESUME after the host is rebooted (or `modprobe tun` as root): `docker exec tartarus-cape supervisorctl restart cape` if `machines/list` is empty;
  `make verify-cape-hardening`; `make verify-isolation GUESTS="lab1 w10-q"`; `python3 -I <scratchpad>/analyse.py lab1 inetsim` and `... w10-q inetsim`
  (watch `docker logs tartarus-cape | grep -i "permission denied"` and /opt/CAPEv2/log for more cape-writable paths; the DNS rows and `network` counts prove the pcap);
  `make verify-wizard SAMPLE=<scratchpad>/sample/benign.exe`. If a CAPE path turns out to need writing, add it to the Dockerfile `install` line AND
  test_cape_owns_only_what_it_writes_while_running. If anything fails, revert only that step (git diff shows each).

## FINAL-PROOF STAGE (host rebooted into 7.2.11, guests start)

- supervisorctl all RUNNING; `make verify-cape-hardening` 6/6 OK.
- Real analyses via POST /api/analyses (benign.exe + random tail, route inetsim, options.guest pinned), deleted afterwards:
  lab1 -> 494 done, 747 events, network dns 6 / http 2 / flows 227, dump.pcap 31464 bytes owned by cape (tcpdump file capability + pcap group work);
  w10-q -> 495 done, 692 events, dns 2 (tartarus-selftest.example -> 192.168.150.1) / http 1 / flows 276, dump.pcap 20502 bytes.
  No PermissionError / "permission denied" in `docker logs tartarus-cape` or /opt/CAPEv2/log (the only errors there date from the reboot's postgres lookup).
  So the root-owned CAPE tree needs no further cape-writable path for submit, run, ResultServer, processing and reporting.
- `make verify-isolation GUESTS="lab1 w10-q"`: first run green but only 12 probes: the cape-web control was SKIPPED ("does not answer from the cape
  container either"), because the probe sends `Host: probe` and the web process (ALLOWED_HOSTS now strict, `/` 404) answers a Django 400/404 without
  X-Cuckoo-Version. Fixed: marker is now `Server: gunicorn` (the real service identifies itself even on the refusal; the INetSim catch-all and the
  backend cannot answer that), fake in scripts/tests/test_verify_isolation.sh updated; rerun green with 13 probes per scenario, exit 0.
- Found, not fixed: GET /apiv2/ (the API index page) answers 500 since the URL config no longer has the UI's route names its template reverses;
  the backend never calls it. 
- `make verify-wizard SAMPLE=<benign.exe>`: green (clone -> ready -> analysis done on the clone -> clone deleted); its analyses 496/497 deleted.
- `make test-cape` 2180 passed, `make test-scripts` all passed, `make smoke` 0 FAIL, `make lint` exit 0.

## STEP 6 re-attempt (one cycle + one fix, then reverted)
Tried in the real stack: compose `cap_drop ALL` + the candidate caps (CHOWN DAC_OVERRIDE FOWNER KILL SETGID SETUID SETPCAP SYS_CHROOT MKNOD
NET_BIND_SERVICE NET_RAW NET_ADMIN SYS_ADMIN SYS_PTRACE), devices kvm/tun/vhost-net/loop-control, `device_cgroup_rules b 7:* rmw`, and in the
entrypoint (a) bind-mounting /proc/sys/net rw while /proc/sys stays ro (works: net.* writable, kernel.core_pattern still read-only) and (b)
mknod of /dev/loop0..63. Result: container healthy, privileged=false, tt-guest created, nft tables and hook loaded, all programs RUNNING, BUT
every guest start fails: `Unable to set bridge tt-guest port vnet0 isolated to 1: Read-only file system`. libvirt writes
/sys/class/net/tt-guest/brif/<tap>/isolated; the sysfs SUPERBLOCK is read-only (a bind-remount rw of /sys/devices/virtual/net changes only the
bind flag: the mount stays `sysfs ro`), so the only way is `mount -o remount,rw /sys`, which makes /sys/kernel/uevent_helper and friends host-writable,
i.e. the same host-code-execution class as privileged. The alternative (stop libvirt writing it: drop `<port isolated='yes'/>` from every domain
and snapshot XML and set the flag in the qemu hook with `bridge link set dev <tap> isolated on`) is a design change to the isolation, untested here.
=> REVERTED: docker-compose.yml cape block and cape/entrypoint.sh restored byte for byte (compose now differs from HEAD only by the
`restart: "no"` lines someone else changed for the reboot; not mine, untouched). Stack rebuilt privileged: healthy, nft tables present, analysis 500 on lab1 done
(735 events, dns 6, http 2), verify-cape-hardening 6/6, guests shut off, analysis deleted.
Candidate for a later try: hook-set port isolation + the cap set above + the /proc/sys/net dance, then verify-isolation.
