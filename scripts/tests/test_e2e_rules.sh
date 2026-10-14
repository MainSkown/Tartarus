#!/usr/bin/env bash
# Tests scripts/lib/e2e-rules.sh: the Sigma assertions `make e2e` runs on a finished analysis, and
# the disable-then-re-ingest cycle that must always leave the self-test rule enabled. The API is
# replaced by fixtures/fake_rules_api.py; a correct fake must pass every check, and for each way the
# API can go wrong (a "fault" of the fake) the check meant to catch it must fail.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAKE_API=$REPO/scripts/tests/fixtures/fake_rules_api.py
WORK_DIR="$(mktemp -d)"
SERVER_PID=""
ANALYSIS_ID=7
trap 'stop_server; rm -rf "$WORK_DIR"' EXIT

cd "$REPO" || exit 1
source "$REPO/scripts/lib/e2e-api.sh"
source "$REPO/scripts/lib/e2e-views.sh"
source "$REPO/scripts/lib/e2e-query.sh"
source "$REPO/scripts/lib/e2e-rules.sh"
POLL_SECONDS=0.05
ANALYSIS_TIMEOUT=2

start_server() { # fault...
    local port tries=0
    port=$(python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
    python3 -I "$FAKE_API" "$port" "$@" &
    SERVER_PID=$!
    BASE=http://127.0.0.1:$port
    until curl -s -o /dev/null -m 1 "$BASE/calls"; do
        ((++tries > 50)) && { echo "the fake API did not start" >&2; return 1; }
        sleep 0.1
    done
    SELFTEST_RULE_DISABLED=0
}

stop_server() { [[ -n $SERVER_PID ]] && { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }; SERVER_PID=""; return 0; }

calls() { curl -s "$BASE/calls" | python3 -I -c 'import json, sys; print("\n".join(json.load(sys.stdin)))'; }
rule_is_enabled_on_the_server() { [[ $(curl -s "$BASE/api/rules/$SELFTEST_RULE_ID" | json_field .enabled) == True ]]; }

CHECKS_WITHOUT_AN_ANALYSIS="rules_endpoint_lists_the_shipped_set_and_the_selftest_rule"
CHECKS_ON_AN_ANALYSIS="
    selftest_alert_is_single_and_names_the_registry_write
    selftest_detection_is_in_the_sigma_group
    rule_has_one_detection
"

run_check() { # check-name
    case " $CHECKS_WITHOUT_AN_ANALYSIS " in
        *" $1 "*) "$1" ;;
        *) "$1" "$ANALYSIS_ID" ;;
    esac
}

test_every_check_passes_on_a_correct_api() {
    start_server || return 1
    local name output failures=0
    for name in $CHECKS_WITHOUT_AN_ANALYSIS $CHECKS_ON_AN_ANALYSIS; do
        output=$(run_check "$name" 2>&1) || { echo "$name failed: $output" >&2; failures=$((failures + 1)); }
    done
    ((failures == 0))
}

# fault -> the check that has to notice it, and the words its message must hold.
fault_is_caught_by() { # fault check words
    stop_server
    start_server "$1" || return 1
    local output
    if output=$(run_check "$2" 2>&1); then
        echo "$2 passed although the API has the fault '$1'" >&2
        return 1
    fi
    [[ $output == *"$3"* && $output != *Traceback* ]] || { echo "$2 failed for '$1' without '$3': $output" >&2; return 1; }
}

LISTS=rules_endpoint_lists_the_shipped_set_and_the_selftest_rule
ONE_ALERT=selftest_alert_is_single_and_names_the_registry_write

test_too_few_shipped_rules_are_caught() { fault_is_caught_by too_few_rules $LISTS "30 shipped rules"; }
test_a_shipped_rule_that_is_not_valid_is_named_with_its_error() { fault_is_caught_by shipped_invalid $LISTS "00000000-0000-4000-8000-000000000003 is invalid: the condition names a missing selection"; }
test_a_missing_selftest_rule_is_caught() { fault_is_caught_by tartarus_missing $LISTS "no rule 6c17e2ec"; }
test_a_disabled_selftest_rule_is_caught() { fault_is_caught_by tartarus_disabled $LISTS "is disabled"; }
test_two_alerts_of_the_rule_are_caught() { fault_is_caught_by two_alerts $ONE_ALERT "2 alerts of the rule"; }
test_no_alert_of_the_rule_is_caught() { fault_is_caught_by no_alert $ONE_ALERT "0 alerts of the rule"; }
test_a_trigger_that_is_not_a_registry_write_is_caught() { fault_is_caught_by alert_not_registry $ONE_ALERT "reg-value-set"; }
test_a_trigger_on_another_registry_path_is_caught() { fault_is_caught_by wrong_registry_path $ONE_ALERT "Tartarus"; }
test_a_detections_view_without_a_sigma_group_is_caught() { fault_is_caught_by no_sigma_group selftest_detection_is_in_the_sigma_group "no sigma group"; }
test_a_hit_count_of_two_is_caught() { fault_is_caught_by hits_count_two rule_has_one_detection "hits report 2"; }
test_a_rule_missing_from_the_hits_is_caught() { fault_is_caught_by hits_missing rule_has_one_detection "hits report absent"; }

# The whole cycle: what it prints, and whether the rule is enabled on the server afterwards.
run_the_cycle() { # fault...
    stop_server
    start_server "$@" || return 1
    check_sigma_rules "$ANALYSIS_ID" >"$WORK_DIR/out" 2>&1
    return 0
}

test_the_cycle_passes_and_leaves_the_rule_enabled() {
    run_the_cycle || return 1
    ! grep -q '^\[FAIL\]' "$WORK_DIR/out" && rule_is_enabled_on_the_server || { cat "$WORK_DIR/out" >&2; return 1; }
}

test_the_cycle_disables_reingests_enables_and_reingests_again() {
    run_the_cycle || return 1
    local sequence
    sequence=$(calls | grep -E 'PATCH|reingest' | tr '\n' ' ')
    [[ $sequence == *"PATCH /api/rules/$SELFTEST_RULE_ID POST /api/analyses/7/reingest PATCH /api/rules/$SELFTEST_RULE_ID POST /api/analyses/7/reingest "* ]] ||
        { echo "calls: $sequence" >&2; return 1; }
}

cycle_fails_saying_and_leaves_the_rule_enabled() { # fault words
    run_the_cycle "$1" || return 1
    grep -q '^\[FAIL\].*'"$2" "$WORK_DIR/out" || { echo "no FAIL saying '$2' for '$1':" >&2; cat "$WORK_DIR/out" >&2; return 1; }
    rule_is_enabled_on_the_server || { echo "the rule was left disabled after the fault '$1'" >&2; return 1; }
}

test_a_disable_that_does_not_stick_is_caught() { cycle_fails_saying_and_leaves_the_rule_enabled disable_ignored "disables the rule"; }
test_an_alert_that_survives_the_disable_is_caught() { cycle_fails_saying_and_leaves_the_rule_enabled alert_survives_disable "0 alerts"; }
test_a_disabled_rule_that_stays_in_the_hits_is_caught() { cycle_fails_saying_and_leaves_the_rule_enabled hits_keep_disabled "0 alerts"; }
test_a_detection_that_is_not_restored_is_caught() { cycle_fails_saying_and_leaves_the_rule_enabled detection_not_restored "restores"; }
test_a_refused_reingest_is_caught_and_the_rule_is_enabled_again() { cycle_fails_saying_and_leaves_the_rule_enabled reingest_refused "re-ingesting"; }
test_a_reingest_that_never_ends_is_caught_and_the_rule_is_enabled_again() { cycle_fails_saying_and_leaves_the_rule_enabled reingest_stuck "re-ingesting"; }

test_an_enable_that_does_not_stick_is_reported_and_stays_pending_for_the_cleanup() {
    run_the_cycle enable_ignored || return 1
    grep -q '^\[FAIL\].*enabled again' "$WORK_DIR/out" && [[ $SELFTEST_RULE_DISABLED == 1 ]] || { cat "$WORK_DIR/out" >&2; return 1; }
}

# --- the cleanup -------------------------------------------------------------------------------

test_the_cleanup_enables_a_rule_the_run_disabled() {
    start_server || return 1
    SELFTEST_RULE_DISABLED=1
    set_rule_enabled "$SELFTEST_RULE_ID" false >/dev/null
    restore_selftest_rule >/dev/null && rule_is_enabled_on_the_server && [[ $SELFTEST_RULE_DISABLED == 0 ]]
}

test_the_cleanup_leaves_a_rule_alone_the_run_never_disabled() {
    start_server || return 1
    restore_selftest_rule >/dev/null && ! calls | grep -q PATCH
}

test_the_cleanup_says_so_when_it_cannot_enable_the_rule() {
    start_server enable_ignored || return 1
    SELFTEST_RULE_DISABLED=1
    set_rule_enabled "$SELFTEST_RULE_ID" false >/dev/null
    ! restore_selftest_rule >/dev/null 2>&1 && [[ $SELFTEST_RULE_DISABLED == 1 ]]
}

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    stop_server
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
