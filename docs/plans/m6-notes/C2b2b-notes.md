# C2b-2b notes (done / running / next)

## Done (each piece: test written and seen failing, then the code)
- `git mv guest/manifest.sha256 guest/profiles/windows/manifest.sha256`. Its header comment said
  "CAPE's" and "build-guest.sh", which the giveaway scan of test_windows_profile.py flags now that the
  file sits in the profile (seen failing: `manifest.sha256:5: cape`); reworded. The one reference
  (`MANIFEST` in cape/tests/test_windows_profile.py) points at the new place. scripts/verify-guest.sh and
  scripts/tests/* had no reference to the manifest.
- `steps/lib/render_unattend.py` + cape/tests/test_render_unattend.py (33 tests; collection error first).
- `steps/lib/guest_agent.py` (agent client + CLI) + cape/tests/test_guest_build_agent.py (33 tests).
  scripts/tests/fake_guest_agent.py is the fake agent (shared by the pytest file and the bash tests).
- `cape/bin/guest-build` + cape/tests/test_guest_build.py (25 tests).
- Steps `install`, `provision`, `tamper-off`, `defender-on` + `steps/lib/windows.sh`, tested by
  scripts/tests/test_windows_steps.sh (39 tests, fake agent on loopback, virsh and xorriso stubbed).
- scripts/build-guest.sh is a 60-line wrapper; scripts/tests/test_build_guest.sh was rewritten (17 tests).

## Findings that shaped the design
- CAPE's agent `/execute` does NOT return the process exit code (reply: message, status_code, stdout,
  stderr; the command goes through shlex.split, hence slash paths). The exit code of tamper-off.ps1 is
  carried by a driver script that guest_agent.py writes, uploads and runs; it prints `EXITCODE <n>` after
  the target and deletes everything it uploaded (itself included) in a `finally`.
- Every file under guest/profiles/windows/ is scanned by test_windows_profile.py for giveaway words and
  for the values of names.json: the steps read names.json at run time and never spell a name or the
  words (no "virus" in the pause text, no "CAPE" in comments).
- `CAPE_CONTROL_IP` is exported by the entrypoint to supervisord's services only; a `docker compose exec`
  session does not have it. guest-build falls back to the control network alias `cape-control`, which
  resolves inside the container (checked with getent). /usr/local/lib/tartarus is not on PATH, so the
  wrapper runs `python3 -I /usr/local/lib/tartarus/guest-build`.
- The old script waited for the agent with a 5 s curl timeout; the client's probes use 10 s (an
  unreachable guest IP hangs the connect until then).

## Checks run at the end
- `make test-cape`: 1200 passed, 1 skipped. New pytest files: test_render_unattend 35, test_guest_build_agent 33,
  test_guest_build 25.
- scripts/tests: test_windows_steps.sh 41/41, test_build_guest.sh 17/17, test_verify_guest.sh 17/17,
  (2a's) test_generic_steps.sh green.
- shellcheck (docker koalaman/shellcheck:stable, -x -P SCRIPTDIR) clean on the four steps, windows.sh,
  build-guest.sh and both bash tests; ruff check and format clean with cape/pyproject.toml settings.
- Mutation checks (deliberate breaks; about 9 on render_unattend, 10 on guest_agent, 12 on guest-build,
  25 on the steps, those on the steps run against copies of the tree). Survivors found and given tests: world-readable output file left by an earlier
  attempt (chmod), the exit-code reset in the driver, the missing-token message, CR/NUL stripping of the
  saved log, the "already provisioned" branch of install (its message matched the other branch too).
- The real agent (agent.py copied out of the running container with docker cp, run on loopback) answered
  `answers`, `store`, `retrieve`, `exists` through guest_agent.py: the multipart upload parses, a missing
  file is a 404 with no body. `/execute` could not be tried that way (the agent refuses every command but
  `date` from 127.0.0.1) and the PowerShell driver was never run in PowerShell.

## Test seams in the steps (environment, only the tests set them)
INSTALL_GUARD_SECONDS (7200), INSTALL_POLL_SECONDS (15), INSTALL_KEY_PRESSES (20), INSTALL_KEY_INTERVAL (1),
INSTALL_TYPICAL_SECONDS (900), TT_AGENT_SCRIPT (the agent file in the image), PROVISION_AGENT_WAIT_SECONDS (300),
PROVISION_AFTER_CLEANUP_WAIT_SECONDS (60), PROVISION_PROBE_SECONDS (5); scripts/build-guest.sh reads
TARTARUS_ISO_DIR (default data/iso) besides TARTARUS_ENV_FILE.

## Left for the planner (not mine to edit)
- BLOCKER for a real build: the Windows profile is rejected by load_profiles until the clone pipeline's steps
  exist: `no executable step 'copy'` and `'reconfigure'` (C4's). Checked with load_profiles(guest/profiles,
  guest/steps): profiles {} and windows broken. Every step of the build pipeline resolves.
- The Dockerfile copies guest/profiles/, steps/, domain/ and personas/ already; nothing else is needed for
  these steps (guest-build is run as `python3 -I /usr/local/lib/tartarus/guest-build`).
- guest/domain.xml.tpl (old template) is now unused by any script; cape/tests/test_windows_profile.py
  `test_hardware_is_what_the_domain_template_defines` still reads it. Delete both together.
- cleanup.ps1 keeps the provisioning log on the guest (decision 16 says it goes); G1's choice.
- defender-on's pipeline entry has no `desktop: true`, so its PAUSE (exit 10 of defender-on.ps1) would
  show instructions with no desktop. Add `desktop: true` to that entry in profile.json if wanted.
- defender-on.ps1 and the whole tamper-off path are NOT tested on a real guest.
