# Assertions for scripts/e2e.sh on ending a running analysis early (`POST /api/analyses/{id}/finish`).
# An interactive run lasts its whole timeout; finishing it makes CAPE's analyzer stop within seconds
# and the runner carry the analysis on to done. Sourced after e2e-api.sh and e2e-live.sh (its live
# watch and summary checks); expects the helpers scripts/e2e.sh defines (remember, unique_sample).

FINISH_RUN_SECONDS=${E2E_FINISH_RUN_SECONDS:-300}
# Of the whole run, the analyzer needs about 10 s to stop; a run that is still going long after the call did not stop.
FINISH_LEAVES_RUNNING_SECONDS=${E2E_FINISH_LEAVES_RUNNING_SECONDS:-45}
MONITOR_UP_SECONDS=${E2E_MONITOR_UP_SECONDS:-120}

finish_analysis() { # id
    http POST "/api/analyses/$1/finish"
}

# "running" begins when CAPE takes the task, well before the guest is up; ending the run before the
# analyzer has started the monitor in the sample leaves the guest hung until CAPE gives up on it. The
# analyzer logs the sample's pid when it starts it, and the monitor writes logs/<pid>.bson once it runs
# in that process. Any other process's log (explorer.exe's comes about 10 s earlier) does not count.
sample_is_monitored() { # task
    compose exec -T cape sh -c "
        dir=/opt/CAPEv2/storage/analyses/$1
        pid=\$(sed -n 's/.*Successfully executed process from path .* with pid \\([0-9]*\\)\$/\\1/p' \$dir/analysis.log 2>/dev/null | head -n 1)
        [ -n \"\$pid\" ] && [ -e \$dir/logs/\$pid.bson ]"
}

wait_for_monitor() { # id
    local task deadline=$((SECONDS + MONITOR_UP_SECONDS))
    task=$(analysis_field "$1" cape_task_id) || return 1
    until sample_is_monitored "$task"; do
        ((SECONDS < deadline)) || { echo "the sample is not monitored in CAPE task $task after $MONITOR_UP_SECONDS s"; return 1; }
        sleep "$POLL_SECONDS"
    done
    echo "CAPE task $task"
}

finish_is_accepted_and_the_status_is_unchanged() { # id
    finish_analysis "$1"
    [[ $HTTP_CODE == 200 ]] || { echo "answered $HTTP_CODE: $(body)"; return 1; }
    json_assert <<PY
assert v["id"] == $1, f"another analysis: {v['id']}"
assert v["status"] == "running", f"status {v['status']}"
detail = "200, status still running"
PY
}

finish_again_while_running_is_accepted() { # id
    finish_analysis "$1"
    [[ $HTTP_CODE == 200 ]] && return 0
    echo "answered $HTTP_CODE: $(body)"
    return 1
}

# Echoes the seconds from now until the analysis is no longer running.
seconds_until_it_leaves_running() { # id
    local started=$SECONDS
    wait_for_status "$1" "processing ingesting done" "$FINISH_LEAVES_RUNNING_SECONDS" >/dev/null || return 1
    echo "left running $((SECONDS - started)) s after the second call, far inside the $FINISH_RUN_SECONDS s timeout"
}

analysis_is_done_with_a_report() { # id
    http GET "/api/analyses/$1"
    json_assert <<PY
assert v["status"] == "done", f"status {v['status']}: {v['error']}"
assert v["summary"] is not None, "done without a report summary"
detail = "done with a report"
PY
}

finish_is_refused_with() { # id expected-status expected-words
    finish_analysis "$1"
    [[ $HTTP_CODE == "$2" ]] || { echo "answered $HTTP_CODE: $(body)"; return 1; }
    grep -qF "$3" <<<"$(body)" || { echo "the message lacks '$3': $(body)"; return 1; }
    echo "$2: $(body | json_field .error.message)"
}

cancel_analysis() { # id
    http POST "/api/analyses/$1/cancel"
    [[ $HTTP_CODE == 200 ]] || { echo "cancelling $1 answered $HTTP_CODE: $(body)"; return 1; }
}

finishing_a_run_ends_it() {
    local id queued
    submit_sample "$(unique_sample e2e-finish.exe)" '{"interactive": true, "route": "inetsim", "timeout": '"$FINISH_RUN_SECONDS"'}' &&
        remember "$SUBMITTED_ID" || { fail "(j) submitting the interactive analysis"; return 1; }
    id=$SUBMITTED_ID
    check "(j) interactive analysis $id is running" wait_for_running "$id" || return 1
    ANALYSIS_TIMEOUT=$((FINISH_RUN_SECONDS + 60)) watch_live_in_background "$id"
    submit_sample "$(unique_sample e2e-finish-queued.exe)" "$(options_on_the_guest_of "$id" '"timeout": 60')" &&
        queued=$SUBMITTED_ID && remember "$queued" || { fail "(j) submitting the second analysis"; return 1; }
    check "(j) the second analysis waits for the guest, and finishing it answers 409" finish_is_refused_with "$queued" 409 "queued"
    check "(j) the queued analysis $queued is cancelled" cancel_analysis "$queued"
    check "(j) finishing an unknown analysis answers 404" finish_is_refused_with 999999 404 "not found"
    check "(j) the monitor is up in the guest" wait_for_monitor "$id" || return 1
    check "(j) finishing analysis $id answers 200 and leaves the status to the runner" finish_is_accepted_and_the_status_is_unchanged "$id"
    check "(j) finishing again while it is still running answers 200" finish_again_while_running_is_accepted "$id"
    check "(j) the analysis leaves running within $FINISH_LEAVES_RUNNING_SECONDS s" seconds_until_it_leaves_running "$id" || return 1
    check "(j) analysis $id reaches done" wait_for_status "$id" done "$ANALYSIS_TIMEOUT" || return 1
    check "(j) the finished analysis has a report" analysis_is_done_with_a_report "$id"
    check "(j) finishing a done analysis answers 409" finish_is_refused_with "$id" 409 "already over"
    finish_live_watch
    check "(j) the live statuses went through running to done, in order" ranked_statuses_never_go_back "$LIVE_SUMMARY"
    check "(j) the live socket closed with 1000, once" closed_normally_once "$LIVE_SUMMARY"
    check "(j) deleting analysis $id answers 204" delete_analysis "$id"
}
