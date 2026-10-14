"""A stand-in for the analysis and events API, small enough to read, used by test_e2e_query.sh.

It answers the endpoints scripts/lib/e2e-query.sh calls over 250 generated events, for the query
forms that script sends. `python3 fake_events_api.py <port> [fault ...]` serves a correct API;
each fault names one way the API goes wrong, so the test can show the matching check fails.
"""

import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ANALYSIS_ID = 7
SAMPLE_NAME = "e2e-a.exe"
LANES = ["process", "file", "network", "registry", "api"]
FIRST_TIME = datetime(2026, 10, 13, 22, 47, 27, tzinfo=timezone.utc)
ALERT_POSITIONS = (10, 20, 30)
FAULTS = set(sys.argv[2:])


def isoformat(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"


def make_events():
    events = []
    for position in range(250):
        lane = "process" if position in ALERT_POSITIONS else LANES[position % len(LANES)]
        process = None if lane == "network" else (SAMPLE_NAME if position % 2 == 0 else "cmd.exe")
        events.append(
            {
                "id": f"evt-{position:04d}",
                "time": isoformat(FIRST_TIME + timedelta(milliseconds=50 * position)),
                "sequence": position,
                "lane": lane,
                "kind": "alert" if position in ALERT_POSITIONS else "event",
                "summary": f"{lane} activity of {process or 'the network'}",
                "process": None if process is None else {"pid": 100 + position % 2, "name": process, "entity_id": None},
                "command_line": f"C:\\Windows\\{process}" if process and lane in ("process", "api") else None,
                "references": [f"evt-{position - 1:04d}", f"evt-{position - 2:04d}"] if position in ALERT_POSITIONS else [],
            }
        )
    return events


EVENTS = make_events()
BY_ID = {event["id"]: event for event in EVENTS}


def public(event, columns=()):
    fields = {}
    if "process.command_line" in columns and event["command_line"] and "columns_ignored" not in FAULTS:
        fields["process.command_line"] = event["command_line"]
    return {key: event[key] for key in ("id", "time", "sequence", "lane", "kind", "summary", "process")} | {"fields": fields}


def lane_counts():
    counts = {}
    for event in EVENTS:
        counts[event["lane"]] = counts.get(event["lane"], 0) + 1
    return counts


def analysis_record():
    return {
        "id": ANALYSIS_ID,
        "filename": SAMPLE_NAME,
        "status": "done",
        "event_count": len(EVENTS),
        "summary": {"lane_counts": lane_counts(), "signatures": [{"name": "s", "severity": "high", "description": "d"}]},
    }


class BadRequest(Exception):
    def __init__(self, code, status=422, details=None):
        self.code, self.status, self.details = code, status, details or {}


def query_error(text):
    if "((" in text:
        return [{"start": 1, "end": 2, "message": "the query ends where a term is expected", "suggestion": None}]
    if text.startswith("procss"):
        return [{"start": 0, "end": 6, "message": "unknown field 'procss'; did you mean 'process'?", "suggestion": "process"}]
    return []


def matches_query(event, text):
    text = text.strip()
    name = (event["process"] or {}).get("name", "")
    if text == "":
        return True
    field, separator, value = text.partition(":")
    value = value.strip('"')
    if separator and field == "lane":
        return "lane_query_ignored" in FAULTS or event["lane"] == value
    if separator and field == "kind":
        return event["kind"] == value
    if separator and field == "process.command_line" and value == "*":
        return event["command_line"] is not None
    if separator and field in ("proc", "process.name"):
        if field == "proc" and "alias_ignored" in FAULTS:
            return True
        return name.lower() == value.lower()
    if "free_text_finds_nothing" in FAULTS:
        return False
    needle = text.strip('"').lower()
    return needle in event["summary"].lower() or needle in (event["command_line"] or "").lower()


def chip_field(chip):
    return {"lane": "tartarus.lane", "process": "process.name", "proc": "process.name"}.get(chip["field"], chip["field"])


def matches_chip(event, chip):
    if chip_field(chip) == "tartarus.lane":
        hit = event["lane"] == chip["value"]
    else:
        hit = ((event["process"] or {}).get("name", "")).lower() == chip["value"].lower()
    negate = chip.get("negate", False) and "negated_chip_ignored" not in FAULTS
    return hit != negate


def filtered(body, skip_fields=()):
    text = body.get("query", "")
    errors = query_error(text)
    if errors and "bad_query_runs" not in FAULTS:
        raise BadRequest("invalid_query", details={"errors": [error | {"filter_index": None} for error in errors]})
    chips = [chip for chip in body.get("filters", []) if chip_field(chip) not in skip_fields]
    return [event for event in EVENTS if matches_query(event, text) and all(matches_chip(event, chip) for chip in chips)]


def sort_key(event):
    return (event["time"], event["sequence"], event["id"])


def encode_cursor(sort, offset):
    return base64.urlsafe_b64encode(json.dumps({"sort": sort, "after": offset}).encode()).decode().rstrip("=")


def decode_cursor(cursor, sort):
    if "bad_cursor_accepted" in FAULTS:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded))
        if decoded["sort"] != sort:
            raise ValueError("another sort")
        return int(decoded["after"])
    except (ValueError, KeyError, TypeError):
        raise BadRequest("invalid_cursor") from None


def search(body):
    sort = body.get("sort", "@timestamp")
    matching = sorted(filtered(body), key=sort_key, reverse=sort.startswith("-"))
    if sort.startswith("-") and "sorts_not_reversed" in FAULTS and len(matching) > 2:
        matching[0], matching[1] = matching[1], matching[0]
    start = decode_cursor(body["search_after"], sort) if body.get("search_after") else 0
    size = body.get("size", 100)
    page = matching[start : start + size]
    if "duplicate_page" in FAULTS and start > 0 and page:
        page[0] = matching[start - 1]
    more = start + size < len(matching)
    total = len(matching) + ("total_off_by_one" in FAULTS and not body.get("query") and not body.get("filters"))
    cursor = encode_cursor(sort, start + size) if more or ("impossible_has_cursor" in FAULTS and not matching) else None
    return {"events": [public(event, body.get("columns", [])) for event in page], "total": total, "next_cursor": cursor}


def facet(body, field):
    attribute = (lambda event: event["lane"]) if field == "tartarus.lane" else (lambda event: (event["process"] or {}).get("name"))
    skipped = () if "own_chip_applies" in FAULTS else (field,)
    counts = {}
    for event in filtered(body, skip_fields=skipped):
        if attribute(event) is not None:
            counts[attribute(event)] = counts.get(attribute(event), 0) + 1
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    if "facet_count_off" in FAULTS and ranked and field == "process.name":
        ranked[0] = (ranked[0][0], ranked[0][1] + 1)
    return {"field": field, "values": [{"value": value, "count": count} for value, count in ranked], "total": sum(counts.values())}


def histogram(body):
    matching = sorted(filtered(body), key=sort_key)
    if "histogram_lossy" in FAULTS and matching:
        matching = matching[1:]
    buckets = {}
    for event in matching:
        second = event["time"][:19]
        bucket = buckets.setdefault(second, {"time": second + ".000000Z", "total": 0, "by_lane": {}})
        bucket["total"] += 1
        bucket["by_lane"][event["lane"]] = bucket["by_lane"].get(event["lane"], 0) + 1
    alerts = [] if "no_detections" in FAULTS else [event for event in matching if event["kind"] == "alert"]
    return {
        "interval_ms": 1000,
        "from": matching[0]["time"],
        "to": matching[-1]["time"],
        "total": len(matching),
        "buckets": list(buckets.values()),
        "detections": [{"time": a["time"], "id": a["id"], "name": "rule", "severity": "high", "ruleset": "cape"} for a in alerts],
    }


def detail(event_id):
    event = BY_ID.get(event_id)
    if event is None:
        raise BadRequest("not_found", 404)
    referenced_by = [] if "no_referenced_by" in FAULTS else [other for other in EVENTS if event_id in other["references"]]
    references = [BY_ID[reference] for reference in event["references"]]
    source = {"@timestamp": event["time"], "event": {"id": event_id}, "tartarus": {} if "no_raw" in FAULTS else {"raw": {"seen": True}}}
    listing = lambda found: {"items": [public(item) for item in found], "total": len(found)}
    return {"event": public(event), "source": source, "related": {"references": listing(references), "referenced_by": listing(referenced_by)}}


FIELDS = [
    {"name": "process.name", "type": "keyword", "aliases": ["proc", "process"], "description": "", "example": "", "lane": None, "members": [], "searchable": True},
    {"name": "tartarus.lane", "type": "keyword", "aliases": ["lane"], "description": "", "example": "", "lane": None, "members": [], "searchable": True},
]


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
        url = urlparse(self.path)
        parts = unquote(url.path).strip("/").split("/")
        if parts[:2] == ["api", "query"]:
            return self.query_route(method, parts[2], url)
        if parts[:2] != ["api", "analyses"] or len(parts) < 3:
            raise BadRequest("not_found", 404)
        if int(parts[2]) != ANALYSIS_ID and "unknown_analysis_200" not in FAULTS:
            raise BadRequest("not_found", 404)
        rest = parts[3:]
        if method == "GET" and not rest:
            return analysis_record()
        if method == "POST" and rest == ["events", "search"]:
            return search(self.body())
        if method == "POST" and rest == ["events", "facets"]:
            body = self.body()
            return {"facets": [facet(body, field) for field in body["fields"]]}
        if method == "POST" and rest == ["events", "histogram"]:
            return histogram(self.body())
        if method == "GET" and rest[:1] == ["events"]:
            return detail("/".join(rest[1:]))
        if method == "GET" and rest == ["query", "values"]:
            return self.values(parse_qs(url.query))
        raise BadRequest("not_found", 404)

    def query_route(self, method, name, url):
        if method == "POST" and name == "validate":
            errors = query_error(self.body()["query"])
            return {"ok": not errors, "errors": errors}
        return FIELDS

    def values(self, params):
        prefix = params.get("prefix", [""])[0].lower()
        found = {}
        for event in EVENTS:
            name = (event["process"] or {}).get("name", "").lower()
            if name.startswith(prefix) and name and "values_empty" not in FAULTS:
                found[name] = found.get(name, 0) + 1
        return {"values": [{"value": value, "count": count} for value, count in found.items()]}

    def handle_method(self, method):
        try:
            self.reply(200, self.route(method))
        except BadRequest as problem:
            self.reply(problem.status, {"error": {"code": problem.code, "message": problem.code, "details": problem.details}})

    def do_GET(self):
        self.handle_method("GET")

    def do_POST(self):
        self.handle_method("POST")

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
