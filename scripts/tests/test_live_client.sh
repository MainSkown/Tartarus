#!/usr/bin/env bash
# Tests what scripts/lib/live_client.py records of a live `events` message: the capemon calls under
# `ids` and `calls`, and the Sigma alerts apart under `alerts`, each with the call that triggered it.
# The alerts must stay out of `ids` and `calls`: those are compared with the final index's capemon
# events (scripts/lib/e2e-live.sh), which an alert is not.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

HARNESS=$(
    cat <<'PY'
import importlib.util, json, sys, types

# The client needs `websockets` only to open sockets, which this test never does.
for name in ("websockets", "websockets.asyncio", "websockets.asyncio.client", "websockets.typing"):
    sys.modules[name] = types.SimpleNamespace(ClientConnection=object, Subprotocol=str)
spec = importlib.util.spec_from_file_location("live_client", sys.argv[1])
live_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_client)

def event(event_id, action, kind="event", lane="registry", api=None, pid=100, rule=None, related=None):
    document = {
        "@timestamp": "2026-10-14T15:49:01.250Z",
        "event": {"id": event_id, "action": action, "kind": kind},
        "tartarus": {"lane": lane},
        "process": {"pid": pid},
    }
    if api:
        document["api"] = {"name": api}
    if rule:
        document["rule"] = rule
    if related:
        document["related"] = {"events": related}
    return document

def describe(*events):
    message = {"type": "events", "data": {"events": list(events), "dropped": 0}}
    return live_client.describe(message, 1.0, 0)

SIGMA = {"id": "6c17e2ec-0203-4f72-8760-b1b2a72336db", "ruleset": "sigma"}
exec(sys.stdin.read())
PY
)

# Runs the Python block on stdin with `describe(*events)` and the `event(...)` builder at hand.
describe_events() { python3 -I -c "$HARNESS" "$REPO/scripts/lib/live_client.py"; }

test_an_alert_is_recorded_apart_from_the_calls() {
    describe_events >"$WORK_DIR/out" 2>&1 <<'PY'
record = describe(
    event("c1", "reg-value-set", api="NtSetValueKey"),
    event("a1", "rule-matched", kind="alert", rule=SIGMA, related=["c1"]),
)
assert record["ids"] == ["c1"], record["ids"]
assert len(record["calls"]) == 1, record["calls"]
assert record["n"] == 2, record["n"]
print("ok")
PY
    grep -q '^ok$' "$WORK_DIR/out" || { cat "$WORK_DIR/out"; return 1; }
}

test_an_alert_carries_its_rule_and_the_call_that_triggered_it() {
    describe_events >"$WORK_DIR/out" 2>&1 <<'PY'
trigger = event("c1", "reg-value-set", api="NtSetValueKey")
record = describe(trigger, event("a1", "rule-matched", kind="alert", rule=SIGMA, related=["c1"]))
(alert,) = record["alerts"]
assert alert["rule_id"] == SIGMA["id"], alert
assert alert["ruleset"] == "sigma", alert
assert alert["related_ids"] == ["c1"], alert
assert alert["related_calls"] == [live_client.call_key(trigger)], alert
print("ok")
PY
    grep -q '^ok$' "$WORK_DIR/out" || { cat "$WORK_DIR/out"; return 1; }
}

test_a_trigger_that_is_not_in_the_batch_is_left_unresolved() {
    describe_events >"$WORK_DIR/out" 2>&1 <<'PY'
record = describe(event("a1", "rule-matched", kind="alert", rule=SIGMA, related=["elsewhere"]))
(alert,) = record["alerts"]
assert alert["related_ids"] == ["elsewhere"] and alert["related_calls"] == [], alert
print("ok")
PY
    grep -q '^ok$' "$WORK_DIR/out" || { cat "$WORK_DIR/out"; return 1; }
}

test_a_batch_without_alerts_records_an_empty_list() {
    describe_events >"$WORK_DIR/out" 2>&1 <<'PY'
record = describe(event("c1", "reg-value-set", api="NtSetValueKey"))
assert record["alerts"] == [], record["alerts"]
assert record["api"] == 0 or record["api"] == 1
print("ok")
PY
    grep -q '^ok$' "$WORK_DIR/out" || { cat "$WORK_DIR/out"; return 1; }
}

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
