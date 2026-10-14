# Helpers for scripts/e2e.sh: reporting, calling the analyses API through the frontend's
# published port, and waiting on analysis states with bounded waits. Sourced, not executed.
# Expects the caller to have cd'd to the repository root.

TERMINAL_STATES="done failed report_failed cancelled"
DEFAULT_OPTIONS='{}'
POLL_SECONDS=${E2E_POLL_SECONDS:-2}
# How long cleanup waits for an analysis that is still running: the longest a default run takes.
CLEANUP_WAIT_SECONDS=${E2E_CLEANUP_WAIT:-300}

failed=0
ok()   { printf '[ OK ] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=1; }
info() { printf '[INFO] %s\n' "$1"; }

# Runs a function and reports it; its stdout, if any, becomes the detail.
check() {
    local description=$1 detail
    shift
    if detail=$("$@" 2>&1); then ok "$description${detail:+ ($detail)}"
    else detail=${detail//$'\n'/; }; fail "$description${detail:+ ($detail)}"; return 1; fi
}

compose() { docker compose "$@"; }

in_words() { [[ " $2 " == *" $1 "* ]]; }

# --- HTTP -------------------------------------------------------------------

RESPONSE_FILE=$(mktemp)
HTTP_CODE=""

# Sets HTTP_CODE and writes the body to RESPONSE_FILE. Called directly, never in $(...), so
# the globals survive.
http() {
    local method=$1 path=$2
    shift 2
    HTTP_CODE=$(curl -s -m 60 -o "$RESPONSE_FILE" -w '%{http_code}' -X "$method" "$@" "$BASE$path") || HTTP_CODE=000
}

body() { cat "$RESPONSE_FILE"; }

# Reads one field of a JSON document on stdin; `.a.b` walks nested objects.
json_field() {
    python3 -I -c '
import json, sys
value = json.load(sys.stdin)
for key in sys.argv[1].strip(".").split("."):
    value = value[key]
print("null" if value is None else value)' "$1"
}

resolve_base_url() {
    local address
    address=$(compose port frontend 80 2>/dev/null) || return 1
    BASE=http://$address
}

health_status() { # component
    http GET /api/system/health
    [[ $HTTP_CODE == 200 ]] || { echo "unreachable"; return 0; }
    body | json_field ".$1.status" 2>/dev/null || echo "unreadable"
}

# --- analyses ---------------------------------------------------------------

# Sets SUBMITTED_ID; a global rather than output, so callers need no subshell and keep their state.
submit_sample() { # file [options-json]
    http POST /api/analyses -F "file=@$1" -F "options=${2:-$DEFAULT_OPTIONS}"
    [[ $HTTP_CODE == 201 ]] || { echo "POST /api/analyses answered $HTTP_CODE: $(body)" >&2; return 1; }
    SUBMITTED_ID=$(body | json_field .id)
}

analysis_field() { # id field
    http GET "/api/analyses/$1"
    [[ $HTTP_CODE == 200 ]] || { echo "GET /api/analyses/$1 answered $HTTP_CODE" >&2; return 1; }
    body | json_field ".$2"
}

analysis_status() { analysis_field "$1" status; }

# Waits until the analysis reaches one of the wanted states. A terminal state that is not wanted
# ends the wait at once, since it can never change; the timeout covers a hung CAPE.
wait_for_status() { # id "wanted states" timeout-seconds
    local id=$1 wanted=$2 deadline=$((SECONDS + $3)) status="?"
    while ((SECONDS < deadline)); do
        status=$(analysis_status "$id") || status="?"
        if in_words "$status" "$wanted"; then echo "$status"; return 0; fi
        if in_words "$status" "$TERMINAL_STATES"; then
            echo "analysis $id ended as '$status' (wanted: $wanted): $(analysis_field "$id" error)"
            return 1
        fi
        sleep "$POLL_SECONDS"
    done
    echo "analysis $id still '$status' after $3 s (wanted: $wanted)"
    return 1
}

wait_for_terminal() { wait_for_status "$1" "$TERMINAL_STATES" "$2"; }

# Waits for a health component to reach a status, e.g. cape down.
wait_for_health() { # component status timeout-seconds
    local deadline=$((SECONDS + $3)) current="?"
    while ((SECONDS < deadline)); do
        current=$(health_status "$1")
        [[ $current == "$2" ]] && { echo "$1 is $2"; return 0; }
        sleep "$POLL_SECONDS"
    done
    echo "$1 is still '$current' after $3 s (wanted: $2)"
    return 1
}

delete_analysis() { http DELETE "/api/analyses/$1"; [[ $HTTP_CODE == 204 ]] || { echo "DELETE answered $HTTP_CODE: $(body)"; return 1; }; }

cancel_when_queued() { # id
    [[ $(analysis_status "$1" 2>/dev/null) == queued ]] && http POST "/api/analyses/$1/cancel"
    return 0
}

# The API refuses to delete (409) an analysis that is still active, and only a queued one can be
# cancelled, so a running one is waited for, up to CLEANUP_WAIT_SECONDS.
remove_analysis() { # id
    local outcome
    http GET "/api/analyses/$1"
    [[ $HTTP_CODE == 404 ]] && return 0
    outcome=$(wait_for_terminal "$1" "$CLEANUP_WAIT_SECONDS") || { echo "$outcome; it was left behind"; return 1; }
    delete_analysis "$1"
}

# Queued analyses are cancelled first: behind a running one they would start as soon as it ends.
remove_analyses() { # id...
    local id left_behind=0
    for id; do cancel_when_queued "$id"; done
    for id; do remove_analysis "$id" || left_behind=1; done
    return "$left_behind"
}

reingest_answers() { # id expected-code
    http POST "/api/analyses/$1/reingest"
    [[ $HTTP_CODE == "$2" ]] || { echo "answered $HTTP_CODE (wanted $2): $(body)"; return 1; }
    echo "answered $HTTP_CODE"
}

analyses_of_sample() { # sha256 -> one analysis id per line
    http GET "/api/analyses?limit=200"
    body | json_eval '"\n".join(str(a["id"]) for a in v["items"] if a["sample_sha256"] == "'"$1"'")'
}

# Evaluates a Python expression over the JSON document `v` on stdin: json_eval 'len(v["items"])'.
json_eval() {
    python3 -I -c 'import json, sys; v = json.load(sys.stdin); print(eval(sys.argv[1]))' "$1"
}
