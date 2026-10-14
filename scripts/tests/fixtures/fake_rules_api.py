"""A stand-in for the rules and analysis API, small enough to read, used by test_e2e_rules.sh.

It answers what scripts/lib/e2e-rules.sh calls for one finished analysis (id 7): the rules, the
events search that finds the self-test rule's alert, the alert's related event, the detections, the
per-rule hits and the re-ingest, after which the alert exists only while the rule is enabled.
`python3 fake_rules_api.py <port> [fault ...]` serves a correct API; each fault names one way it
goes wrong, so the test can show the matching check fails. `GET /calls` lists the requests seen.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

ANALYSIS_ID = 7
SELFTEST_ID = "6c17e2ec-0203-4f72-8760-b1b2a72336db"
SELFTEST_TITLE = "Tartarus Self-Test Registry Marker Written"
REGISTRY_PATH = "HKEY_CURRENT_USER\\Software\\Tartarus\\SelfTest"
REINGEST_POLLS = 2
FAULTS = set(sys.argv[2:])
CALLS: list[str] = []


def make_rules():
    count = 30 if "too_few_rules" in FAULTS else 60
    rules = [
        {
            "id": f"00000000-0000-4000-8000-{number:012d}",
            "title": f"Shipped rule {number}",
            "level": "medium",
            "status": "test",
            "validity": "valid",
            "error": None,
            "enabled": True,
            "path": f"/rules/sigma/default/process_creation/rule_{number}.yml",
            "hits": 0,
        }
        for number in range(count)
    ]
    if "shipped_invalid" in FAULTS:
        rules[3] |= {"validity": "invalid", "error": "the condition names a missing selection"}
    if "tartarus_missing" not in FAULTS:
        rules.append(
            {
                "id": SELFTEST_ID,
                "title": SELFTEST_TITLE,
                "level": "informational",
                "status": "stable",
                "validity": "valid",
                "error": None,
                "enabled": "tartarus_disabled" not in FAULTS,
                "path": "/rules/sigma/tartarus/tartarus_selftest_registry_marker.yml",
                "hits": 1,
            }
        )
    return rules


RULES = make_rules()


class State:
    status = "done"
    polls_left = 0
    alerts = 1


def selftest_rule():
    return next((rule for rule in RULES if rule["id"] == SELFTEST_ID), {"enabled": True})


def alert_count_after_ingest():
    if "two_alerts" in FAULTS:
        return 2
    if "no_alert" in FAULTS:
        return 0
    if not selftest_rule()["enabled"]:
        return 1 if "alert_survives_disable" in FAULTS else 0
    return 0 if "detection_not_restored" in FAULTS and State.alerts == 0 else 1


State.alerts = alert_count_after_ingest()


class BadRequest(Exception):
    def __init__(self, code, status=404):
        self.code, self.status = code, status


def analysis_record():
    if State.status == "ingesting":
        State.polls_left -= 1
        if State.polls_left <= 0 and "reingest_stuck" not in FAULTS:
            State.status = "done"
            State.alerts = alert_count_after_ingest()
    return {
        "id": ANALYSIS_ID,
        "filename": "e2e-a.exe",
        "status": State.status,
        "error": None,
        "event_count": 10,
        "summary": {"lane_counts": {"registry": 10}},
    }


def reingest():
    if "reingest_refused" in FAULTS:
        raise BadRequest("conflict", 409)
    State.status, State.polls_left = "ingesting", REINGEST_POLLS
    return {"id": ANALYSIS_ID, "status": State.status}


def alert_event(number):
    return {
        "id": f"alert-{number}",
        "lane": "registry",
        "kind": "alert",
        "action": "rule-matched",
        "rule_name": SELFTEST_TITLE,
        "rule_ruleset": "sigma",
    }


def search(body):
    query = body.get("query", "")
    if "rule.ruleset:sigma" not in query:
        return {"events": [], "total": 0, "next_cursor": None}
    count = State.alerts
    return {"events": [alert_event(n) for n in range(count)][: body.get("size", 100)], "total": count, "next_cursor": None}


def trigger_event():
    wrong_action = "alert_not_registry" in FAULTS
    wrong_path = "wrong_registry_path" in FAULTS
    return {
        "id": "reg-1",
        "lane": "registry",
        "kind": "event",
        "action": "file-write" if wrong_action else "reg-value-set",
        "registry_path": REGISTRY_PATH + ("Other" if wrong_path else ""),
    }


def event_detail(event_id):
    listing = lambda items: {"items": items, "total": len(items)}
    return {
        "event": alert_event(0),
        "source": {"rule": {"id": SELFTEST_ID, "ruleset": "sigma"}, "related": {"events": ["reg-1"]}},
        "related": {"references": listing([trigger_event()]), "referenced_by": listing([])},
    }


def detections():
    groups = [{"ruleset": "cape", "detections": [{"name": "A CAPE signature", "related_events": []}]}]
    if State.alerts and "no_sigma_group" not in FAULTS:
        sigma = {"name": SELFTEST_TITLE, "related_events": [{"id": "reg-1", "action": trigger_event()["action"]}]}
        groups.append({"ruleset": "sigma", "detections": [sigma] * State.alerts})
    return {"groups": groups, "total": sum(len(group["detections"]) for group in groups)}


def hits():
    if "hits_missing" in FAULTS or (State.alerts == 0 and "hits_keep_disabled" not in FAULTS):
        return []
    return [{"rule_id": SELFTEST_ID, "count": 2 if "hits_count_two" in FAULTS else max(State.alerts, 1)}]


def update_rule(rule_id, body):
    rule = next((rule for rule in RULES if rule["id"] == rule_id), None)
    if rule is None:
        raise BadRequest("not_found")
    wanted = body["enabled"]
    ignored = "enable_ignored" if wanted else "disable_ignored"
    if ignored not in FAULTS:
        rule["enabled"] = wanted
    return rule


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")

    def route(self, method):
        parts = unquote(urlparse(self.path).path).strip("/").split("/")
        if parts == ["calls"]:
            return CALLS
        CALLS.append(f"{method} /{'/'.join(parts)}")
        if parts[:2] == ["api", "rules"]:
            return self.rules_route(method, parts[2:])
        if parts[:2] != ["api", "analyses"] or int(parts[2]) != ANALYSIS_ID:
            raise BadRequest("not_found")
        rest = parts[3:]
        routes = {
            ("GET", ()): analysis_record,
            ("POST", ("reingest",)): reingest,
            ("GET", ("detections",)): detections,
            ("GET", ("rules", "hits")): hits,
        }
        if (method, tuple(rest)) in routes:
            return routes[(method, tuple(rest))]()
        if method == "POST" and rest == ["events", "search"]:
            return search(self.body())
        if method == "GET" and rest[:1] == ["events"]:
            return event_detail("/".join(rest[1:]))
        raise BadRequest("not_found")

    def rules_route(self, method, rest):
        if method == "GET" and not rest:
            return RULES
        if method == "GET":
            return next((rule for rule in RULES if rule["id"] == rest[0]), None) or self.missing()
        if method == "PATCH":
            return update_rule(rest[0], self.body())
        raise BadRequest("not_found")

    def missing(self):
        raise BadRequest("not_found")

    def handle_method(self, method):
        try:
            self.reply(200, self.route(method))
        except BadRequest as problem:
            self.reply(problem.status, {"error": {"code": problem.code, "message": problem.code}})

    def do_GET(self):
        self.handle_method("GET")

    def do_POST(self):
        self.handle_method("POST")

    def do_PATCH(self):
        self.handle_method("PATCH")

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
