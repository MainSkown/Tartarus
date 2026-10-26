#!/usr/bin/env bash
# Tests live_events_are_in_the_final_index (scripts/lib/e2e-live.sh): live API calls are the final
# index's calls with the clock offset between the rounded live calibration and the exact final one.
# The index and the live summary are replaced by a document written where json_assert reads it; the
# document the real summary_with_index_ids builds from an OpenSearch answer is tested apart.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cd "$REPO" || exit 1
source "$REPO/scripts/lib/e2e-api.sh"
source "$REPO/scripts/lib/e2e-views.sh"
source "$REPO/scripts/lib/e2e-rules.sh"
source "$REPO/scripts/lib/e2e-live.sh"

eval "$(declare -f summary_with_index_ids | sed '1s/^summary_with_index_ids/summary_of_the_index_answer/')"

# What summary_with_index_ids builds from a real run: the live summary and the index's capemon calls.
summary_with_index_ids() { cp "$WORK_DIR/document.json" "$RESPONSE_FILE"; }

# Writes the document: the final calls are 20 calls of pid 180 half a second apart (six distinct, the rest one repeated call); the live ones are the same
# calls `offset` seconds early, minus those in `drop_live`, plus `extra_live` calls the index has not got. The Sigma alert of the self-test
# rule names call 3 on both sides, except as `alerts` says: agree, live_only, final_only, other_trigger (final names call 4), other_rule,
# unresolved (the live batch lacks the named event).
write_document() { # offset drop_live extra_live drop_final [alerts]
    python3 -I - "$@" >"$WORK_DIR/document.json" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone

offset, drop_live, extra_live, drop_final = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
alerts = sys.argv[5] if len(sys.argv) > 5 else "agree"
start = datetime(2026, 10, 14, 15, 49, 0, tzinfo=timezone.utc)
RULE = "6c17e2ec-0203-4f72-8760-b1b2a72336db"

def call(index, shift=0.0, name=None):
    name = name or (f"NtCall{index}" if index < 6 else "NtOpenKey")
    when = start + timedelta(seconds=index * 0.5 + shift)
    return f"180|{when.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z|api-call|{name}"

final_calls = [call(i) for i in range(20)][drop_final:]
live_calls = [call(i, -offset) for i in range(20)][drop_live:] + [call(i, -offset, "NtNeverInTheIndex") for i in range(extra_live)]
ids = [f"id{i}" for i in range(20)]
live_alert = {"id": "live-alert", "rule_id": RULE, "ruleset": "sigma", "related_ids": ["id3"], "related_calls": [call(3, -offset)]}
final_alert = {"rule_id": RULE, "related_ids": ["id3"], "related_calls": [call(3)]}
if alerts == "other_trigger":
    final_alert = final_alert | {"related_ids": ["id4"], "related_calls": [call(4)]}
if alerts == "other_rule":
    final_alert = final_alert | {"rule_id": "00000000-0000-4000-8000-000000000001"}
if alerts == "unresolved":
    live_alert = live_alert | {"related_calls": []}
live_alerts = [] if alerts in ("final_only",) else [live_alert]
final_alerts = [] if alerts == "live_only" else [final_alert]
live = {"messages": [{"type": "events", "ids": ids, "calls": live_calls, "api": 20, "dropped": 0, "n": 20, "conn": 0, "alerts": live_alerts}]}
print(json.dumps({"live": live, "final": ids, "final_calls": final_calls, "final_alerts": final_alerts}))
PY
}

passes() { write_document "$@" && live_events_are_in_the_final_index "$WORK_DIR/summary.json" 1 >"$WORK_DIR/out" 2>&1; }
fails_saying() { # words, then document arguments
    local words=$1
    shift
    write_document "$@" && ! live_events_are_in_the_final_index "$WORK_DIR/summary.json" 1 >"$WORK_DIR/out" 2>&1 && grep -q "$words" "$WORK_DIR/out"
}

test_live_calls_a_constant_few_seconds_early_are_the_final_calls() { passes 4.8 0 0 0; }
test_live_calls_on_the_same_clock_are_the_final_calls() { passes 0 0 0 0; }
test_the_offset_is_reported() { passes 4.8 0 0 0 && grep -q "4.8 s off" "$WORK_DIR/out"; }
test_a_live_call_the_index_does_not_have_is_caught() { fails_saying "no matching call in the final index" 4.8 0 2 0; }
test_a_final_call_that_never_arrived_live_is_caught() { fails_saying "never arrived live" 4.8 3 0 0; }
test_an_offset_beyond_the_rounded_calibration_is_caught() { fails_saying "off the final ones" 12 0 0 0; }
test_a_sigma_alert_on_the_same_trigger_live_and_final_agrees() { passes 4.8 0 0 0 agree && grep -q "1 Sigma alert" "$WORK_DIR/out"; }
test_a_sigma_alert_that_never_reached_the_final_index_is_caught() { fails_saying "Sigma alerts seen live have no match" 4.8 0 0 0 live_only; }
test_a_sigma_alert_of_the_final_index_that_never_arrived_live_is_caught() { fails_saying "Sigma alerts of the final index never arrived live" 4.8 0 0 0 final_only; }
test_a_sigma_alert_on_another_trigger_is_caught() { fails_saying "Sigma alerts seen live have no match" 4.8 0 0 0 other_trigger; }
test_a_sigma_alert_of_another_rule_is_caught() { fails_saying "Sigma alerts seen live have no match" 4.8 0 0 0 other_rule; }
test_a_sigma_alert_whose_trigger_was_not_in_its_batch_is_caught() { fails_saying "not in its batch" 4.8 0 0 0 unresolved; }

# --- the self-test alert seen live ---

SELFTEST=6c17e2ec-0203-4f72-8760-b1b2a72336db

# A live summary of one events message at 12.5 s holding the given alerts (python list literal).
write_summary() { # alerts
    python3 -I - "$1" >"$WORK_DIR/summary.json" <<'PY'
import json, sys
alerts = eval(sys.argv[1])
print(json.dumps({"messages": [{"type": "events", "t": 12.5, "conn": 0, "n": 3, "ids": [], "calls": [], "api": 0, "dropped": 0, "alerts": alerts}]}))
PY
}

ALERT="{'rule_id': '$SELFTEST', 'ruleset': 'sigma', 'related_ids': ['c'], 'related_calls': ['k']}"
saw_selftest_alert() { live_feed_saw_the_alert_of_rule "$WORK_DIR/summary.json" "$SELFTEST" >"$WORK_DIR/out" 2>&1; }

test_one_alert_of_the_rule_with_its_trigger_in_the_batch_is_seen_live() { write_summary "[$ALERT]" && saw_selftest_alert && grep -q "12.5 s" "$WORK_DIR/out"; }
test_no_alert_at_all_is_caught() { write_summary "[]" && ! saw_selftest_alert && grep -q "no live alert" "$WORK_DIR/out"; }
test_an_alert_of_another_rule_does_not_count() {
    write_summary "[{**$ALERT, 'rule_id': 'other'}]" && ! saw_selftest_alert && grep -q "no live alert" "$WORK_DIR/out"
}
test_a_cape_alert_with_the_same_rule_id_does_not_count() {
    write_summary "[{**$ALERT, 'ruleset': 'cape'}]" && ! saw_selftest_alert && grep -q "no live alert" "$WORK_DIR/out"
}
test_the_same_alert_twice_is_caught() { write_summary "[$ALERT, $ALERT]" && ! saw_selftest_alert && grep -q "2 live alerts" "$WORK_DIR/out"; }
test_an_alert_without_its_trigger_in_the_batch_is_caught() {
    write_summary "[{**$ALERT, 'related_calls': []}]" && ! saw_selftest_alert && grep -q "not in its batch" "$WORK_DIR/out"
}

# --- the index side of the summary ---

# OpenSearch's answer for the capemon calls, the final-phase events and the Sigma alerts of an index: two calls, one Sysmon event,
# an alert naming the first call, an alert whose trigger is not in the index, and an alert naming the Sysmon event.
canned_answer() {
    python3 -I - <<'PY'
import json
def call(identifier, action, api):
    return {"_id": identifier, "_source": {"@timestamp": "2026-10-14T15:49:01.250Z", "process": {"pid": 180}, "event": {"id": identifier, "action": action, "module": "capemon", "kind": "event"}, "api": {"name": api}}}
def alert(identifier, rule, related):
    return {"_id": identifier, "_source": {"@timestamp": "2026-10-14T15:49:01.250Z", "event": {"id": identifier, "action": "rule-matched", "module": "sigma", "kind": "alert"}, "rule": {"id": rule, "ruleset": "sigma"}, "related": {"events": related}}}
def final_only(identifier, module):
    return {"_id": identifier, "_source": {"@timestamp": "2026-10-14T15:49:01.250Z", "process": {"pid": 180}, "event": {"id": identifier, "action": "reg-value-set", "module": module, "kind": "event"}}}
import os
extra = [final_only(f"v{n}", "volatility") for n in range(int(os.environ.get("EXTRA_FINAL_EVENTS", "0")))]
hits = extra + [call("c1", "reg-value-set", "NtSetValueKey"), call("c2", "file-write", "NtWriteFile"), final_only("s1", "sysmon"), alert("a1", "rule-one", ["c1"]), alert("a2", "rule-two", ["gone"]), alert("a3", "rule-three", ["s1"])]
print(json.dumps({"hits": {"hits": hits}}))
PY
}

opensearch_curl() { canned_answer; }

index_summary() {
    summary_of_the_index_answer "$WORK_DIR/live.json" 1 && cp "$RESPONSE_FILE" "$WORK_DIR/index-summary.json"
}

test_the_index_summary_keeps_capemon_calls_apart_from_alerts() {
    echo '{"messages": []}' >"$WORK_DIR/live.json"
    index_summary && python3 -I - "$WORK_DIR/index-summary.json" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1]))
assert summary["final"] == ["c1", "c2"], summary["final"]
assert len(summary["final_calls"]) == 2, summary["final_calls"]
PY
}

test_the_index_summary_names_the_call_behind_each_alert() {
    echo '{"messages": []}' >"$WORK_DIR/live.json"
    index_summary && python3 -I - "$WORK_DIR/index-summary.json" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1]))
by_rule = {alert["rule_id"]: alert for alert in summary["final_alerts"]}
assert by_rule["rule-one"]["related_calls"] == [summary["final_calls"][0]], by_rule["rule-one"]
assert by_rule["rule-two"]["related_ids"] == ["gone"] and by_rule["rule-two"]["related_calls"] == [], by_rule["rule-two"]
PY
}

test_an_alert_on_a_final_phase_event_is_not_compared_with_the_live_feed() {
    echo '{"messages": []}' >"$WORK_DIR/live.json"
    index_summary && python3 -I - "$WORK_DIR/index-summary.json" <<'PY'
import json, sys
rules = {alert["rule_id"] for alert in json.load(open(sys.argv[1]))["final_alerts"]}
assert rules == {"rule-one", "rule-two"}, rules
PY
}

test_the_rules_whose_final_alert_names_only_final_phase_events_are_listed() {
    echo '{"messages": []}' >"$WORK_DIR/live.json"
    index_summary && python3 -I - "$WORK_DIR/index-summary.json" <<'PY'
import json, sys
rules = json.load(open(sys.argv[1]))["final_only_alert_rules"]
assert rules == ["rule-three"], rules
PY
}

test_an_answer_too_big_for_one_command_line_argument_is_still_read() {
    echo '{"messages": []}' >"$WORK_DIR/live.json"
    EXTRA_FINAL_EVENTS=3000 index_summary && python3 -I - "$WORK_DIR/index-summary.json" <<'PY'
import json, sys
assert json.load(open(sys.argv[1]))["final"] == ["c1", "c2"]
PY
}

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; cat "$WORK_DIR/out" 2>/dev/null | head -3; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
