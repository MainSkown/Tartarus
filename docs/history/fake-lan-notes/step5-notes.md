# Step 5 notes: lan-sim image, compose service, cape wiring

Started 2026-11-23. Isolation-relevant: the container shares cape's network namespace and parses hostile input.

## Done
1. Heartbeat moved to `<root>/status/alive` (`Layout.alive_file` in cape/guest_engine/lan_session.py, one place; the daemon and
   lan_logic.py follow Layout, daemon.py untouched). Why: the root and `sessions/` are root-owned and read-only for uid 10001,
   `status/` is the daemon's. Check: `cape/tests/test_lan_session.py` (failed first), lan_logic and daemon tests pass.
2. dns_static: `cape/bin/lan_dns.py` (logic) + `cape/bin/lan-dns-static` (script) + `cape/tests/test_lan_dns.py` (28 tests, failed
   first); `fqdn_problem` made public in lan_presets.py; entrypoint `render_inetsim_config` appends the lines and falls back to none.
   Whole cape suite: 3190 passed.

3. `lan-sim/Dockerfile` (two stages, python:3.12-slim by the backend's digest, uv 0.12 by digest in the build stage only, uid/gid 10001,
   `--no-dev` is right: the project has no dev group and tests run through `uv run --with`), `.dockerignore` (`!lan-sim`, excludes tests and
   `.venv`s), dependabot entries for `/lan-sim` (uv, docker). Check: built; import check, uid 10001; backend `test_image_pins.py` passes.
4. Licences: THIRD_PARTY.md and docs/licenses.md (22 packages read from the built image's dist-info), see "impacket" below.

5. docker-compose.yml: `lan-run` tmpfs volume, mounted in cape and lan-sim; service `lan-sim`; cape entrypoint
   `prepare_lan_sim_directory`. Checks: `backend/tests/test_lan_sim_service.py` (12, failed first), `docker compose config -q`,
   `backend/tests/test_image_pins.py`.
6. Standalone smoke (scratchpad/smoke.sh): named tmpfs volume, a root holder runs the real entrypoint function, then the daemon with
   `--read-only --cap-drop ALL --network none`. PASS: running as 10001, heartbeat at status/alive, `docker diff` shows only the mountpoint,
   writes to sessions/ and the root refused (EACCES), rename of status/ refused, /app /opt /tmp read-only, stale heartbeat -> healthcheck
   exit 1, SIGTERM exit 0 in under 1 s, heartbeat removed. (First run showed install needs FOWNER after chown: cape has it.)

7. Real wiring, once (2026-11-23, no analysis running: 27 analyses all `done`, guests `win` and `w10` shut off). `docker compose build cape
   lan-sim && docker compose up -d` recreated only cape and created lan-sim (backend, frontend, postgres, opensearch untouched).
   Evidence (scratchpad snap.sh, baseline taken after the new stack was up and before the session):
   - cape and lan-sim healthy; `/run/lan-sim` is a tmpfs nested inside cape's `/run` tmpfs; modes root 0755, sessions root 0755,
     status 10001 0755 (holds `alive`), logs 10001 0750.
   - `/etc/inetsim/tartarus.conf` ends with 17 `dns_static` lines (three presets), INetSim RUNNING; queries to 192.168.150.1:53:
     fs01.corp.local -> .201, dc01.lab.internal -> .232, nas.home.lan -> .216, unknown.example.com -> .1 (the gateway, as before).
   - `GET /lan/health` ready true, `GET /lan-presets` 3 presets (domain-servers 7 hosts, flat-home 4, small-office 6).
   - `POST /lan/sessions` {step5-check, win, small-office} -> 201. Open: 16 listeners on .200-.205 (445, 389, 3389, 5985, 1433, 22)
     equal to the 16 `guest . host . port` elements of the nft set; iptables has the two `tartarus-lan` ACCEPT rules; 6 local routes proto 77.
   - `DELETE /lan/sessions/step5-check` -> 200. After: ss, `nft list table inet tartarus_guest`, `iptables-save | grep tartarus-lan` and
     `ip route show table local proto 77` identical to the baseline (only `nft list tables` changed its listing order, known from step 0).
   - The live lan-sim (uid 10001) cannot write or unlink anything in sessions/ nor create files in the root; it can read the session file.
   - INetSim stayed RUNNING throughout.
8. Restart caveat checked: `docker compose up -d --force-recreate cape` leaves lan-sim running in the DEAD namespace (NetworkMode still
   `container:<old id>`), healthy by its own heartbeat, and `/lan/health` still says ready true: a false ready. A plain `docker compose up -d`
   afterwards recreates lan-sim and fixes it (checked). Documented in docs/architecture.md. Not fixed in code (see Findings).

## Findings for the planner (not done here)
- **False ready after recreating only cape** (above). A real fix: the daemon writes its network-namespace id (`readlink /proc/self/ns/net`)
  into the heartbeat and `LanSessions._daemon_problem` compares it with its own. Touches daemon.py (another agent's file) and lan_logic.py.
  The scripts that run `compose up -d --wait --force-recreate cape` (verify-guest.sh) or stop cape (verify-cape.sh) leave lan-sim stale too.
- **lan-sim can still connect to cape's own local listeners.** The `tartarus_egress` table rejects its outbound connections to the Docker
  network and the internet (checked: 172.20.0.1:80 and 8.8.8.8:443 refused) but `oifname "lo" accept` lets uid 10001 connect to
  127.0.0.1:8000 (CAPE API, token needed), 172.23.0.2:8002 (control service, token needed) and, by address, guacd on 4822. The daemon never
  initiates a connection, so `meta skuid 10001 ct state new reject` first in the output chain of `guest_engine/egress.py` would close it.
- **A FIFO in status/ would hang the control service.** `lan_session.read_status` opens the daemon-written status file without
  O_NONBLOCK (and follows links, on purpose: tests); a compromised daemon could `mkfifo status/<key>.json`. By reading, not exercised.
- `install -d -o 10001 ... ` in the entrypoint needs FOWNER after the chown (cape has it; a holder container without it failed).

## impacket and the GPL (facts for the project owner; nothing decided)
The text is the license file inside the installed 0.13.1 dist-info, read from the built image. It is "a slightly modified version of the
Apache Software License" 1.1 (only "Apache" -> "Impacket" and "Apache Software Foundation" -> "Fortra"), plus separate notices for
pysmb (zlib-style), Isaac Boukris (MIT), recomsvc, Marc Horowitz (BSD) and MIT (krb5).
Clauses that could matter:
1. Source redistribution keeps the copyright notice, conditions and disclaimer; binary redistribution reproduces them in the documentation.
2. Clause 3 (acknowledgment, advertising-style): end-user documentation included with a redistribution, if any, "must include" the line
   "This product includes software developed by SecureAuth Corporation ... and Fortra ...", or it may appear in the software itself.
3. Clause 4: the names "Impacket", "SecureAuth Corporation" and "Fortra" may not be used to endorse or promote products derived from it
   without written permission.
4. Clause 5: products derived from it may not be called "Impacket" or have it in their name without permission of Fortra.
Why it may matter for GPL-3.0-only: GPL-3.0 section 10 forbids imposing further restrictions on recipients. The FSF is understood to class
the Apache 1.1 license as GPL-incompatible for such clauses (I could not re-fetch the FSF page: rate limited; this is from memory). I am
not a lawyer and this is not a conclusion.
The facts about the combination: `lan-sim` is one Python process. Its own code (GPL-3.0-only like the project) imports impacket directly
(`ntlm.py`, `spnego`, `nt_errors`, `crypto`, `dcerpc.v5.srvs`/`scmr`/`dtypes` in the SMB services); it does not copy or fork impacket.
The container is therefore not a separate program that merely sits next to impacket: a GPL module and impacket run together in one
process. What Tartarus distributes today is source only (the Dockerfile fetches impacket from PyPI on the user's machine; no image is
published), so nothing of impacket is conveyed by the repository; the question becomes live if an image is ever published, or if one
reads the combination as already problematic.
Options:
- A. Keep as is: source-only, users build locally, THIRD_PARTY.md says "license compatibility under review". Decide before any image is published.
- B. Add a GPL-3.0 section 7 "additional permission" (an exception, like the OpenSSL one) to lan-sim's own files, allowing the combination with
  impacket. Only the copyright holder can do it, it is cheap, and impacket's own acknowledgment and naming clauses must still be met.
- C. Relicense lan-sim's own code (and the one shared file `lan_session.py`, which is stdlib only) under a permissive license that fits Apache 1.1.
- D. Replace the impacket parts we use (NTLM and SPNEGO structures, SMB2 and DCE/RPC structures, a few crypto helpers). Large for SMB.
- E. Ask the project owner, and optionally Fortra for permission or a clarification; a lawyer if the image will be distributed.
Other lan-sim dependencies are fine under GPL-3.0-only by their declared licenses: ldap3 LGPL-3.0-or-later, asyncssh EPL-2.0 OR
GPL-2.0-or-later (headers name the secondary license), the rest BSD/MIT/ISC/Apache-2.0/PSF.

## Running
(nothing)

## Next
- Step 6 onward. Windows guest reaching a fake host is Step 12 (untested here: no guest was started).
