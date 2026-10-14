#!/usr/bin/env bash
# Tests scripts/lib/e2e-query.sh: the assertions `make e2e` runs against a finished analysis's
# events API. The API is replaced by fixtures/fake_events_api.py; a correct fake must pass every
# check, and for each way the API can go wrong (a "fault" of the fake) the check that is meant to
# catch it must fail, so a check that could never fail is found here and not on the real stack.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAKE_API=$REPO/scripts/tests/fixtures/fake_events_api.py
WORK_DIR="$(mktemp -d)"
SERVER_PID=""
ANALYSIS_ID=7
trap 'stop_server; rm -rf "$WORK_DIR"' EXIT

cd "$REPO" || exit 1
source "$REPO/scripts/lib/e2e-api.sh"
source "$REPO/scripts/lib/e2e-views.sh"
source "$REPO/scripts/lib/e2e-query.sh"

free_port() { python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

start_server() { # fault...
    local port
    port=$(free_port)
    python3 -I "$FAKE_API" "$port" "$@" &
    SERVER_PID=$!
    BASE=http://127.0.0.1:$port
    local tries=0
    until curl -s -o /dev/null -m 1 "$BASE/api/query/fields"; do
        ((++tries > 50)) && { echo "the fake API did not start" >&2; return 1; }
        sleep 0.1
    done
}

stop_server() { [[ -n $SERVER_PID ]] && { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }; SERVER_PID=""; return 0; }

# The checks that take the analysis id; the first two take nothing.
CHECKS_WITHOUT_AN_ANALYSIS="query_validation_accepts_a_good_query query_validation_flags_a_misspelt_field field_catalog_lists_process_name_and_its_aliases"
CHECKS_ON_AN_ANALYSIS="
    unfiltered_search_total_is_event_count
    paging_covers_every_event_once_in_both_sorts
    lane_query_matches_the_lane_count
    lane_chip_equals_the_query_and_a_negated_chip_is_the_rest
    process_alias_finds_only_the_sample_process
    free_text_finds_the_sample_name
    impossible_query_has_no_events
    bad_queries_answer_422_with_spans
    bad_cursor_answers_422
    unknown_analysis_answers_404
    top_process_facet_count_matches_a_search
    lane_facet_ignores_its_own_chip
    histogram_sums_to_the_totals_and_lane_counts
    event_detail_has_the_raw_document
    alert_and_the_event_it_names_point_at_each_other
    value_autocomplete_finds_the_sample_name
    columns_return_the_command_line
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

test_an_index_over_the_paging_cap_is_cut_to_its_first_pages_and_says_so() {
    start_server || return 1
    local output
    output=$(QUERY_MAX_PAGED_EVENTS=100 paging_covers_every_event_once_in_both_sorts "$ANALYSIS_ID" 2>&1) || { echo "$output" >&2; return 1; }
    [[ $output == *"reverse was not compared"* ]] || { echo "the cut is not in the detail: $output" >&2; return 1; }
}

# fault -> the check that has to notice it.
fault_is_caught_by() { # fault check
    stop_server
    start_server "$1" || return 1
    local output
    if output=$(run_check "$2" 2>&1); then
        echo "$2 passed although the API has the fault '$1'" >&2
        return 1
    fi
    [[ -n $output && $output != *Traceback* ]] || { echo "$2 failed without a clear message for '$1': $output" >&2; return 1; }
    [[ -z ${SHOW_FAULT_MESSAGES:-} ]] || echo "  $1: $output" >&2
}

test_a_total_that_is_off_by_one_is_caught() { fault_is_caught_by total_off_by_one unfiltered_search_total_is_event_count; }
test_a_repeated_event_between_pages_is_caught() { fault_is_caught_by duplicate_page paging_covers_every_event_once_in_both_sorts; }
test_a_descending_order_that_is_not_the_reverse_is_caught() { fault_is_caught_by sorts_not_reversed paging_covers_every_event_once_in_both_sorts; }
test_a_lane_query_that_filters_nothing_is_caught() { fault_is_caught_by lane_query_ignored lane_query_matches_the_lane_count; }
test_a_negated_chip_that_is_not_negated_is_caught() { fault_is_caught_by negated_chip_ignored lane_chip_equals_the_query_and_a_negated_chip_is_the_rest; }
test_an_alias_that_matches_everything_is_caught() { fault_is_caught_by alias_ignored process_alias_finds_only_the_sample_process; }
test_free_text_that_finds_nothing_is_caught() { fault_is_caught_by free_text_finds_nothing free_text_finds_the_sample_name; }
test_a_cursor_on_an_empty_result_is_caught() { fault_is_caught_by impossible_has_cursor impossible_query_has_no_events; }
test_a_bad_query_that_runs_is_caught() { fault_is_caught_by bad_query_runs bad_queries_answer_422_with_spans; }
test_a_bad_cursor_that_is_accepted_is_caught() { fault_is_caught_by bad_cursor_accepted bad_cursor_answers_422; }
test_an_unknown_analysis_that_answers_is_caught() { fault_is_caught_by unknown_analysis_200 unknown_analysis_answers_404; }
test_a_facet_count_that_differs_from_a_search_is_caught() { fault_is_caught_by facet_count_off top_process_facet_count_matches_a_search; }
test_a_facet_that_applies_its_own_chip_is_caught() { fault_is_caught_by own_chip_applies lane_facet_ignores_its_own_chip; }
test_a_histogram_that_loses_an_event_is_caught() { fault_is_caught_by histogram_lossy histogram_sums_to_the_totals_and_lane_counts; }
test_a_histogram_without_detections_is_caught() { fault_is_caught_by no_detections histogram_sums_to_the_totals_and_lane_counts; }
test_an_event_without_its_raw_document_is_caught() { fault_is_caught_by no_raw event_detail_has_the_raw_document; }
test_a_detection_that_nothing_points_back_to_is_caught() { fault_is_caught_by no_referenced_by alert_and_the_event_it_names_point_at_each_other; }
test_a_value_autocomplete_that_finds_nothing_is_caught() { fault_is_caught_by values_empty value_autocomplete_finds_the_sample_name; }
test_columns_that_return_nothing_are_caught() { fault_is_caught_by columns_ignored columns_return_the_command_line; }

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    stop_server
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
