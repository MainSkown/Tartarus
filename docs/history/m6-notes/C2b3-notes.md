# C2b-3 notes (done / running / next)

Baseline before any change: `pytest -q` in cape/ -> 1240 passed, 1 skipped (13 s).

## Done (test first: the tests were written and seen failing, then the code)
- Items 1-4, the orphaned step processes: `StepControl` and `terminate_group` / `is_step_process` in
  `steps.py`; `step_pid` + `step_path` in `build.json`; `Sequencer.recover_interrupted` stops an orphan;
  `Sequencer.shutdown` / `Engine.shutdown` / `guest-control` signal handler; `tests/conftest.py`
  autouse fixture + `tests/fixtures/leaks.py` + `tests/test_leaks.py`.

- Item 5, media kind: the engine records it on the guest as `guest.media_kind` (`installer` |
  `disk_image`) from the media scan's `kind` at build start (validation refuses a medium with no usable
  kind, field `media.file`), a clone copies its source's. `context.json` carries it as `guest.media_kind`;
  `common.sh media_kind` reads it and falls back to the extension only when the field is absent or null.
- Item 6, registry fields: `Guest.nvram_path`, `display`, `tpm_dir` (default None; `display` is a dict
  like the allow-list in `guest_record.py` already said, not a string), `media_kind`; adoption reads
  `<os><nvram>`; the `define` step records `nvram_path` when the rendered domain has an `<nvram>`.
  `tpm_dir` is never recorded: libvirt's domain XML does not name a swtpm state dir.
- Item 7, `scripts/preflight.sh` checks `GUEST_CONTROL_TOKEN` (shell variable, else `.env`) is >= 32
  characters; it checked no required setting before, so the message style is that of the other checks.

## Running
- nothing

## Next
- Nothing open in this task. For the planner: `supervisord.conf` has no `stopwaitsecs` for guest-control
  (default 10 s); the shutdown needs up to 5 s of grace plus the status hooks.

## Decisions
- `build.json` gets two fields, `step_pid` (the group leader's pid) and `step_path` (the file the step
  executes). The path is recorded because recovery has no profile at hand to look the step up, and the
  pid check must compare against what was really started. Both are cleared when the step ends.
- A killed orphan is matched by `/proc/<pid>/cmdline` containing the step path as one of its arguments
  (a script runs as `<interpreter> <script>`) and by the pid leading its own process group.
- `run_step` reports the pid (`StepControl.on_start`) BEFORE it starts the output reader thread: both
  save `build.json`, and two saves at once collide on the shared `.build.json.tmp` name (seen as an
  unhandled `FileNotFoundError` in the reader thread while writing this).
