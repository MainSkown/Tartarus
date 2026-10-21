#!/usr/bin/env bash
# Tests how scripts/e2e.sh removes the analyses it (or its browser test) created: an analysis that
# is still queued or running must be cancelled or waited for before the delete, or the delete
# answers 409 and the leftover blocks the next run's "no analysis is active" precondition. The
# analyses API is replaced by fixtures/fake_analyses_api.py.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAKE_API=$REPO/scripts/tests/fixtures/fake_analyses_api.py
SERVER_PID=""
trap 'stop_server' EXIT

cd "$REPO" || exit 1
source "$REPO/scripts/lib/e2e-api.sh"
E2E_POLL_SECONDS=0.05
POLL_SECONDS=0.05
CLEANUP_WAIT_SECONDS=2

start_server() { # id:status[:polls[:sha]]...
    local port tries=0
    port=$(python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
    python3 -I "$FAKE_API" "$port" "$@" &
    SERVER_PID=$!
    BASE=http://127.0.0.1:$port
    until curl -s -o /dev/null -m 1 "$BASE/calls"; do
        ((++tries > 50)) && { echo "the fake API did not start" >&2; return 1; }
        sleep 0.1
    done
}

stop_server() { [[ -n $SERVER_PID ]] && { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }; SERVER_PID=""; return 0; }

calls() { curl -s "$BASE/calls" | python3 -I -c 'import json, sys; print("\n".join(json.load(sys.stdin)))'; }
status_code_of() { curl -s -o /dev/null -w '%{http_code}' "$BASE/api/analyses/$1"; }

test_a_finished_analysis_is_deleted_at_once() {
    start_server 1:done || return 1
    remove_analyses 1 >/dev/null && [[ $(status_code_of 1) == 404 ]]
}

test_a_queued_analysis_is_cancelled_and_then_deleted() {
    start_server 1:queued || return 1
    remove_analyses 1 >/dev/null && [[ $(status_code_of 1) == 404 ]] && calls | grep -q 'POST /api/analyses/1/cancel'
}

test_a_running_analysis_is_waited_for_and_then_deleted() {
    start_server 1:running:5 || return 1
    remove_analyses 1 >/dev/null && [[ $(status_code_of 1) == 404 ]]
}

test_a_running_analysis_is_never_asked_to_cancel() {
    start_server 1:running:3 || return 1
    remove_analyses 1 >/dev/null && [[ $(status_code_of 1) == 404 ]] && ! calls | grep -q cancel
}

test_an_analysis_that_never_ends_gives_up_after_the_bound_and_says_so() {
    start_server 1:running || return 1
    local before=$SECONDS output
    output=$(remove_analyses 1 2>&1)
    local status=$?
    ((status != 0)) && ((SECONDS - before < 6)) && [[ $output == *"analysis 1"* && $output == *running* ]]
}

test_an_analysis_that_is_already_gone_is_not_an_error() {
    start_server 1:done || return 1
    curl -s -o /dev/null -X DELETE "$BASE/api/analyses/1"
    remove_analyses 1 >/dev/null
}

# A queued analysis behind a running one would start as soon as the first ends; it is cancelled first.
test_queued_analyses_are_cancelled_before_a_running_one_is_waited_for() {
    start_server 1:running:5 2:queued || return 1
    remove_analyses 1 2 >/dev/null
    local sequence
    sequence=$(calls | grep -n 'POST /api/analyses/2/cancel\|DELETE /api/analyses/1' | cut -d: -f1 | tr '\n' ' ')
    local cancel_line=${sequence%% *}
    [[ $(calls | sed -n "${cancel_line}p") == 'POST /api/analyses/2/cancel' ]] && [[ $(status_code_of 1) == 404 && $(status_code_of 2) == 404 ]]
}

test_one_stuck_analysis_does_not_keep_the_others_from_being_removed() {
    start_server 1:running 2:done || return 1
    remove_analyses 1 2 >/dev/null
    [[ $(status_code_of 2) == 404 ]]
}

test_the_analyses_of_a_sample_are_found_by_its_hash() {
    local mine=$(printf 'a%.0s' {1..64}) other=$(printf 'b%.0s' {1..64})
    start_server "1:done:0:$mine" "2:done:0:$other" "3:running:0:$mine" || return 1
    [[ $(analyses_of_sample "$mine" | tr '\n' ' ') == "1 3 " ]]
}

# Two analyses on different guests run together, so a step that needs the second to wait for the first
# pins both to the guest the first one was given.
test_options_are_pinned_to_the_guest_of_another_analysis() {
    start_server 7:running || return 1
    [[ $(options_on_the_guest_of 7 '"timeout": 60') == '{"timeout": 60, "guest": "lab-7"}' ]] &&
        [[ $(options_on_the_guest_of 7) == '{"guest": "lab-7"}' ]]
}

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    stop_server
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
