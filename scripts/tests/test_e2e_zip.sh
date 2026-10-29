#!/usr/bin/env bash
# Tests scripts/lib/e2e-zip.sh: the checks `make e2e` runs on a submission from a password-protected
# zip (the member list, the submission, the password kept out of every answer and out of the backend
# log, the entry running and the decoy not, the refusals leaving nothing behind). The API is replaced
# by fixtures/fake_zip_api.py; a correct fake must pass every check, and for each way the API can go
# wrong (a "fault" of the fake) the check meant to catch it must fail, saying why.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAKE_API=$REPO/scripts/tests/fixtures/fake_zip_api.py
WORK_DIR="$(mktemp -d)"
SERVER_PID=""
CREATED_IDS=()
trap 'stop_server; rm -rf "$WORK_DIR"' EXIT

cd "$REPO" || exit 1
source "$REPO/scripts/lib/e2e-api.sh"
source "$REPO/scripts/lib/e2e-views.sh"
source "$REPO/scripts/lib/e2e-exports.sh"
source "$REPO/scripts/lib/e2e-zip.sh"
POLL_SECONDS=0.05
ANALYSIS_TIMEOUT=2

# What scripts/e2e.sh supplies to the lib, and the two things that need Docker.
remember() { CREATED_IDS+=("$1"); }
sha256_of() { sha256sum "$1" | cut -d' ' -f1; }
stored_sample_exists() { [[ $(curl -s -o /dev/null -w '%{http_code}' "$BASE/stored/$1") == 200 ]]; }
PAYLOAD_CONTENT=payload-content
DECOY_CONTENT=decoy-content
build_archive_zip() {
    mkdir -p "$(archive_members_dir)"
    printf '%s' "$PAYLOAD_CONTENT" >"$(archive_members_dir)/$ARCHIVE_ENTRY"
    printf '%s' "$DECOY_CONTENT" >"$(archive_members_dir)/$ARCHIVE_DECOY"
    printf 'PK\003\004 %s' "$RANDOM$RANDOM" >"$1"
}
cape_analysis_log() { echo "analysis.log of CAPE task $1: Unable to find any 7z.exe executable"; }
BACKEND_LOG_FILE=$WORK_DIR/backend.log
backend_log() { cat "$BACKEND_LOG_FILE"; }

start_server() { # fault...
    local port tries=0
    port=$(python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
    FAKE_ENTRY_SHA=$(printf '%s' "$PAYLOAD_CONTENT" | sha256sum | cut -d' ' -f1) \
        FAKE_DECOY_SHA=$(printf '%s' "$DECOY_CONTENT" | sha256sum | cut -d' ' -f1) \
        python3 -I "$FAKE_API" "$port" "$ARCHIVE_PASSWORD" "$@" &
    SERVER_PID=$!
    BASE=http://127.0.0.1:$port
    until curl -s -o /dev/null -m 1 "$BASE/calls"; do
        ((++tries > 50)) && { echo "the fake API did not start" >&2; return 1; }
        sleep 0.1
    done
}

stop_server() { [[ -n $SERVER_PID ]] && { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }; SERVER_PID=""; return 0; }

# A request line is in the log, as the submission is in uvicorn's access log; the password is not, unless a test says so.
write_backend_log() { printf 'INFO: "POST /api/analyses HTTP/1.1" 201\nINFO: %s\n' "${1:-nothing else}" >"$BACKEND_LOG_FILE"; }

run_the_flow() { # fault...
    stop_server
    start_server "$@" || return 1
    check_zip_submission >"$WORK_DIR/out" 2>&1
    return 0
}

flow_passes() { ! grep -q '^\[FAIL\]' "$WORK_DIR/out" && grep -q '^\[ OK \].*(z6)' "$WORK_DIR/out"; }

flow_fails_saying() { # fault group words
    run_the_flow "$1" || return 1
    grep -q '^\[FAIL\].*'"$2"'.*'"$3" "$WORK_DIR/out" || { echo "no FAIL of group $2 saying '$3' for '$1':" >&2; cat "$WORK_DIR/out" >&2; return 1; }
}

test_every_check_passes_on_a_correct_api() {
    write_backend_log
    run_the_flow || return 1
    flow_passes || { cat "$WORK_DIR/out" >&2; return 1; }
}

test_every_group_prints_at_least_one_line() {
    write_backend_log
    run_the_flow || return 1
    local group
    for group in z1 z2 z3 z4 z5 z6 z7 z8; do
        grep -q "(${group})" "$WORK_DIR/out" || { echo "no line for ($group)" >&2; return 1; }
    done
}

# --- Z1 ----------------------------------------------------------------------------------------

test_a_listing_of_two_members_is_caught() { write_backend_log; flow_fails_saying two_members z1 "2 members"; }
test_a_wrong_password_reported_ok_is_caught() { write_backend_log; flow_fails_saying wrong_password_is_ok z1 "password_ok"; }
test_a_file_that_is_not_a_zip_but_is_listed_is_caught() { write_backend_log; flow_fails_saying not_a_zip_is_listed z1 "answered 200 (wanted 422)"; }

# --- Z2 ----------------------------------------------------------------------------------------

test_a_password_in_the_create_response_is_caught() { write_backend_log; flow_fails_saying password_in_create z2 "create response.*holds the password"; }
test_a_password_in_the_analysis_is_caught() { write_backend_log; flow_fails_saying password_in_get z2 "GET /api/analyses/[0-9]*.*holds the password"; }
test_a_password_in_the_list_is_caught() { write_backend_log; flow_fails_saying password_in_list z2 "list.*holds the password"; }
test_an_analysis_that_does_not_finish_is_caught() { write_backend_log; flow_fails_saying analysis_fails z2 "ended as 'failed'"; }
test_a_filename_that_is_not_a_zip_is_caught() { write_backend_log; flow_fails_saying filename_not_zip z2 "does not end in .zip"; }
test_a_missing_archive_entry_option_is_caught() { write_backend_log; flow_fails_saying entry_missing_from_options z2 "archive_entry"; }
test_a_package_that_is_not_zip_is_caught() { write_backend_log; flow_fails_saying package_not_zip z2 "package"; }

# --- Z3 ----------------------------------------------------------------------------------------

test_an_entry_that_never_ran_is_caught() { write_backend_log; flow_fails_saying entry_did_not_run z3 "no process-created event for payload.exe"; }
test_a_decoy_that_ran_is_caught() { write_backend_log; flow_fails_saying decoy_ran z3 "other.exe"; }

# --- Z7 ----------------------------------------------------------------------------------------

test_an_entry_hash_that_is_null_is_caught() { write_backend_log; flow_fails_saying entry_sha_null z7 "entry_sha256 is null"; }
test_an_entry_hash_that_is_the_decoys_is_caught() { write_backend_log; flow_fails_saying entry_sha_is_the_decoys z7 "the decoy's hash"; }
test_an_entry_hash_that_is_the_zips_is_caught() { write_backend_log; flow_fails_saying entry_sha_is_the_zips z7 "the zip's hash"; }
test_a_report_that_does_not_record_the_entry_hash_is_caught() { write_backend_log; flow_fails_saying report_without_entry_sha z7 "does not say"; }
test_a_report_that_holds_the_password_is_caught() { write_backend_log; flow_fails_saying report_holds_password z7 "still holds"; }

# --- Z8 ----------------------------------------------------------------------------------------

test_a_zip_without_the_extension_that_does_not_run_is_caught_and_the_evidence_is_shown() {
    write_backend_log
    flow_fails_saying bin_name_fails z8 "ended as 'failed'" || return 1
    grep -q 'analysis.log of CAPE task.*7z.exe' "$WORK_DIR/out" || { echo "no analysis.log excerpt after the failure:" >&2; cat "$WORK_DIR/out" >&2; return 1; }
}

test_a_zip_without_the_extension_that_runs_leaves_no_evidence_lines() {
    write_backend_log
    run_the_flow || return 1
    ! grep -q 'analysis.log of CAPE task' "$WORK_DIR/out"
}

# --- Z4 and Z5 ---------------------------------------------------------------------------------

test_a_wrong_password_that_is_accepted_is_caught() { write_backend_log; flow_fails_saying wrong_password_accepted z4 "answered 201 (wanted 422)"; }
test_a_wrong_password_that_leaves_a_row_is_caught() { write_backend_log; flow_fails_saying wrong_password_adds_a_row z4 "analyses"; }
test_a_wrong_password_that_leaves_the_sample_is_caught() { write_backend_log; flow_fails_saying wrong_password_stores_sample z4 "still stored"; }
test_a_missing_entry_that_is_accepted_is_caught() { write_backend_log; flow_fails_saying missing_entry_accepted z5 "answered 201 (wanted 422)"; }
test_a_refusal_on_the_wrong_field_is_caught() { write_backend_log; flow_fails_saying refusal_on_wrong_field z5 "options.archive_entry"; }

# --- Z6 ----------------------------------------------------------------------------------------

test_a_password_in_the_backend_log_is_caught() {
    write_backend_log "parsed options {'archive_password': '$ARCHIVE_PASSWORD'}"
    run_the_flow || return 1
    grep -q '^\[FAIL\].*(z6).*1 times' "$WORK_DIR/out" || { cat "$WORK_DIR/out" >&2; return 1; }
}

test_a_log_that_does_not_show_the_submission_proves_nothing_and_is_caught() {
    echo "INFO: started" >"$BACKEND_LOG_FILE"
    run_the_flow || return 1
    grep -q '^\[FAIL\].*(z6).*proves nothing' "$WORK_DIR/out" || { cat "$WORK_DIR/out" >&2; return 1; }
}

# --- the builder -------------------------------------------------------------------------------

python_with_pyzipper() {
    local candidate
    for candidate in python3 backend/.venv/bin/python; do
        "$candidate" -I -c 'import pyzipper' 2>/dev/null && { echo "$candidate"; return 0; }
    done
    return 1
}

test_the_builder_writes_an_aes_zip_with_every_member_that_only_the_password_opens() {
    local python
    python=$(python_with_pyzipper) || { echo "skipped: no python with pyzipper on this host" >&2; return 0; }
    mkdir "$WORK_DIR/members"
    printf 'one' >"$WORK_DIR/members/payload.exe"
    printf 'two' >"$WORK_DIR/members/other.exe"
    tar -C "$WORK_DIR/members" -c . | "$python" -I -c "$(cat scripts/lib/aes_zip.py)" "$ARCHIVE_PASSWORD" >"$WORK_DIR/built.zip" || return 1
    "$python" -I - "$WORK_DIR/built.zip" "$ARCHIVE_PASSWORD" <<'PY'
import sys
import pyzipper

with pyzipper.AESZipFile(sys.argv[1]) as archive:
    names = sorted(archive.namelist())
    assert names == ["other.exe", "payload.exe"], names
    assert all(info.flag_bits & 1 for info in archive.infolist()), "a member is not encrypted"
    archive.setpassword(sys.argv[2].encode())
    assert archive.read("payload.exe") == b"one"
    archive.setpassword(b"wrong")
    try:
        archive.read("payload.exe")
    except RuntimeError:
        pass
    else:
        raise AssertionError("a wrong password opened the member")
PY
}

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    stop_server
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
