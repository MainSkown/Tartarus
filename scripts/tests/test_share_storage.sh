#!/usr/bin/env bash
# Tests cape/bin/share-storage: CAPE creates uploaded files (dropped files, screenshots, dumps)
# with Python's temporary-file mode 0600, which the backend, running as another user, cannot read.
set -uo pipefail

SHARE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/cape/bin/share-storage"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

failures=0
mode_of() { stat -c '%a' "$1"; }

fresh_storage() {
    rm -rf "$WORK_DIR/analyses"
    mkdir -p "$WORK_DIR/analyses/7/files" "$WORK_DIR/analyses/7/shots" "$WORK_DIR/analyses/7/private"
    printf x >"$WORK_DIR/analyses/7/files/dropped"
    printf x >"$WORK_DIR/analyses/7/shots/0001.jpg"
    printf x >"$WORK_DIR/analyses/7/private/inside"
    chmod 600 "$WORK_DIR/analyses/7/files/dropped" "$WORK_DIR/analyses/7/shots/0001.jpg" "$WORK_DIR/analyses/7/private/inside"
    chmod 700 "$WORK_DIR/analyses/7/private" "$WORK_DIR/analyses/7/files"
}

test_a_private_file_becomes_readable_by_others() {
    fresh_storage
    "$SHARE" --once "$WORK_DIR/analyses" || return 1
    [[ $(mode_of "$WORK_DIR/analyses/7/files/dropped") == 644 ]]
}

test_a_private_directory_can_be_entered_by_others() {
    fresh_storage
    "$SHARE" --once "$WORK_DIR/analyses" || return 1
    [[ $(mode_of "$WORK_DIR/analyses/7/private") == 755 && $(mode_of "$WORK_DIR/analyses/7/private/inside") == 644 ]]
}

test_nobody_gains_write_access() {
    fresh_storage
    "$SHARE" --once "$WORK_DIR/analyses" || return 1
    [[ -z $(find "$WORK_DIR/analyses" -perm /022 | head -1) ]]
}

test_files_that_are_already_readable_are_left_alone() {
    fresh_storage
    chmod 640 "$WORK_DIR/analyses/7/shots/0001.jpg"
    printf x >"$WORK_DIR/analyses/7/report"
    chmod 644 "$WORK_DIR/analyses/7/report"
    "$SHARE" --once "$WORK_DIR/analyses" || return 1
    [[ $(mode_of "$WORK_DIR/analyses/7/report") == 644 ]]
}

test_a_missing_storage_directory_is_not_an_error() {
    "$SHARE" --once "$WORK_DIR/does-not-exist"
}

test_an_unknown_argument_prints_usage_and_exits_2() {
    "$SHARE" --bogus >"$WORK_DIR/out" 2>&1
    [[ $? -eq 2 ]] && grep -qi usage "$WORK_DIR/out"
}

for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
