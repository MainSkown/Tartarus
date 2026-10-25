# C3 notes (media scan)

## Done
- Real fixture `cape/tests/fixtures/wiminfo_win11_25h2_pl_x64.txt` (wiminfo of the user's ISO); derived `wiminfo_multilang_two_arch.txt`, `wiminfo_solid_esd_lzms.txt`, `wiminfo_non_windows.txt`.
- `cape/guest_engine/media/`: `errors.py` (Fault table, MediaProblem), `commands.py` (Runner, run_command), `mount.py` (LoopMounter, cleanup_stale_mounts), `inspector.py` (MediaContext, Inspector protocol), `scan.py` (scan_media), `__init__.py`.
- `guest/profiles/windows/inspector.py` (parse_wiminfo, inspect, WIMINFO_FAILURES table).
- Tests: test_media_mount.py (26), test_media_scan.py (16), test_windows_inspector.py (22), helper test_media_support.py; mutation-checked (busy fallback, attach lock, node creation each fail a test).
- Real ISO check in a throwaway container: 0.037 s, ten editions, build 26200, pl-PL; 2 and 6 concurrent scans identical; nothing left mounted; stale cleanup removed a leaked mount.
- `scripts/tests/test_media_real.sh` (4.4 s, skips without ISO, docker, image or network).

## Running
- nothing

## Next
- C2b wires `GuestEngine.media()` to `scan_media(Path("/data/iso"), inspectors_by_profile_id, run_command)`; the control service calls `cleanup_stale_mounts(run_command)` once at start.
- Dockerfile needs `wimtools` (C1).
