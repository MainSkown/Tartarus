# Assertions for scripts/e2e.sh on the live WebSocket (`/ws/analyses/{id}/live`) and the desktop
# tunnel (`/ws/analyses/{id}/desktop`). scripts/lib/live_client.py records what a socket sends and
# prints a JSON summary; the checks here read that summary. Sourced after e2e-api.sh and
# e2e-views.sh, whose json_assert reads RESPONSE_FILE, so each check copies its summary there.

LIVE_CLIENT=$REPO/scripts/lib/live_client.py
LIVE_FINAL_ID_LIMIT=10000
# A live run is calibrated to a rounded offset, the final index exactly: measured 4.1 to 4.9 s apart on one
# run, 4.4 to 7.1 s across eight (M3 plan, decision 8). The offset is constant within a run.
LIVE_CLOCK_MAX_OFFSET_SECONDS=${E2E_LIVE_CLOCK_MAX_OFFSET:-10}
LIVE_CLOCK_TOLERANCE_SECONDS=${E2E_LIVE_CLOCK_TOLERANCE:-1}
DESKTOP_FIRST_FRAME_SECONDS=${E2E_DESKTOP_FIRST_FRAME_SECONDS:-60}
DESKTOP_RUN_SECONDS=${E2E_DESKTOP_RUN_SECONDS:-120}
DESKTOP_BROWSER_SECONDS=${E2E_DESKTOP_BROWSER_SECONDS:-900}
# Final minus live may hold calls CAPE merged into a `repeated` count (live ids are best effort).

# --- running the client -----------------------------------------------------------------------

# The backend's environment has `websockets`; a host python that has it is used first, as it is faster.
live_client() { # mode id [client options]
    local mode=$1 id=$2
    shift 2
    if python3 -I -c 'import websockets' 2>/dev/null; then
        python3 -I "$LIVE_CLIENT" "$mode" "$BASE" "$id" "$@"
    else
        env -u VIRTUAL_ENV uv run --project backend --quiet python -I "$LIVE_CLIENT" "$mode" "$BASE" "$id" "$@"
    fi
}

# Follows an analysis from now on in the background, writing the summary to LIVE_SUMMARY[id].
watch_live_in_background() { # id [client options]
    local id=$1
    shift
    LIVE_SUMMARY=$WORK_DIR/live-$id.json
    live_client live "$id" --deadline "$((ANALYSIS_TIMEOUT + 60))" "$@" >"$LIVE_SUMMARY" 2>"$LIVE_SUMMARY.err" &
    LIVE_WATCH_PID=$!
}

finish_live_watch() {
    [[ -n ${LIVE_WATCH_PID:-} ]] && wait "$LIVE_WATCH_PID"
    LIVE_WATCH_PID=
}

stop_live_watch() { # for cleanup
    [[ -n ${LIVE_WATCH_PID:-} ]] && kill "$LIVE_WATCH_PID" 2>/dev/null
    return 0
}

# json_assert reads the last answer, so a summary becomes the last answer.
live_assert() { # summary-file; stdin: the Python block
    cp "$1" "$RESPONSE_FILE"
    json_assert
}

# Puts {"live": <summary>, "final": [<ids of the index's capemon events>], "final_calls": [...], "final_alerts": [...]}
# where json_assert reads it. An alert names its triggering events by id; each is resolved to the call it is, as the
# live client does for the alerts it saw, so the two sides can be compared by call and not by an id that may shift.
summary_with_index_ids() { # summary-file id
    local ids
    ids=$(opensearch_curl -XPOST -H 'content-type: application/json' \
        -d "{\"size\":$LIVE_FINAL_ID_LIMIT,\"_source\":[\"process.pid\",\"@timestamp\",\"event.action\",\"event.module\",\"event.kind\",\"api.name\",\"rule.id\",\"rule.ruleset\",\"related.events\"],\"query\":{\"bool\":{\"minimum_should_match\":1,\"should\":[{\"term\":{\"event.module\":\"capemon\"}},{\"bool\":{\"filter\":[{\"term\":{\"event.kind\":\"alert\"}},{\"term\":{\"rule.ruleset\":\"sigma\"}}]}}]}}}" \
        "localhost:9200/$(index_name "$2")/_search") || return 1
    python3 -I -c '
import json, sys
with open(sys.argv[1]) as summary:
    live = json.load(summary)
answer = json.loads(sys.argv[2])
if "hits" not in answer:
    sys.exit(f"OpenSearch answered {str(answer)[:200]}")
def call_key(source):
    process = source.get("process") or {}
    api = source.get("api") or {}
    return "|".join(str(part) for part in (process.get("pid"), source["@timestamp"], source["event"]["action"], api.get("name")))
hits = answer["hits"]["hits"]
calls = [hit for hit in hits if hit["_source"]["event"]["module"] == "capemon"]
call_by_id = {hit["_id"]: call_key(hit["_source"]) for hit in calls}
def alert_of(source):
    related_ids = source["related"]["events"]
    return {"rule_id": source["rule"]["id"], "related_ids": related_ids, "related_calls": [call_by_id[i] for i in related_ids if i in call_by_id]}
alerts = [alert_of(hit["_source"]) for hit in hits if hit["_source"]["event"]["kind"] == "alert"]
print(json.dumps({"live": live, "final": [hit["_id"] for hit in calls], "final_calls": list(call_by_id.values()), "final_alerts": alerts}))' "$1" "$ids" >"$RESPONSE_FILE"
}

# --- (h) the live feed of an analysis followed from submit to done -----------------------------

ranked_statuses_never_go_back() { # summary-file
    live_assert "$1" <<'PY'
rank = {"queued": 0, "starting": 1, "running": 2, "processing": 3, "ingesting": 4, "done": 5}
sequence = []
for message in v["messages"]:
    if message["type"] == "status" and (not sequence or sequence[-1] != message["status"]):
        sequence.append(message["status"])
unknown = [status for status in sequence if status not in rank]
assert not unknown, f"unexpected statuses {unknown}"
assert "running" in sequence, f"never running: {sequence}"
assert sequence[-1] == "done", f"the last status is {sequence[-1]}: {sequence}"
assert sequence.index("running") < len(sequence) - 1, f"no terminal status after running: {sequence}"
assert [rank[s] for s in sequence] == sorted(rank[s] for s in sequence), f"statuses out of order: {sequence}"
detail = " -> ".join(sequence)
PY
}

processes_arrive_in_order() { # summary-file sample-file-name
    live_assert "$1" <<PY
sample_name = "$2"
operations = [message for message in v["messages"] if message["type"] == "process"]
added = {}
for position, message in enumerate(operations):
    pid, op = message["pid"], message["op"]
    if op == "add":
        added.setdefault(pid, position)
    elif op == "end":
        assert pid in added, f"pid {pid} ended with no earlier add"
ended = {m["pid"] for m in operations if m["op"] == "end"}
samples = [m for m in operations if m["op"] == "add" and m["name"] == sample_name]
assert samples, f"no add for {sample_name}"
sample = samples[0]
children = [m for m in operations if m["op"] == "add" and m["name"] == "cmd.exe" and m["ppid"] == sample["pid"]]
assert children, f"no add for cmd.exe with parent {sample['pid']}"
for process in (sample, children[0]):
    assert process["pid"] in ended, f"{process['name']} ({process['pid']}) never ended"
detail = f"{len(added)} processes added, {len(ended)} ended; {sample_name} {sample['pid']} -> cmd.exe {children[0]['pid']}"
PY
}

live_events_are_in_the_final_index() { # summary-file id
    summary_with_index_ids "$1" "$2" || { echo "could not read the ids of $(index_name "$2")"; return 1; }
    json_assert <<PY
from datetime import datetime

live = v["live"]
final = set(v["final"])
events = [m for m in live["messages"] if m["type"] == "events"]
delivered = [event_id for m in events for event_id in m["ids"]]
live_ids = set(delivered)
assert sum(m["api"] for m in events) > 0, "include_api was asked for and no api event arrived"
assert sum(m["dropped"] for m in events) == 0, "the server dropped events for this client"
assert len(delivered) == len(live_ids), f"{len(delivered) - len(live_ids)} events were delivered twice"
assert len(final) < $LIVE_FINAL_ID_LIMIT, "the final index has more events than this check reads"
# CAPE merges consecutive identical calls and renumbers the rest, and the live path does not, so an id
# can shift after a merge. What must hold is that every call seen live exists in the final index.
# The final index calibrates the guest clock exactly and a live run only to a rounded offset (M3
# decision 8), so live times sit a constant few seconds off the final ones: a call is the same call
# when pid, action and API name match and the times differ by that run's offset, give or take
# $LIVE_CLOCK_TOLERANCE_SECONDS s.
shifted = live_ids - final

def split_call(call):
    pid, stamp, action, api = call.split("|")
    return (pid, action, api), datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()

def times_by_call(calls):
    grouped = {}
    for key, when in map(split_call, calls):
        grouped.setdefault(key, []).append(when)
    return grouped

final_times = times_by_call(v["final_calls"])
live_calls = [call for m in events for call in m["calls"]]
live_times = times_by_call(live_calls)
# A call made once on each side pins the offset; repeated identical calls could be matched a step off.
single = [when - final_times[key][0] for key, (when, *rest) in live_times.items() if key in final_times and not rest and len(final_times[key]) == 1]
assert single, "no call was made exactly once on each side, so the clock offset cannot be measured"
offset = sorted(single)[len(single) // 2]
assert abs(offset) <= $LIVE_CLOCK_MAX_OFFSET_SECONDS, f"live times are {offset:.1f} s off the final ones, more than the rounded calibration allows"
def same_call(live_when, final_when):
    return abs(live_when - final_when - offset) <= $LIVE_CLOCK_TOLERANCE_SECONDS

def live_without_final(live_by_key, final_by_key):
    return [key for key, whens in live_by_key.items() for when in whens if not any(same_call(when, other) for other in final_by_key.get(key, []))]

def final_without_live(final_by_key, live_by_key):
    return [key for key, whens in final_by_key.items() for when in whens if not any(same_call(other, when) for other in live_by_key.get(key, []))]

absent = live_without_final(live_times, final_times)
assert not absent, f"{len(absent)} live events have no matching call in the final index, e.g. {absent[:2]}"
never_live = final_without_live(final_times, live_times)
assert not never_live, f"{len(never_live)} calls of the final index never arrived live, e.g. {sorted(never_live)[:2]}"

# A Sigma alert is the same alert live and final when its rule and the call that triggered it are, the
# trigger's time carrying the same offset as any other call.
live_alerts = [alert for m in events for alert in m["alerts"] if alert["ruleset"] == "sigma"]
final_alerts = v["final_alerts"]
for side, alerts, where in (("live", live_alerts, "its batch"), ("final", final_alerts, "the capemon events of the index")):
    unresolved = [alert["rule_id"] for alert in alerts if not alert["related_ids"] or len(alert["related_calls"]) != len(alert["related_ids"])]
    assert not unresolved, f"{side} Sigma alerts of rules {unresolved} name an event that is not in {where}"

def alert_calls(alerts):
    return times_by_call(f"{alert['rule_id'].lower()}/{call}" for alert in alerts for call in alert["related_calls"])

live_alert_times, final_alert_times = alert_calls(live_alerts), alert_calls(final_alerts)
unmatched_live = live_without_final(live_alert_times, final_alert_times)
assert not unmatched_live, f"{len(unmatched_live)} Sigma alerts seen live have no match in the final index, e.g. {unmatched_live[:2]}"
unmatched_final = final_without_live(final_alert_times, live_alert_times)
assert not unmatched_final, f"{len(unmatched_final)} Sigma alerts of the final index never arrived live, e.g. {sorted(unmatched_final)[:2]}"
missing = final - live_ids
detail = f"{len(live_ids)} live events, {len(final)} capemon events in the index, {len(missing)} not seen live under their id, {len(shifted)} live ids shifted by merged repeats; live times {offset:.1f} s off the final ones; {len(live_alerts)} Sigma alerts live and {len(final_alerts)} final, matched by rule and triggering call"
if missing:
    detail += ": " + ", ".join(sorted(missing))
PY
}

# The Outcome promises a live match reaches the feed in the batch of the event that caused it.
live_feed_saw_the_alert_of_rule() { # summary-file rule-id
    live_assert "$1" <<PY
rule = "$2"
arrivals = [(m["t"], alert) for m in v["messages"] if m["type"] == "events" for alert in m["alerts"] if alert["ruleset"] == "sigma" and alert["rule_id"] == rule]
assert arrivals, f"no live alert of rule {rule}"
assert len(arrivals) == 1, f"{len(arrivals)} live alerts of rule {rule}; the sample triggers it once"
at, alert = arrivals[0]
assert alert["related_ids"] and len(alert["related_calls"]) == len(alert["related_ids"]), f"the event it names is not in its batch: {alert['related_ids']}"
detail = f"arrived at {at} s with its triggering event in the same batch"
PY
}

phase_final_is_last_and_single() { # summary-file
    live_assert "$1" <<'PY'
messages = v["messages"]
phases = [m for m in messages if m["type"] == "phase"]
assert len(phases) == 1, f"{len(phases)} phase messages"
assert phases[0]["phase"] == "final", f"phase is {phases[0]['phase']}"
assert messages[-1]["type"] == "phase", f"the last message is {messages[-1]['type']}"
detail = "arrived once, last"
PY
}

closed_normally_once() { # summary-file
    live_assert "$1" <<'PY'
codes = [connection["code"] for connection in v["connections"]]
assert not v["timed_out"], "the client gave up waiting"
assert codes == [1000], f"close codes {codes}"
detail = "1000"
PY
}

no_unexpected_errors() { # summary-file
    live_assert "$1" <<'PY'
errors = [m["code"] for m in v["messages"] if m["type"] == "error" and m["code"] != "query_unsupported"]
assert not errors, f"error messages: {errors}"
detail = "none besides the refused query"
PY
}

events_began_before_processing() { # summary-file
    live_assert "$1" <<'PY'
messages = v["messages"]
first_events = next((m for m in messages if m["type"] == "events"), None)
processing = next((m for m in messages if m["type"] == "status" and m["status"] == "processing"), None)
assert first_events, "no events message at all"
assert processing, "the status never became processing"
assert messages.index(first_events) < messages.index(processing), "events only after processing began"
running = next(m for m in messages if m["type"] == "status" and m["status"] == "running")
detail = f"running at {running['t']} s, first events at {first_events['t']} s, processing at {processing['t']} s"
PY
}

query_is_refused_and_the_stream_goes_on() { # summary-file
    live_assert "$1" <<'PY'
messages = v["messages"]
refusals = [position for position, m in enumerate(messages) if m["type"] == "error" and m["code"] == "query_unsupported"]
assert len(refusals) == 1, f"{len(refusals)} query_unsupported errors"
later = [m["type"] for m in messages[refusals[0] + 1 :]]
assert "status" in later and "phase" in later, f"nothing useful after the refusal: {sorted(set(later))}"
detail = f"{len(later)} messages followed it"
PY
}

# A client that connects to a finished analysis: the status, the phase and the close, no events.
finished_analysis_replays_only_the_end() { # id
    local file=$WORK_DIR/live-late-$1.json
    live_client live "$1" --deadline 30 >"$file" || { echo "the client failed"; return 1; }
    live_assert "$file" <<'PY'
types = [m["type"] for m in v["messages"]]
codes = [connection["code"] for connection in v["connections"]]
assert codes == [1000], f"close codes {codes}"
assert types[0] == "status" and v["messages"][0]["status"] == "done", f"first message {v['messages'][:1]}"
assert types.count("phase") == 1 and types[-1] == "phase", f"messages {types}"
assert "events" not in types, "a finished analysis sent events"
detail = f"{types}, closed 1000"
PY
}

unknown_analysis_closes_4404() {
    local file=$WORK_DIR/live-unknown.json
    live_client live 999999 --deadline 30 >"$file" || { echo "the client failed"; return 1; }
    live_assert "$file" <<'PY'
codes = [connection["code"] for connection in v["connections"]]
assert codes == [4404], f"close codes {codes}"
assert not v["messages"], f"messages arrived: {v['messages']}"
detail = "4404, nothing sent"
PY
}

check_live_feed() { # id summary-file sample-file-name
    local id=$1 summary=$2 sample=$3
    check "(h) the live status goes through running to done, in order" ranked_statuses_never_go_back "$summary"
    check "(h) process add messages arrive for the sample and its cmd.exe child, each end after its add" processes_arrive_in_order "$summary" "$sample"
    check "(h) every call seen live is in the final index, ids may shift where CAPE merged repeats, and the Sigma alerts agree by rule and triggering call" live_events_are_in_the_final_index "$summary" "$id"
    check "(h) the self-test rule's Sigma alert arrived live once, in the batch of the event that triggered it" live_feed_saw_the_alert_of_rule "$summary" "$SELFTEST_RULE_ID"
    check "(h) the first events arrived before the status was processing" events_began_before_processing "$summary"
    check "(h) phase final arrived once, as the last message" phase_final_is_last_and_single "$summary"
    check "(h) the socket closed with 1000, once" closed_normally_once "$summary"
    check "(h) no error message arrived besides the refused query" no_unexpected_errors "$summary"
    check "(h) a subscribe with a query is refused with query_unsupported and the stream goes on" query_is_refused_and_the_stream_goes_on "$summary"
    check "(h) a client connecting after the run gets status, phase final and 1000, no events" finished_analysis_replays_only_the_end "$id"
    check "(h) /ws/analyses/999999/live closes with 4404" unknown_analysis_closes_4404
}

# --- (f) a live client across a backend restart -------------------------------------------------

live_client_survived_the_restart() { # summary-file id
    summary_with_index_ids "$1" "$2" || { echo "could not read the ids of $(index_name "$2")"; return 1; }
    json_assert <<PY
live = v["live"]
final = set(v["final"])
connections = live["connections"]
codes = [connection["code"] for connection in connections]
assert not live["timed_out"], "the client gave up before the run ended"
assert len(connections) >= 2, f"it never had to reconnect: close codes {codes}"
assert codes[-1] == 1000, f"the last connection closed with {codes[-1]}"
phases = [m for m in live["messages"] if m["type"] == "phase"]
assert phases, "phase final never arrived"
seen = {event_id for m in live["messages"] if m["type"] == "events" for event_id in m["ids"]}
unknown = seen - final
assert seen, "no event arrived at all"
assert not unknown, f"{len(unknown)} of the {len(seen)} events seen are not in the final index"
after_restart = sum(m["n"] for m in live["messages"] if m["type"] == "events" and m["conn"] == len(connections) - 1)
# The runner restarts the collector for a running analysis it resumes, and the collector re-reads the logs.
assert after_restart > 0, "the reconnected socket received no event: the collector did not resume"
detail = f"close codes {codes}, {len(seen)} distinct events seen of {len(final)}, {after_restart} on the last connection"
PY
}

# --- (i) the interactive desktop -----------------------------------------------------------------

desktop_stream_behaves() { # summary-file
    live_assert "$1" <<PY
import re
assert v["error"] is None, f"could not connect: {v['error']}"
assert re.fullmatch(r"0\.,36\.[0-9a-f-]{36};", v["first_frame"] or ""), f"first frame {v['first_frame']!r}"
first = v["first_display_at"]
assert first is not None, f"no size or img instruction; opcodes {v['opcodes']}"
assert first < $DESKTOP_FIRST_FRAME_SECONDS, f"the first frame came after {first:.1f} s"
assert v["clipboard_sent_at"] is not None, "the clipboard instruction was never sent"
assert not v["clipboard_replies"], f"clipboard came back: {v['clipboard_replies']}"
assert v["ping_echoed"], "the tunnel stopped answering after the clipboard instruction"
assert not v["timed_out"], "the socket outlived the run"
assert v["close_code"] == 1000, f"close code {v['close_code']} ({v['close_reason']})"
# An interactive run lasts its whole timeout (some of it may be over when the client connects), so a much earlier end is a dropped stream.
assert v["closed_at"] >= 0.75 * $DESKTOP_RUN_SECONDS, f"closed after {v['closed_at']:.0f} s, long before the {$DESKTOP_RUN_SECONDS} s run could end: {v['errors']}"
# guacd reports the guest's VNC going away (515, 519) at the end of the run, a moment before the status moves on.
stray = [error for error in v["errors"] if error[1] not in ("515", "519")]
assert not stray, f"guacd reported {stray}"
detail = f"first frame {v['first_display_at']:.1f} s after connecting, closed 1000 {v['closed_at']:.0f} s in ({v['close_reason']})"
PY
}

desktop_refuses_a_finished_analysis() { # id
    local file=$WORK_DIR/desktop-late-$1.json
    live_client desktop "$1" --deadline 30 >"$file" || { echo "the client failed"; return 1; }
    live_assert "$file" <<'PY'
assert v["close_code"] == 4409, f"close code {v['close_code']}"
assert v["first_display_at"] is None, "a frame arrived"
detail = f"4409 ({v['close_reason']})"
PY
}

desktop_api_flow() {
    local id file
    submit_sample "$(unique_sample e2e-i.exe)" '{"interactive": true, "route": "inetsim", "timeout": '"$DESKTOP_RUN_SECONDS"'}' &&
        remember "$SUBMITTED_ID" || { fail "(i) submitting the interactive analysis"; return 1; }
    id=$SUBMITTED_ID
    file=$WORK_DIR/desktop-$id.json
    check "(i) interactive analysis $id is running" wait_for_running "$id" || return 1
    live_client desktop "$id" --clipboard --deadline "$((ANALYSIS_TIMEOUT + 60))" >"$file" || { fail "(i) the desktop client failed"; return 1; }
    check "(i) the desktop tunnel starts with the internal instruction, delivers a frame, ignores a clipboard instruction and closes 1000 with the run" \
        desktop_stream_behaves "$file"
    check "(i) analysis $id reaches done" wait_for_status "$id" done "$ANALYSIS_TIMEOUT" || return 1
    check "(i) the desktop of the finished analysis closes with 4409" desktop_refuses_a_finished_analysis "$id"
    check "(i) deleting analysis $id answers 204" delete_analysis "$id"
}
