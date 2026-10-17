# DOCS notes (done / running / next)

Task: make the specs true for M6. Docs only, no commit. Files: backend.md, cape-integration.md, gui.md,
architecture.md, data-model.md, tartarus-v1.md, overview.md, README.md, new guest-profiles.md.

## Done
- Read the plan (Status, decisions 1 to 17), all per-task notes, S0b/S0c/S0d/S0e findings.
- Read the code: cape/guest_engine, cape/bin/guest-control + finish-run, guest/steps, the windows profile,
  backend api/guests.py, guest/*, analyses/*, ws/desktop + desktop/*, compose, entrypoint/supervisord,
  frontend guest pages/composables.
- Written: docs/specs/guest-profiles.md (new); backend.md (modules, health, settings, POST /analyses, finish,
  Guests section with the build job and self-test, guest desktop WS, jobs/paused, config, testing);
  cape-integration.md (container table, kvm.conf, libvirt finding RESOLVED, M0b one-guest finding lifted, backend
  talks to CAPE, the whole wizard section rewritten, interactive desktop + Windows Security); gui.md (header
  popover, routes, Dashboard, Submit dialog, workspace header, Guest VM section, Settings, structure);
  architecture.md; data-model.md (no guest table, options.guest, paused, default guest); tartarus-v1.md (decisions,
  Q1 and Q5, non-goals); overview.md (M3 to M6 rows, next up, after v1, glossary); README.md.
- Link check (scratchpad linkcheck.py): 95 relative links in 10 files, 0 problems.

## Running
- nothing

## Next
- nothing; report to the planner

## Contradictions plan vs code (code wins) and loose ends found
- Header health: plan says "ok when at least one is ready"; code: ok only when ALL guests are ready,
  degraded when some are not, down when none is ready or none exists (backend/app/guest/health.py).
- docker-compose.yml still passes GUEST_LABEL to the backend and .env.example still documents it; the backend
  no longer has a `guest_label` setting (only scripts/build-guest.sh reads it as the CLI's guest name).
- cape/bin/finish-run and its supervisord program still run (fixed to GUEST_IP), unused by the backend,
  which finishes through guest-control POST /tasks/{id}/finish {guest}.
- The profile schema accepts the signals report.child_process and storage.monitor_log; the backend verdict
  (selftest_verdict.SIGNAL_JUDGES) judges only events.process/file/registry, report.present, report.dns_answer
  and fails any other signal id.
- pafish: nothing in the code runs it (`selftest.extras` is parsed and unused); the card shows no pafish summary.
- Wave 5 `make verify-wizard` exists (scripts/verify-wizard.py) but is a ~6 minute clone-based check, not the
  20 minute build-and-clone proof the plan describes.
- resume/restart: the backend docstrings say 409 "when the build is not failed"; the engine accepts resume and
  restart on failed or paused builds, continue on paused only.
- Deleting another guest during a build is still allowed (engine refuses only the guest being built or the
  source of a running clone).
- agent.shutdown `agent-command` and agent.ready.marker are parsed but nothing uses them (snapshot always ACPI).
- The grep gate (test_engine_generic_code.py) covers cape/guest_engine only, not guest/steps, backend/app/guest or
  the frontend; backend selftest_verdict names three defender.* facts and the frontend says "Windows ISO" in two
  empty states.
- GuestCard SYSTEM = profile display name + media.variant; the engine records the variant as the edition INDEX
  ("5"), the screenshot fixtures used a name ("Pro"); a real Pro guest probably reads "Windows 11 5" (not seen on screen).
- GUI: no [REBUILD], no "verified on Windows 11 25H2" text, the delete confirm does not show the size freed.
- tartarus-v1 open questions 10 and 11 left untouched as asked; Q11 (default password Tartarus1!) is now stale
  for wizard builds (random per guest) and still true for the adopted `win`.
- M4's Rules-page review is recorded as pending in the M4 plan; the overview row says so.
- Not verified by me: nothing was run (docs only); every figure about real runs comes from the plan's Status.
