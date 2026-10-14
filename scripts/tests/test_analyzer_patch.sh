#!/usr/bin/env bash
# Tests cape/patches/skip-packaged-apps.py, the build-time patch that stops CAPE's guest-side analyzer
# from injecting the monitor into Store apps in an interactive analysis. The patch runs against an
# excerpt of the pinned analyzer (fixtures/analyzer-excerpt.py); the image build runs it against the
# real file, where a changed anchor fails the build.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PATCHER="$REPO/cape/patches/skip-packaged-apps.py"
FIXTURE="$REPO/scripts/tests/fixtures/analyzer-excerpt.py"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

failures=0
OUTPUT=""
STATUS=0

run_test() {
    local name=$1
    cp "$FIXTURE" "$WORK_DIR/analyzer.py"
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
}

patch_analyzer() { OUTPUT="$(python3 -I "$PATCHER" "${1:-$WORK_DIR/analyzer.py}" 2>&1)"; STATUS=$?; return "$STATUS"; }

# Drives the patched PipeHandler._handle_process for one announced process and prints "injected" or "skipped".
announce() {
    local image_path=$1 interactive=$2 package=$3
    python3 -I - "$WORK_DIR/analyzer.py" "$image_path" "$interactive" "$package" <<'PY'
import importlib.util
import sys
from types import SimpleNamespace

path, image_path, interactive, package = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("analyzer_under_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.INTERACTIVE_MODE = interactive == "interactive"
module.FakeProcess.filepaths = {4242: image_path}
handler = module.PipeHandler()
handler.analyzer = SimpleNamespace(
    pid=1, ppid=2, process_list=SimpleNamespace(pids=[]), options={}, package_name=package,
    config=SimpleNamespace(category="file", target="sample.exe"), files=SimpleNamespace(files={}),
    SERVICES_PID=None, NUM_INJECTED=0, LASTINJECT_TIME=None,
)
handler._handle_process(b"4242,17")

injected = module.FakeProcess.injected == [4242]
counted = handler.analyzer.NUM_INJECTED == (1 if injected else 0)
cleaned = injected or 4242 not in module.INJECT_LIST
print("injected" if injected else "skipped", "" if counted and cleaned else "BOOKKEEPING-WRONG")
PY
}

NOTEPAD='\Device\HarddiskVolume3\Program Files\WindowsApps\Microsoft.WindowsNotepad_11.2501.31.0_x64__8wekyb3d8bbwe\Notepad\Notepad.exe'

assert_announce() {
    local expected=$1
    shift
    local got
    got="$(announce "$@")"
    [[ $got == "$expected " ]] || { echo "  $*: expected '$expected', got '$got'"; return 1; }
}

test_the_patch_applies_and_leaves_valid_python() {
    patch_analyzer
    [[ $STATUS -eq 0 ]] || { echo "  patcher failed: $OUTPUT"; return 1; }
    python3 -I -m py_compile "$WORK_DIR/analyzer.py" || { echo "  patched file does not compile"; return 1; }
}

test_an_interactive_run_skips_a_store_app() {
    patch_analyzer && assert_announce skipped "$NOTEPAD" interactive modules.packages.exe
}

test_the_store_app_path_match_ignores_case() {
    patch_analyzer && assert_announce skipped '\device\harddiskvolume3\PROGRAM FILES\WINDOWSAPPS\x\App.exe' interactive modules.packages.exe
}

test_an_interactive_run_still_injects_a_classic_program() {
    patch_analyzer && assert_announce injected '\Device\HarddiskVolume3\Windows\System32\cmd.exe' interactive modules.packages.exe
}

test_a_non_interactive_run_still_injects_a_store_app() {
    patch_analyzer && assert_announce injected "$NOTEPAD" automatic modules.packages.exe
}

# The msix package installs the sample as a Store app, so skipping would blind the analysis to it.
test_an_interactive_msix_analysis_still_injects_a_store_app() {
    patch_analyzer && assert_announce injected "$NOTEPAD" interactive modules.packages.msix
}

test_the_patch_fails_when_an_anchor_changed() {
    sed -i 's/if not in_protected_path(filename):/if not in_protected_path(filepath):/' "$WORK_DIR/analyzer.py"
    cp "$WORK_DIR/analyzer.py" "$WORK_DIR/before.py"
    patch_analyzer && { echo "  patcher succeeded on a changed anchor"; return 1; }
    cmp -s "$WORK_DIR/analyzer.py" "$WORK_DIR/before.py" || { echo "  file was modified despite the failure"; return 1; }
    [[ $OUTPUT == *"in_protected_path(filename)"* ]] || { echo "  error does not name the anchor: $OUTPUT"; return 1; }
}

test_the_patch_refuses_a_file_that_is_already_patched() {
    patch_analyzer || { echo "  first application failed: $OUTPUT"; return 1; }
    patch_analyzer && { echo "  patcher applied twice"; return 1; }
    return 0
}

run_test test_the_patch_applies_and_leaves_valid_python
run_test test_an_interactive_run_skips_a_store_app
run_test test_the_store_app_path_match_ignores_case
run_test test_an_interactive_run_still_injects_a_classic_program
run_test test_a_non_interactive_run_still_injects_a_store_app
run_test test_an_interactive_msix_analysis_still_injects_a_store_app
run_test test_the_patch_fails_when_an_anchor_changed
run_test test_the_patch_refuses_a_file_that_is_already_patched

if [[ $failures -ne 0 ]]; then echo "$failures test(s) failed"; exit 1; fi
echo "all passed"
