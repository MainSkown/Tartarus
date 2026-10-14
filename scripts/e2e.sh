#!/usr/bin/env bash
# End-to-end check of the stack against the REAL services (`make up` first, guest built and registered):
# submits a harmless sample through the frontend's published port and follows it through the
# queue, the guest and the report. On the finished analysis of step (a) it checks the event index,
# every analysis view (processes, network, detections, ATT&CK, IOCs, artifacts) and the query API:
# validation, the field catalog, search with paging in both sorts, query/chip/lane narrowing, the
# error answers, facets, the histogram, one event with its related events, value autocomplete and
# extra columns, each compared with the analysis record's own counts (scripts/lib/e2e-query.sh).
# The live feed is always checked on the same analysis. Then it checks the queue order and
# cancelling, deleting a finished analysis, and a browser run of the submit flow
# (frontend/tests/e2e/submit-flow.spec.ts: the tabs, and the Events and Timeline tabs filtering the
# real index) on a second analysis. Step (j) always ends an interactive run early through POST /finish.
# `E2E_DRILLS=1` adds the failure drills, which stop cape or opensearch and restart the backend
# mid-run and put them back afterwards. `E2E_SKIP_UI=1` skips the browser test.
# `E2E_DESKTOP=1` adds the interactive desktop (the tunnel's API half, then the browser test
# frontend/tests/e2e/desktop-flow.spec.ts): it holds the guest for the whole timeout of two
# interactive runs, about 10 minutes.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO=$PWD

SAMPLE_SRC=$REPO/guest/testsample/benign.c
SAMPLE_DIR=${TMPDIR:-/tmp}/tt-guest-verify
SAMPLES_IN_BACKEND=/data/samples
BROWSER_SECONDS=${E2E_BROWSER_SECONDS:-480}
ANALYSIS_TIMEOUT=${E2E_ANALYSIS_TIMEOUT:-420}
RESTORE_TIMEOUT=${E2E_RESTORE_TIMEOUT:-240}
DRILLS=${E2E_DRILLS:-0}
CAPE_DOWN_SECONDS=${E2E_CAPE_DOWN_SECONDS:-15}
GRACE_MARGIN=${E2E_GRACE_MARGIN:-45}
SKIP_UI=${E2E_SKIP_UI:-0}
DESKTOP=${E2E_DESKTOP:-0}

source "$REPO/scripts/lib/benign-sample.sh"
source "$REPO/scripts/lib/e2e-api.sh"
source "$REPO/scripts/lib/e2e-views.sh"
source "$REPO/scripts/lib/e2e-query.sh"
source "$REPO/scripts/lib/e2e-live.sh"
source "$REPO/scripts/lib/e2e-finish.sh"

WORK_DIR=$(mktemp -d)
CREATED_IDS=()

# --- cleanup ----------------------------------------------------------------

remember() { CREATED_IDS+=("$1"); }

# Always runs: puts cape, opensearch and the backend back, then removes what the run created. An
# analysis that is still running is waited for (see remove_analysis), so a failed step does not leave
# one behind to block the next run; a second interrupt skips the wait.
cleanup() {
    trap - EXIT
    stop_live_watch
    compose start opensearch cape backend >/dev/null 2>&1
    if [[ -n ${BASE:-} ]]; then
        wait_for_health cape ok "$RESTORE_TIMEOUT" >/dev/null 2>&1 || info "cape is not healthy after the run"
        wait_for_health opensearch ok "$RESTORE_TIMEOUT" >/dev/null 2>&1 || info "opensearch is not healthy after the run"
    fi
    remove_analyses "${CREATED_IDS[@]}" >/dev/null 2>&1
    rm -rf "$WORK_DIR" "$RESPONSE_FILE"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# --- preconditions ----------------------------------------------------------

stack_is_up() {
    [[ $(health_status postgres) != unreachable ]] || { echo "no answer from $BASE/api/system/health; run 'make up'"; return 1; }
}

component_is_ok() {
    local status
    status=$(health_status "$1")
    [[ $status == ok ]] || { echo "$1 is '$status'"; return 1; }
}

guest_is_registered() {
    component_is_ok guest || { echo "build it with 'make build-guest' (this script does not)"; return 1; }
}

no_analysis_is_active() {
    http GET "/api/analyses?limit=200"
    local active
    active=$(body | json_eval 'sum(a["status"] in ("queued", "starting", "running", "processing", "ingesting") for a in v["items"])')
    [[ $active == 0 ]] || { echo "$active analyses are still active; wait for them or cancel them"; return 1; }
}

check_preconditions() {
    resolve_base_url || { fail "the frontend publishes no port; run 'make up'"; return 1; }
    check "stack is up (frontend answers on $BASE)" stack_is_up || return 1
    check "cape is ok in /api/system/health" component_is_ok cape || return 1
    check "guest is registered and ready in /api/system/health" guest_is_registered || return 1
    check "no analysis is queued or running already" no_analysis_is_active || return 1
}

# --- samples ----------------------------------------------------------------

# A copy of benign.exe with random trailing bytes, so each group of analyses has its own hash and
# "the sample file is removed" can be asserted without other analyses sharing the file.
unique_sample() { # name
    cp "$SAMPLE_DIR/benign.exe" "$WORK_DIR/$1"
    head -c 32 /dev/urandom >> "$WORK_DIR/$1"
    echo "$WORK_DIR/$1"
}

sha256_of() { sha256sum "$1" | cut -d' ' -f1; }

stored_sample_exists() { compose exec -T backend test -f "$SAMPLES_IN_BACKEND/$1.zip"; }

submit_and_remember() { # file
    submit_sample "$1" && remember "$SUBMITTED_ID"
}

# --- (a) a submitted sample runs to done -------------------------------------

has_score_and_signature() { # id
    http GET "/api/analyses/$1"
    local score signatures
    score=$(body | json_field .score)
    signatures=$(body | json_eval 'len(v["summary"]["signatures"]) if v["summary"] else 0')
    [[ $score != null ]] || { echo "no score"; return 1; }
    ((signatures >= 1)) || { echo "no signatures in the summary"; return 1; }
    echo "score $score, $signatures signatures"
}

step_a_sample_runs_to_done() {
    local started=$SECONDS
    A_FILE=$(unique_sample e2e-a.exe)
    A_SHA=$(sha256_of "$A_FILE")
    submit_and_remember "$A_FILE" || { fail "(a) POST /api/analyses did not answer 201"; return 1; }
    A_ID=$SUBMITTED_ID
    ok "(a) submit answered 201 with analysis id $A_ID"
    watch_live_in_background "$A_ID" --include-api --query-probe
    check "(a) analysis $A_ID reaches done" wait_for_status "$A_ID" done "$ANALYSIS_TIMEOUT" || return 1
    finish_live_watch
    check "(a) the result has a score and at least one signature" has_score_and_signature "$A_ID"
    check_finished_analysis_views "$A_ID" "$A_SHA"
    check_finished_analysis_queries "$A_ID"
    info "(a) took $((SECONDS - started)) s"
}

# --- (h) the live feed -------------------------------------------------------------------------

step_h_live_feed() {
    [[ -s ${LIVE_SUMMARY:-} ]] || { fail "(h) skipped: step (a) recorded no live feed"; return 1; }
    check_live_feed "$A_ID" "$LIVE_SUMMARY" "$(basename "$A_FILE")"
}

# --- (b) and (c) strict order, and cancelling a queued analysis ---------------

cancel_answers_cancelled() { # id
    http POST "/api/analyses/$1/cancel"
    [[ $HTTP_CODE == 200 ]] || { echo "cancel answered $HTTP_CODE: $(body)"; return 1; }
    [[ $(body | json_field .status) == cancelled ]] || { echo "status is $(body | json_field .status)"; return 1; }
    [[ $(analysis_status "$1") == cancelled ]]
}

# The second analysis must never leave `queued` while the first is not finished. It is read
# first: a terminal state is final, so seeing the first unfinished afterwards proves it was
# unfinished at the moment the second was seen started.
second_waits_for_first() { # first second
    local first=$1 second=$2 deadline=$((SECONDS + ANALYSIS_TIMEOUT)) second_status first_status polls=0
    while ((SECONDS < deadline)); do
        second_status=$(analysis_status "$second") || return 1
        first_status=$(analysis_status "$first") || return 1
        ((polls++))
        if [[ $second_status != queued ]] && ! in_words "$first_status" "$TERMINAL_STATES"; then
            echo "analysis $second is '$second_status' while analysis $first is still '$first_status'"
            return 1
        fi
        if in_words "$second_status" "$TERMINAL_STATES"; then
            [[ $first_status == done ]] || { echo "analysis $first ended as '$first_status'"; return 1; }
            [[ $second_status == done ]] || { echo "analysis $second ended as '$second_status': $(analysis_field "$second" error)"; return 1; }
            echo "$polls polls; $second stayed queued until $first finished"
            return 0
        fi
        sleep 1
    done
    echo "analyses $first and $second did not both finish within $ANALYSIS_TIMEOUT s"
    return 1
}

step_bc_order_and_cancel() {
    local started=$SECONDS
    B_FILE=$(unique_sample e2e-b.exe)
    B_SHA=$(sha256_of "$B_FILE")
    submit_and_remember "$B_FILE" && B1_ID=$SUBMITTED_ID &&
        submit_and_remember "$B_FILE" && B2_ID=$SUBMITTED_ID &&
        submit_and_remember "$B_FILE" && B3_ID=$SUBMITTED_ID ||
        { fail "(b) submitting three analyses at once"; return 1; }
    ok "(b) three analyses submitted at once: $B1_ID, $B2_ID, $B3_ID"
    check "(c) cancelling queued analysis $B3_ID answers cancelled" cancel_answers_cancelled "$B3_ID"
    check "(b) analysis $B2_ID stays queued until $B1_ID is finished, then both are done" second_waits_for_first "$B1_ID" "$B2_ID"
    check "(c) the cancelled analysis never ran" cancelled_never_ran "$B3_ID"
    info "(b,c) took $((SECONDS - started)) s"
}

cancelled_never_ran() { # id
    http GET "/api/analyses/$1"
    [[ $(body | json_field .status) == cancelled && $(body | json_field .cape_task_id) == null ]] ||
        { echo "status $(body | json_field .status), cape_task_id $(body | json_field .cape_task_id)"; return 1; }
}

# --- (d) deleting a finished analysis ----------------------------------------

is_gone() { # id
    http GET "/api/analyses/$1"
    [[ $HTTP_CODE == 404 ]] || { echo "GET answered $HTTP_CODE"; return 1; }
}

delete_removes_analysis() { # id
    delete_analysis "$1" && is_gone "$1"
}

delete_removes_analysis_and_never_indexed() { # id
    index_is_gone "$1" && delete_removes_analysis "$1" && index_is_gone "$1"
}

delete_removes_analysis_and_index() { # id
    index_exists "$1" || { echo "$(index_name "$1") did not exist before the delete"; return 1; }
    delete_removes_analysis "$1" && index_is_gone "$1"
}

sample_file_is_present() { stored_sample_exists "$1" || { echo "no $SAMPLES_IN_BACKEND/$1.zip in the backend"; return 1; }; }
sample_file_is_gone() { ! stored_sample_exists "$1" || { echo "$SAMPLES_IN_BACKEND/$1.zip is still in the backend"; return 1; }; }

step_d_delete() {
    check "(d) the sample file exists while analysis $A_ID refers to it" sample_file_is_present "$A_SHA"
    check "(d) deleting finished analysis $A_ID answers 204 and it and its event index are gone" delete_removes_analysis_and_index "$A_ID"
    check "(d) its sample file is removed because nothing refers to it" sample_file_is_gone "$A_SHA"
    check "(d) deleting $B1_ID (done) answers 204 and it and its event index are gone" delete_removes_analysis_and_index "$B1_ID"
    check "(d) the sample stays while $B2_ID and the cancelled $B3_ID still refer to it" sample_file_is_present "$B_SHA"
    check "(d) deleting $B2_ID (done) answers 204 and it and its event index are gone" delete_removes_analysis_and_index "$B2_ID"
    check "(d) deleting the cancelled $B3_ID answers 204 and it is gone, with no index to leave behind" delete_removes_analysis_and_never_indexed "$B3_ID"
    check "(d) the sample file is removed with the last analysis that used it" sample_file_is_gone "$B_SHA"
}

# --- browser test -------------------------------------------------------------

# The desktop spec is opt in through E2E_DESKTOP, so each run pins it: a `make e2e DESKTOP=1` must not
# also run it inside the submit flow's call.
browser_test_passes() { # file spec desktop(0|1) bound-seconds
    local output
    output=$(cd frontend && E2E_BASE_URL=$BASE E2E_SAMPLE=$1 E2E_DESKTOP=$3 timeout "$4" npm run --silent e2e -- "$2" 2>&1)
    local status=$?
    # A skipped test exits 0 too, so the count is what proves it ran.
    if ((status == 0)) && grep -q '1 passed' <<<"$output"; then return 0; fi
    tail -25 <<<"$output"
    return 1
}

# The browser submits its own analysis, so this script learns of it by the sample's hash; remembered,
# cleanup removes it even when the test died before it could.
remember_analyses_of_sample() { # sha256
    local id
    for id in $(analyses_of_sample "$1"); do remember "$id"; done
}

step_browser_flow() {
    local started=$SECONDS sample sha
    sample=$(unique_sample e2e-ui.exe)
    sha=$(sha256_of "$sample")
    check "browser: the submit dialog lands on /analyses/<id>, the page shows done with a score, and the Events and Timeline tabs answer queries" \
        browser_test_passes "$sample" submit-flow 0 "$BROWSER_SECONDS"
    remember_analyses_of_sample "$sha"
    info "browser flow took $((SECONDS - started)) s"
}

step_i_interactive_desktop() {
    local started=$SECONDS
    desktop_api_flow
    check "browser: the LIVE tab shows the guest's desktop, takes the mouse and keys, and ends with the run" \
        browser_test_passes "$(unique_sample e2e-desktop.exe)" desktop-flow 1 "$DESKTOP_BROWSER_SECONDS"
    info "(i) took $((SECONDS - started)) s"
}

# --- drills -------------------------------------------------------------------

drill_grace_seconds() {
    local configured
    configured=$(compose exec -T backend printenv RUNNER_UNREACHABLE_GRACE_SECONDS 2>/dev/null)
    echo "${configured:-120}"
}

wait_for_running() { wait_for_status "$1" "running" "$ANALYSIS_TIMEOUT"; }

stays_active() { # id
    local status
    status=$(analysis_status "$1") || return 1
    in_words "$status" "$TERMINAL_STATES" && { echo "analysis $1 is already '$status'"; return 1; }
    echo "analysis $1 is still '$status'"
}

ended_with_a_message() { # id
    local status error
    status=$(analysis_status "$1") && error=$(analysis_field "$1" error) || return 1
    case $status in
        failed | report_failed) [[ $error != null && -n $error ]] || { echo "$status without an error message"; return 1; }
            echo "$status: $error" ;;
        *) echo "$status" ;;
    esac
}

# Submits two analyses, waits for the first to run, then stops cape. Sets DRILL_FIRST, DRILL_SECOND
# (queued behind it) and STOPPED_AT.
start_two_and_stop_cape() { # label
    submit_and_remember "$(unique_sample "e2e-$1-first.exe")" && DRILL_FIRST=$SUBMITTED_ID &&
        submit_and_remember "$(unique_sample "e2e-$1-second.exe")" && DRILL_SECOND=$SUBMITTED_ID ||
        { fail "($1) submitting the two drill analyses"; return 1; }
    check "($1) analysis $DRILL_FIRST is running" wait_for_running "$DRILL_FIRST" || return 1
    compose stop cape >/dev/null 2>&1
    STOPPED_AT=$SECONDS
    check "($1) /api/system/health reports cape down" wait_for_health cape down 60
}

queue_moves_on() { # id
    check "($DRILL_LABEL) the queue moves on: analysis $1 leaves queued and finishes done" \
        wait_for_status "$1" done "$ANALYSIS_TIMEOUT"
}

# CAPE is back within the grace period, so the runner keeps following the same task. Stopping the
# container kills the guest, and CAPE itself then ends the orphaned task as failed_analysis.
step_e_cape_restarts_within_grace() {
    local grace
    DRILL_LABEL=e
    grace=$(drill_grace_seconds)
    start_two_and_stop_cape e || return 1
    info "(e) cape is down for $CAPE_DOWN_SECONDS s, well inside the ${grace} s grace"
    sleep "$CAPE_DOWN_SECONDS"
    check "(e) the backend keeps analysis $DRILL_FIRST active while cape is down" stays_active "$DRILL_FIRST"
    compose start cape >/dev/null 2>&1
    check "(e) cape is ok in /api/system/health again" wait_for_health cape ok "$RESTORE_TIMEOUT"
    check "(e) analysis $DRILL_FIRST reaches a terminal state within the ${grace} s grace after cape returned" \
        wait_for_terminal "$DRILL_FIRST" "$grace"
    check "(e) a failed analysis carries an error message" ended_with_a_message "$DRILL_FIRST"
    info "(e) analysis $DRILL_FIRST ended $((SECONDS - STOPPED_AT)) s after the stop"
    queue_moves_on "$DRILL_SECOND"
}

error_names_the_outage() { # id
    local error
    error=$(analysis_field "$1" error) || return 1
    [[ $error == *"CAPE has been unreachable for"* ]] || { echo "error is '$error'"; return 1; }
    echo "$error"
}

# The plan's promise: CAPE gone for longer than the grace period ends the analysis as failed.
step_e2_cape_down_past_grace() {
    local grace
    DRILL_LABEL=e2
    grace=$(drill_grace_seconds)
    start_two_and_stop_cape e2 || return 1
    info "(e2) cape stays down past the ${grace} s grace"
    check "(e2) analysis $DRILL_FIRST is failed within $((grace + GRACE_MARGIN)) s of the stop" \
        wait_for_status "$DRILL_FIRST" failed "$((grace + GRACE_MARGIN))"
    check "(e2) its error says how long CAPE was unreachable" error_names_the_outage "$DRILL_FIRST"
    info "(e2) analysis $DRILL_FIRST failed $((SECONDS - STOPPED_AT)) s after the stop"
    compose start cape >/dev/null 2>&1
    check "(e2) cape is ok in /api/system/health again" wait_for_health cape ok "$RESTORE_TIMEOUT"
    queue_moves_on "$DRILL_SECOND"
}

same_task_id() { # id expected
    local current
    current=$(analysis_field "$1" cape_task_id) || return 1
    [[ $current == "$2" ]] || { echo "cape_task_id is $current, was $2"; return 1; }
    echo "task $current"
}

step_f_backend_restarts_mid_run() {
    local id task_id
    submit_and_remember "$(unique_sample e2e-f.exe)" || { fail "(f) submitting the drill analysis"; return 1; }
    id=$SUBMITTED_ID
    watch_live_in_background "$id" --include-api --reconnect
    check "(f) analysis $id is running" wait_for_running "$id" || return 1
    task_id=$(analysis_field "$id" cape_task_id)
    compose restart backend >/dev/null 2>&1
    check "(f) the backend answers again after the restart" wait_for_health postgres ok 120
    check "(f) analysis $id still points at CAPE task $task_id" same_task_id "$id" "$task_id"
    check "(f) analysis $id finishes done" wait_for_status "$id" done "$ANALYSIS_TIMEOUT"
    check "(f) it is still the same CAPE task" same_task_id "$id" "$task_id"
    finish_live_watch
    check "(f) a live client that reconnected across the restart saw only events of the final index and phase final" \
        live_client_survived_the_restart "$LIVE_SUMMARY" "$id"
}

# --- (g) re-ingest after an index outage --------------------------------------

error_says_indexing_failed() { # id
    local error
    error=$(analysis_field "$1" error) || return 1
    [[ ${error,,} == *indexing* ]] || { echo "error is '$error'"; return 1; }
    echo "$error"
}

failed_ingest_left_nothing_behind() { # id
    local count
    count=$(analysis_field "$1" event_count) || return 1
    [[ $count == 0 ]] || { echo "event_count is $count"; return 1; }
    index_is_gone "$1"
}

reingest_answers() { # id expected-code
    http POST "/api/analyses/$1/reingest"
    [[ $HTTP_CODE == "$2" ]] || { echo "answered $HTTP_CODE (wanted $2): $(body)"; return 1; }
    echo "answered $HTTP_CODE"
}

step_g_reingest_after_index_outage() {
    local failed_id busy_id
    submit_and_remember "$(unique_sample e2e-g-failed.exe)" && failed_id=$SUBMITTED_ID ||
        { fail "(g) submitting the drill analysis"; return 1; }
    compose stop opensearch >/dev/null 2>&1
    check "(g) /api/system/health reports opensearch down" wait_for_health opensearch down 60 || return 1
    check "(g) analysis $failed_id ends report_failed because its events could not be indexed"         wait_for_status "$failed_id" report_failed "$ANALYSIS_TIMEOUT" || return 1
    check "(g) its error says indexing failed" error_says_indexing_failed "$failed_id"
    compose start opensearch >/dev/null 2>&1
    check "(g) opensearch is ok in /api/system/health again" wait_for_health opensearch ok "$RESTORE_TIMEOUT" || return 1
    check "(g) the failed analysis has no events and no index" failed_ingest_left_nothing_behind "$failed_id"

    submit_and_remember "$(unique_sample e2e-g-busy.exe)" && busy_id=$SUBMITTED_ID ||
        { fail "(g) submitting the second drill analysis"; return 1; }
    check "(g) analysis $busy_id is running" wait_for_running "$busy_id" || return 1
    check "(g) re-ingesting $failed_id while $busy_id is active answers 409" reingest_answers "$failed_id" 409
    check "(g) analysis $failed_id is still report_failed after the refused re-ingest" \
        wait_for_status "$failed_id" report_failed 5
    check "(g) analysis $busy_id finishes done" wait_for_status "$busy_id" done "$ANALYSIS_TIMEOUT" || return 1

    check "(g) re-ingesting $failed_id answers 200" reingest_answers "$failed_id" 200
    check "(g) analysis $failed_id reaches done" wait_for_status "$failed_id" done "$ANALYSIS_TIMEOUT" || return 1
    check "(g) its event_count is positive and the lane counts add up to it" event_count_matches_lanes "$failed_id"
    check "(g) the rebuilt index holds exactly event_count documents" index_holds_every_event "$failed_id"
}

# --- main ---------------------------------------------------------------------

main() {
    echo "== preconditions"
    check_preconditions || exit 1
    build_sample || { fail "could not build benign.exe with mingw-w64"; exit 1; }
    echo "== (a) a submitted sample runs to done"
    step_a_sample_runs_to_done
    echo "== (h) the live feed of step (a)"
    step_h_live_feed
    echo "== (b, c) order and cancel"
    step_bc_order_and_cancel
    echo "== (d) delete"
    [[ -n ${A_ID:-} && -n ${B3_ID:-} ]] && step_d_delete || fail "(d) skipped: the earlier steps did not produce analyses to delete"
    if [[ $SKIP_UI != 1 ]]; then
        echo "== browser flow"
        step_browser_flow
    fi
    echo "== (j) ending a run early"
    finish_run_ends_the_run
    if [[ $DESKTOP == 1 ]]; then
        echo "== (i) the interactive desktop"
        step_i_interactive_desktop
    fi
    if [[ $DRILLS == 1 ]]; then
        echo "== (e) cape restarts mid-run, inside the grace period"
        step_e_cape_restarts_within_grace
        echo "== (e2) cape stays down past the grace period"
        step_e2_cape_down_past_grace
        echo "== (f) the backend restarts mid-run"
        step_f_backend_restarts_mid_run
        echo "== (g) re-ingest after an index outage"
        step_g_reingest_after_index_outage
    fi
}

# Sourcing the file (to exercise one check on its own) must not run the whole suite.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
    exit "$failed"
fi
