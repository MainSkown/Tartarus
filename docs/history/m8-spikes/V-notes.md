# V notes: Volatility3 in the guest control service (M8, resume file)

## Done
- `cape/bin/volatility.py`: the one place the `vol` command line is built (`Volatility.command`), the real runner
  (`run_command`: `cape` user, minimal environment, no stdin, kill on timeout) and the reading of the output
  (rows, banner version, `NO_SYMBOLS`, errors).
- `cape/bin/memory_logic.py`: `MemoryAnalyser.analyse` (probe `windows.info`, then pslist, cmdline, malfind and
  hollowprocesses with `--pid` from `reports/report.json`), `memory/` writer, `delete_dump` with the held-open scan
  of `/proc`, per-task lock, `analyse_response` / `delete_dump_response`.
- `cape/bin/guest-control`: `POST /memory/{id}/analyse`, `DELETE /memory/{id}/dump` (thin).
- `cape/build/volatility3.requirements` + `cape/Dockerfile` (`cape-build` stage). NOT built.
- Tests: `test_volatility.py`, `test_memory_logic.py`, `test_guest_control_memory.py`, `test_volatility_image.py`;
  fixtures in `cape/tests/fixtures/volatility/` (copied from the spike); `Makefile` lint list; `docs/specs/cape-integration.md`.
- Checked on the host against the real wheel (2.28.2, in a throwaway uv env, deleted): the command line is accepted
  (`-q --offline -s <dir> -f <file> -r json windows.malware.malfind --pid 1 2 3`), the banner goes to stderr, a
  non-Windows file fails with rc 1 and the same "requirement was not fulfilled" text as missing symbols, and
  `$HOME/.cache/volatility3/identifier.cache` is written (so `HOME=/home/cape` must be writable).

## Not done / next (needs a real stack and a real dump)
- Build the image (`docker compose build cape`), then `vol --help` as `cape` inside it.
- Put the ISF in `/var/lib/libvirt/tartarus/symbols/windows/` (the generator is a separate task) and run a real
  analysis with `memory=1`.
- Prove the list at the end of the final report of this task.
