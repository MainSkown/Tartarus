#!/usr/bin/env bash
# Scans the real Windows ISO with the media scanner in a throwaway container (never the running
# `cape`): ten editions, build 26200, concurrent scans agree, and nothing stays mounted afterwards.
# Needs the ISO in data/iso, the tartarus-cape image and network access for `apt-get install wimtools`
# (the Dockerfile gets the package later); skips cleanly (exit 0) when any of them is missing.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ISO_NAME="Win11_25H2_Polish_x64_v2.iso"
IMAGE="tartarus-cape:latest"

skip() { echo "skip: $1"; exit 0; }
[[ -f "$REPO/data/iso/$ISO_NAME" ]] || skip "data/iso/$ISO_NAME is not there"
command -v docker >/dev/null && docker image inspect "$IMAGE" >/dev/null 2>&1 || skip "docker or the $IMAGE image is not available"

PROBE='
import importlib.util, sys, threading
sys.path.insert(0, "/work/cape")
from pathlib import Path
from guest_engine.media import run_command, scan_media

spec = importlib.util.spec_from_file_location("windows_inspector", "/work/guest/profiles/windows/inspector.py")
windows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(windows)

def scan():
    return scan_media(Path("/data/iso"), {"windows": windows}, run_command)

(entry,) = scan()
print("editions", len(entry["variants"]), "pro", entry["variants"][4]["index"], entry["variants"][4]["edition_id"])
print("build", entry["build"], entry["language"], entry["arch"], entry["profile"], entry["kind"])

results = []
threads = [threading.Thread(target=lambda: results.append(scan())) for _ in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
print("concurrent_identical", all(r == [entry] for r in results) and len(results) == 4)
'

OUTPUT="$(docker run --rm -i --privileged --entrypoint "" \
    -v "$REPO/data/iso:/data/iso:ro" -v "$REPO/cape:/work/cape:ro" -v "$REPO/guest:/work/guest:ro" \
    "$IMAGE" bash -c '
        (apt-get update -qq && apt-get install -y -qq wimtools) >/dev/null 2>&1 || { echo "NO_WIMTOOLS"; exit 0; }
        loops_before=$(losetup -a | wc -l)
        python3 -I -c "$(cat)" 2>&1
        echo "mounts_left $(findmnt -rno TARGET | grep -c "^/run/scan")"
        echo "scan_dirs_left $(ls /run/scan 2>/dev/null | wc -l)"
        echo "loops_leaked $(( $(losetup -a | wc -l) - loops_before ))"
    ' <<<"$PROBE" 2>&1)"

[[ "$OUTPUT" == *NO_WIMTOOLS* ]] && skip "wimtools could not be installed (no network?)"

failures=0
expect() {
    local name=$1 line=$2
    if grep -qxF "$line" <<<"$OUTPUT"; then echo "ok   $name"; else echo "FAIL $name (wanted: $line)"; failures=$((failures + 1)); fi
}

expect test_ten_editions_with_pro_at_index_five "editions 10 pro 5 Professional"
expect test_build_language_and_architecture "build 26200 pl-PL amd64 windows installer"
expect test_concurrent_scans_agree "concurrent_identical True"
expect test_nothing_stays_mounted "mounts_left 0"
expect test_no_mount_point_directories_left "scan_dirs_left 0"
expect test_no_loop_device_leaks "loops_leaked 0"

((failures == 0)) && echo "all tests passed" || echo "$OUTPUT"
exit "$failures"
