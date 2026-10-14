# Assertions for scripts/e2e.sh on a finished analysis answering queries: the query endpoints and
# the events API (search, paging, facets, histogram, detail, value autocomplete), read through the
# frontend's published port and compared with what the analysis record itself says (event_count,
# lane_counts, filename). Sourced after e2e-api.sh and e2e-views.sh, whose json_assert runs each
# Python block and gives it `api(method, path, body)` for the further calls a check makes.

QUERY_PAGE_SIZE=100
# Paging every event of a run is a few seconds at this size; a far larger index is cut to its first pages.
QUERY_MAX_PAGED_EVENTS=${E2E_QUERY_MAX_PAGED_EVENTS:-60000}
QUERY_CAPPED_EVENTS=600

# What every check's block starts with. `v` is the document json_assert loaded: the analysis for
# query_assert, the field catalog for catalog_assert.
QUERY_API_PRELUDE=$(
    cat <<'PY'
def answer(method, path, body=None, expect=200):
    status, payload = api(method, path, body)
    sent = json.dumps(body)[:200] if body is not None else ""
    assert status == expect, f"{method} {path} {sent} answered {status} (wanted {expect}): {str(payload)[:300]}"
    return payload

def problem(method, path, body, status):
    answered, payload = api(method, path, body)
    assert answered == status, f"{method} {path} {json.dumps(body)[:200]} answered {answered} (wanted {status}): {str(payload)[:300]}"
    return payload["error"]
PY
)

QUERY_ANALYSIS_PRELUDE=$(
    cat <<'PY'
import urllib.parse
from datetime import datetime

ANALYSIS = v
URL = f"/api/analyses/{v['id']}"
SAMPLE = v["filename"]
EVENT_COUNT = v["event_count"]
LANE_COUNTS = v["summary"]["lane_counts"]
PAGE_SIZE = QUERY_PAGE_SIZE

def search(**body):
    return answer("POST", f"{URL}/events/search", body)

def total_of(**body):
    return search(size=1, **body)["total"]

def facets_of(fields, **body):
    listed = answer("POST", f"{URL}/events/facets", {"fields": fields, **body})["facets"]
    return {facet["field"]: facet for facet in listed}

def detail_of(event_id):
    return answer("GET", f"{URL}/events/{urllib.parse.quote(event_id, safe='')}")

def process_name(event):
    return ((event["process"] or {}).get("name") or "").lower()

def moment(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))

def order_key(event):
    return (moment(event["time"]), event["sequence"] if event["sequence"] is not None else float("inf"))

def page_through(sort, limit=None):
    events, cursor, pages = [], None, 0
    while True:
        body = {"sort": sort, "size": PAGE_SIZE}
        if cursor is not None:
            body["search_after"] = cursor
        page = search(**body)
        pages += 1
        assert page["events"] or page["next_cursor"] is None, f"page {pages} of sort {sort} is empty yet offers a next_cursor"
        events += page["events"]
        cursor = page["next_cursor"]
        if cursor is None or (limit is not None and len(events) >= limit):
            return events, pages
        assert pages <= EVENT_COUNT // PAGE_SIZE + 3, f"sort {sort}: {pages} pages and the cursor still chains"
PY
)

# Runs the Python block on stdin over the analysis `id`.
query_assert() { # id
    http GET "/api/analyses/$1"
    [[ $HTTP_CODE == 200 ]] || { echo "GET /api/analyses/$1 answered $HTTP_CODE"; return 1; }
    {
        printf 'QUERY_PAGE_SIZE, QUERY_MAX_PAGED_EVENTS, QUERY_CAPPED_EVENTS = %s, %s, %s\n' \
            "$QUERY_PAGE_SIZE" "$QUERY_MAX_PAGED_EVENTS" "$QUERY_CAPPED_EVENTS"
        printf '%s\n%s\n' "$QUERY_API_PRELUDE" "$QUERY_ANALYSIS_PRELUDE"
        cat
    } | json_assert
}

# Runs the Python block on stdin over the field catalog, for checks that need no analysis.
catalog_assert() {
    http GET /api/query/fields
    [[ $HTTP_CODE == 200 ]] || { echo "GET /api/query/fields answered $HTTP_CODE"; return 1; }
    { printf '%s\n' "$QUERY_API_PRELUDE"; cat; } | json_assert
}

# --- (i) validation and the field catalog ------------------------------------------------------

query_validation_accepts_a_good_query() {
    catalog_assert <<'PY'
checked = answer("POST", "/api/query/validate", {"query": "process.name:cmd.exe AND lane:network"})
assert checked["ok"] is True and checked["errors"] == [], f"a good query was refused: {checked}"
empty = answer("POST", "/api/query/validate", {"query": ""})
assert empty["ok"] is True, f"the empty query was refused: {empty}"
detail = "ok for a good query and for the empty one"
PY
}

query_validation_flags_a_misspelt_field() {
    catalog_assert <<'PY'
checked = answer("POST", "/api/query/validate", {"query": "procss:x"})
assert checked["ok"] is False, f"procss:x was accepted: {checked}"
(error,) = checked["errors"]
assert (error["start"], error["end"]) == (0, 6), f"the span is {error['start']}..{error['end']}, the field is 0..6"
assert error["suggestion"] == "process", f"the suggestion is {error['suggestion']!r}"
detail = f"{error['message']} (span 0..6)"
PY
}

field_catalog_lists_process_name_and_its_aliases() {
    catalog_assert <<'PY'
by_name = {field["name"]: field for field in v}
assert "process.name" in by_name, f"no process.name among {len(v)} fields"
aliases = by_name["process.name"]["aliases"]
assert "proc" in aliases and "process" in aliases, f"process.name aliases are {aliases}"
assert all(isinstance(field["aliases"], list) for field in v), "a field has no alias list"
detail = f"{len(v)} fields, process.name has aliases {aliases}"
PY
}

# --- (ii) search, paging and the two sorts --------------------------------------------------------

unfiltered_search_total_is_event_count() { # id
    query_assert "$1" <<'PY'
page = search(size=1)
assert page["total"] == EVENT_COUNT, f"total is {page['total']}, the analysis' event_count is {EVENT_COUNT}"
assert len(page["events"]) == 1, f"size 1 returned {len(page['events'])} events"
detail = f"total {page['total']} = event_count"
PY
}

paging_covers_every_event_once_in_both_sorts() { # id
    query_assert "$1" <<'PY'
from itertools import pairwise

capped = EVENT_COUNT > QUERY_MAX_PAGED_EVENTS
limit = QUERY_CAPPED_EVENTS if capped else None
ascending, pages = page_through("@timestamp", limit)
descending, _ = page_through("-@timestamp", limit)
for sort, events in (("@timestamp", ascending), ("-@timestamp", descending)):
    ids = [event["id"] for event in events]
    repeated = len(ids) - len(set(ids))
    assert repeated == 0, f"sort {sort}: {repeated} of {len(ids)} events came on more than one page"
    if not capped:
        assert len(ids) == EVENT_COUNT, f"sort {sort}: paging collected {len(ids)} events, the total is {EVENT_COUNT}"
assert all(order_key(a) <= order_key(b) for a, b in pairwise(ascending)), "the ascending sort is not in (time, sequence) order"
assert all(order_key(a) >= order_key(b) for a, b in pairwise(descending)), "the descending sort is not in (time, sequence) order"
if capped:
    detail = f"{EVENT_COUNT} events is over {QUERY_MAX_PAGED_EVENTS}: the first {len(ascending)} of each sort chain with no repeat; the reverse was not compared"
else:
    ascending_ids = [event["id"] for event in ascending]
    descending_ids = [event["id"] for event in descending]
    assert descending_ids == ascending_ids[::-1], "the descending order is not the exact reverse of the ascending one"
    detail = f"{len(ascending)} events in {pages} pages of {PAGE_SIZE} in each sort, each once, the two orders exact reverses"
PY
}

# --- (iii) a query narrows ------------------------------------------------------------------------

lane_query_matches_the_lane_count() { # id
    query_assert "$1" <<'PY'
expected = LANE_COUNTS.get("process", 0)
assert expected > 0, f"the analysis has no process event: {LANE_COUNTS}"
page = search(query="lane:process", size=500)
other = {event["lane"] for event in page["events"]} - {"process"}
assert not other, f"lane:process returned events of lanes {sorted(other)}"
assert page["total"] == expected, f"lane:process total is {page['total']}, lane_counts says {expected}"
detail = f"lane:process: {page['total']} events, all of the process lane"
PY
}

lane_chip_equals_the_query_and_a_negated_chip_is_the_rest() { # id
    query_assert "$1" <<'PY'
chip = {"field": "lane", "value": "process"}
by_query = total_of(query="lane:process")
by_chip = total_of(filters=[chip])
assert by_chip == by_query, f"the lane chip gives {by_chip}, the query lane:process gives {by_query}"
rest = total_of(filters=[{**chip, "negate": True}])
assert rest == EVENT_COUNT - by_query, f"the negated chip gives {rest}, expected {EVENT_COUNT} - {by_query}"
contradiction = total_of(query="lane:process", filters=[{**chip, "negate": True}])
assert contradiction == 0, f"the lane and its negated chip together give {contradiction}"
detail = f"chip {by_chip} = query {by_query}; negated chip {rest} = {EVENT_COUNT} - {by_query}; both together 0"
PY
}

process_alias_finds_only_the_sample_process() { # id
    query_assert "$1" <<'PY'
page = search(query=f'proc:"{SAMPLE}"', size=500)
assert page["total"] > 0, f"proc:{SAMPLE} found nothing"
wrong = {process_name(event) for event in page["events"]} - {SAMPLE.lower()}
assert not wrong, f"proc:{SAMPLE} returned events of the processes {sorted(wrong)}"
detail = f"proc:{SAMPLE}: {page['total']} events, all of that process"
PY
}

free_text_finds_the_sample_name() { # id
    query_assert "$1" <<'PY'
total = total_of(query=f'"{SAMPLE}"')
assert total > 0, f'free text "{SAMPLE}" found nothing'
detail = f'free text "{SAMPLE}": {total} events'
PY
}

impossible_query_has_no_events() { # id
    query_assert "$1" <<'PY'
page = search(query="process.name:no-such-process-xyz")
assert page["total"] == 0, f"total is {page['total']}"
assert page["events"] == [], f"{len(page['events'])} events on the page"
assert page["next_cursor"] is None, f"next_cursor is {page['next_cursor']!r}"
detail = "total 0, empty page, no cursor"
PY
}

# --- (iv) what is refused ------------------------------------------------------------------------

bad_queries_answer_422_with_spans() { # id
    query_assert "$1" <<'PY'
seen = []
for text in ("((", "procss:x"):
    error = problem("POST", f"{URL}/events/search", {"query": text}, 422)
    assert error["code"] == "invalid_query", f"{text!r}: the error code is {error['code']}"
    spans = error["details"]["errors"]
    assert spans, f"{text!r}: no error span"
    for span in spans:
        assert 0 <= span["start"] < span["end"] <= len(text), f"{text!r}: span {span['start']}..{span['end']} is outside the query"
        assert span["filter_index"] is None, f"{text!r}: filter_index {span['filter_index']} for an error in the query text"
    seen.append(f"{text!r} -> {spans[0]['start']}..{spans[0]['end']}")
    if text.startswith("procss"):
        assert spans[0]["suggestion"] == "process", f"the suggestion is {spans[0]['suggestion']!r}"
detail = "; ".join(seen)
PY
}

bad_cursor_answers_422() { # id
    query_assert "$1" <<'PY'
error = problem("POST", f"{URL}/events/search", {"search_after": "not-a-cursor"}, 422)
assert error["code"] == "invalid_cursor", f"the error code is {error['code']}"
cursor = search(size=1)["next_cursor"]
foreign = problem("POST", f"{URL}/events/search", {"sort": "-@timestamp", "search_after": cursor}, 422)
assert foreign["code"] == "invalid_cursor", f"a cursor of the other sort gave {foreign['code']}"
detail = "invalid_cursor for garbage and for a cursor of the other sort"
PY
}

unknown_analysis_answers_404() { # id
    query_assert "$1" <<'PY'
missing = v["id"] + 1_000_000
error = problem("POST", f"/api/analyses/{missing}/events/search", {}, 404)
assert error["code"] == "not_found", f"the error code is {error['code']}"
problem("GET", f"{URL}/events/no-such-event", None, 404)
detail = f"analysis {missing} and an unknown event answer 404"
PY
}

# --- (v) facets ----------------------------------------------------------------------------------

top_process_facet_count_matches_a_search() { # id
    query_assert "$1" <<'PY'
total = total_of()
facets = facets_of(["tartarus.lane", "process.name"])
lanes = facets["tartarus.lane"]
assert sum(value["count"] for value in lanes["values"]) <= total, f"the lane facet sums to more than the total {total}"
top = facets["process.name"]["values"][0]
by_chip = total_of(filters=[{"field": "process.name", "value": top["value"]}])
assert by_chip == top["count"], f"the top process {top['value']} counts {top['count']} in the facet and {by_chip} in a search"
detail = f"{len(lanes['values'])} lanes; top process {top['value']}: {top['count']} in the facet and in a search"
PY
}

lane_facet_ignores_its_own_chip() { # id
    query_assert "$1" <<'PY'
facets = facets_of(["tartarus.lane", "process.name"], filters=[{"field": "lane", "value": "process"}])
lanes = {value["value"]: value["count"] for value in facets["tartarus.lane"]["values"]}
assert len(lanes) > 1, f"with a chip on lane the lane facet lists only {sorted(lanes)}"
assert lanes.get("process") == LANE_COUNTS["process"], f"the process lane counts {lanes.get('process')}, lane_counts says {LANE_COUNTS['process']}"
others = facets["process.name"]["total"]
assert others <= LANE_COUNTS["process"], f"the process.name facet counts {others} events although the chip keeps {LANE_COUNTS['process']}"
detail = f"lane facet still lists {sorted(lanes)}; the other facet narrowed to {others} events"
PY
}

# --- (vi) histogram ------------------------------------------------------------------------------

histogram_sums_to_the_totals_and_lane_counts() { # id
    query_assert "$1" <<'PY'
histogram = answer("POST", f"{URL}/events/histogram", {})
buckets = histogram["buckets"]
assert histogram["interval_ms"] > 0 and 0 < len(buckets) <= 120, f"auto interval {histogram['interval_ms']} ms gives {len(buckets)} buckets"
assert histogram["total"] == EVENT_COUNT, f"total is {histogram['total']}, event_count is {EVENT_COUNT}"
summed = sum(bucket["total"] for bucket in buckets)
assert summed == EVENT_COUNT, f"the buckets sum to {summed}, event_count is {EVENT_COUNT}"
per_lane = {}
for bucket in buckets:
    assert sum(bucket["by_lane"].values()) == bucket["total"], f"bucket {bucket['time']}: by_lane does not sum to its total"
    for lane, count in bucket["by_lane"].items():
        per_lane[lane] = per_lane.get(lane, 0) + count
assert per_lane == LANE_COUNTS, f"per-lane sums {per_lane} differ from lane_counts {LANE_COUNTS}"
signatures = len(ANALYSIS["summary"]["signatures"])
if signatures:
    assert histogram["detections"], f"the analysis has {signatures} signatures and the histogram no detection"
    note = f"{len(histogram['detections'])} detections"
else:
    note = "no signatures, so detections were not checked"
detail = f"{len(buckets)} buckets of {histogram['interval_ms']} ms sum to {summed} and to lane_counts; {note}"
PY
}

# --- (vii) one event ------------------------------------------------------------------------------

event_detail_has_the_raw_document() { # id
    query_assert "$1" <<'PY'
first = search(size=1)["events"][0]
detail_of_first = detail_of(first["id"])
assert detail_of_first["event"]["id"] == first["id"], "GET events/{id} returned another event"
source = detail_of_first["source"]
assert source.get("event", {}).get("id") == first["id"], "the stored document is not this event's"
assert source.get("tartarus", {}).get("raw") is not None, "the stored document has no tartarus.raw, which searches leave out"
detail = f"{first['id']}: the whole document with tartarus.raw"
PY
}

alert_and_the_event_it_names_point_at_each_other() { # id
    query_assert "$1" <<'PY'
alerts = search(query="kind:alert", size=50)["events"]
assert alerts, "the analysis has no alert event"
for alert in alerts:
    references = detail_of(alert["id"])["related"]["references"]
    if references["total"] > 0:
        break
else:
    raise AssertionError(f"none of {len(alerts)} alerts names an event in related.references")
assert references["items"], "references.total is positive and the listing is empty"
named = references["items"][0]["id"]
back = detail_of(named)["related"]["referenced_by"]
assert alert["id"] in [event["id"] for event in back["items"]], f"event {named} is named by alert {alert['id']} and its referenced_by lacks it"
detail = f"alert {alert['id']} names {references['total']} events; {named} is referenced_by it"
PY
}

# --- (viii, ix) values and columns ----------------------------------------------------------------

value_autocomplete_finds_the_sample_name() { # id
    query_assert "$1" <<'PY'
prefix = urllib.parse.quote(SAMPLE[:4].lower())
values = answer("GET", f"{URL}/query/values?field=proc&prefix={prefix}")["values"]
found = {entry["value"]: entry["count"] for entry in values}
assert SAMPLE.lower() in found, f"proc values starting with {SAMPLE[:4].lower()!r} are {sorted(found)}"
detail = f"{SAMPLE.lower()}: {found[SAMPLE.lower()]} events"
PY
}

columns_return_the_command_line() { # id
    query_assert "$1" <<'PY'
page = search(query="process.command_line:*", columns=["process.command_line"], size=100)
assert page["total"] > 0, "no event has a command line"
bare = [event["id"] for event in page["events"] if not event["fields"].get("process.command_line")]
assert not bare, f"{len(bare)} of {len(page['events'])} events with a command line have no fields.process.command_line"
plain = search(size=5)["events"]
assert all(event["fields"] == {} for event in plain), "fields is not empty without columns"
detail = f"{page['total']} events with a command line, e.g. {page['events'][0]['fields']['process.command_line']}"
PY
}

# --- all of it ------------------------------------------------------------------------------------

check_finished_analysis_queries() { # id
    local id=$1
    check "(a) /query/validate accepts a good query and the empty one" query_validation_accepts_a_good_query
    check "(a) /query/validate flags procss:x with a span and the suggestion process" query_validation_flags_a_misspelt_field
    check "(a) /query/fields lists process.name with its aliases" field_catalog_lists_process_name_and_its_aliases
    check "(a) events/search with no filter totals event_count" unfiltered_search_total_is_event_count "$id"
    check "(a) paging follows next_cursor to the end in both sorts, every event once, the orders exact reverses" paging_covers_every_event_once_in_both_sorts "$id"
    check "(a) the query lane:process returns only process events, as many as lane_counts says" lane_query_matches_the_lane_count "$id"
    check "(a) a lane chip equals the query and its negation is the rest" lane_chip_equals_the_query_and_a_negated_chip_is_the_rest "$id"
    check "(a) the alias proc finds the sample's own process and no other" process_alias_finds_only_the_sample_process "$id"
    check "(a) free text of the sample name finds events" free_text_finds_the_sample_name "$id"
    check "(a) an impossible query has no events and no cursor" impossible_query_has_no_events "$id"
    check "(a) a bad query answers 422 invalid_query with spans" bad_queries_answer_422_with_spans "$id"
    check "(a) a bad cursor answers 422 invalid_cursor" bad_cursor_answers_422 "$id"
    check "(a) an unknown analysis and an unknown event answer 404" unknown_analysis_answers_404 "$id"
    check "(a) the top process facet count equals a search with that chip" top_process_facet_count_matches_a_search "$id"
    check "(a) a facet ignores the chips on its own field" lane_facet_ignores_its_own_chip "$id"
    check "(a) the histogram sums to event_count and to lane_counts, with detections" histogram_sums_to_the_totals_and_lane_counts "$id"
    check "(a) GET events/{id} returns the whole stored document" event_detail_has_the_raw_document "$id"
    check "(a) an alert names events that name it back" alert_and_the_event_it_names_point_at_each_other "$id"
    check "(a) /query/values completes the sample's process name" value_autocomplete_finds_the_sample_name "$id"
    check "(a) columns return the command line in fields" columns_return_the_command_line "$id"
}
