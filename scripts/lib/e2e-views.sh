# Assertions for scripts/e2e.sh on a finished analysis: the event index and each analysis view,
# read through the frontend's published port and (for the index) from inside the compose network.
# Sourced after e2e-api.sh, which supplies http, body, json_eval, compose and the reporting.

ZIP_PASSWORD=infected
TRAVERSAL_ARTIFACT_ID='..%2F..%2Fetc%2Fpasswd'

# Runs the Python block on stdin over the JSON document `v` in RESPONSE_FILE (the last http
# answer). `assert` fails the check with its message; whatever the block leaves in `detail` is
# printed as the check's detail. `api(method, path, body)` returns (status, JSON) for a further call.
json_assert() {
    python3 -I -c '
import json, sys, urllib.error, urllib.request

# No proxy: BASE is the frontend on this machine, and a configured proxy would not reach it.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def api(method, path, body=None):
    headers = {"content-type": "application/json"} if body is not None else {}
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(sys.argv[2] + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, json.loads(response.read() or "null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or "null")

with open(sys.argv[1]) as response:
    scope = {"json": json, "v": json.load(response), "api": api, "detail": ""}
try:
    exec(sys.stdin.read(), scope)
except AssertionError as error:
    print(error)
    sys.exit(1)
print(scope["detail"])' "$RESPONSE_FILE" "${BASE:-}"
}

# GETs an analysis view (stdin: the Python block, see json_assert).
view_assert() { # id path
    local path="/api/analyses/$1${2:+/$2}"
    http GET "$path"
    [[ $HTTP_CODE == 200 ]] || { echo "GET $path answered $HTTP_CODE"; return 1; }
    json_assert
}

# --- the event index (OpenSearch is not published; ask it from inside the network) ----------

index_name() { echo "tartarus-events-$1"; }

opensearch_curl() { compose exec -T opensearch curl -s "$@"; }

index_document_count() { # id
    opensearch_curl "localhost:9200/$(index_name "$1")/_count" | json_field .count 2>/dev/null
}

index_exists() { # id
    [[ $(opensearch_curl -o /dev/null -w '%{http_code}' -I "localhost:9200/$(index_name "$1")") == 200 ]]
}

index_exists_check() { index_exists "$1" || { echo "$(index_name "$1") does not exist"; return 1; }; }
index_is_gone() { ! index_exists "$1" || { echo "$(index_name "$1") still exists"; return 1; }; }

# --- (i, ii) the event count and the index ----------------------------------------------------

event_count_matches_lanes() { # id
    view_assert "$1" "" <<'PY'
count = v["event_count"]
lanes = v["summary"]["lane_counts"]
assert count > 0, f"event_count is {count}"
assert sum(lanes.values()) == count, f"lane_counts {lanes} do not sum to event_count {count}"
detail = f"{count} events: {lanes}"
PY
}

index_holds_every_event() { # id
    local expected indexed
    expected=$(analysis_field "$1" event_count) || return 1
    indexed=$(index_document_count "$1") || { echo "no answer from OpenSearch for $(index_name "$1")"; return 1; }
    [[ $indexed == "$expected" && $expected -gt 0 ]] || { echo "index holds $indexed documents, event_count is $expected"; return 1; }
    echo "$indexed documents"
}

# --- (iii) to (vii) the views -----------------------------------------------------------------

process_tree_has_a_parent_and_child() { # id
    view_assert "$1" processes <<'PY'
roots = v["roots"]
assert roots, "no root process"
parents = [process for process in roots if process["children"]]
assert parents, "no root has a child"
parent = parents[0]
child = parent["children"][0]
for process in (parent, child):
    name = process["name"]
    assert process["start"] and process["end"], f"{name} has no start or end time"
detail = f"{parent['name']} -> {child['name']}, {v['total']} processes"
PY
}

network_has_dns_and_is_simulated() { # id
    view_assert "$1" network <<'PY'
dns = v["dns"]
assert dns["items"], "no DNS row"
assert v["simulated"] is True, "simulated is not true"
detail = f"{dns['total']} DNS rows, simulated"
PY
}

# Every detection and related event must be a document of the analysis index, not only a row in
# the answer.
detections_resolve() { # id
    local ids summary
    summary=$(view_assert "$1" detections <<'PY'
groups = v["groups"]
assert groups, "no detection group"
assert all(group["detections"] for group in groups), "an empty group"
related = [event["id"] for group in groups for d in group["detections"] for event in d["related_events"]]
assert related, "no detection has a related event"
detail = f"{v['total']} detections in {len(groups)} groups, {len(related)} related events"
PY
    ) || { echo "$summary"; return 1; }
    ids=$(json_assert <<'PY'
detections = [d for group in v["groups"] for d in group["detections"]]
related = [event["id"] for d in detections for event in d["related_events"]]
detail = json.dumps({"ids": sorted(set(related) | {d["id"] for d in detections})})
PY
    )
    opensearch_curl -XPOST -H 'content-type: application/json' -d "$ids" "localhost:9200/$(index_name "$1")/_mget" >"$RESPONSE_FILE"
    echo -n "$summary, "
    json_assert <<'PY' || return 1
missing = [doc["_id"] for doc in v["docs"] if not doc["found"]]
assert not missing, f"{len(missing)} of {len(v['docs'])} detections and related events are not in the index"
detail = "all of them are in the index"
PY
}

attack_has_a_known_tactic() { # id
    view_assert "$1" attack <<'PY'
known = [tactic for tactic in v["tactics"] if tactic["id"] != "unknown" and tactic["techniques"]]
assert known, "no technique under a known tactic: " + ", ".join(tactic["id"] for tactic in v["tactics"])
detail = ", ".join(f"{tactic['id']}: {len(tactic['techniques'])}" for tactic in known)
PY
}

iocs_include_hash() { # id sha256
    http GET "/api/analyses/$1/iocs"
    [[ $HTTP_CODE == 200 ]] || { echo "GET iocs answered $HTTP_CODE"; return 1; }
    json_assert <<PY
wanted = "$2"
hashes = [ioc for ioc in v["iocs"] if ioc["type"] == "hash" and ioc["value"] == wanted]
assert hashes, f"no hash IOC for the sample sha256 {wanted}"
detail = hashes[0]["context"]
PY
}

# --- (viii, ix) artifacts ---------------------------------------------------------------------

# Prints "locked" or "opened <sha256 of the first member>" for a zip on stdin. pyzipper is the
# library that wrote the zip; the backend image has it, a bare host usually does not.
ZIP_PROBE='
import hashlib, io, sys
import pyzipper
archive = pyzipper.AESZipFile(io.BytesIO(sys.stdin.buffer.read()))
member = archive.namelist()[0]
try:
    archive.read(member)
    print("opened without a password")
except RuntimeError:
    print("locked", hashlib.sha256(archive.read(member, pwd=sys.argv[1].encode())).hexdigest())'

probe_zip() { # zip-file
    if python3 -I -c 'import pyzipper' 2>/dev/null; then
        python3 -I -c "$ZIP_PROBE" "$ZIP_PASSWORD" <"$1"
    else
        compose exec -T backend python -I -c "$ZIP_PROBE" "$ZIP_PASSWORD" <"$1"
    fi
}

first_dropped_artifact() { # id -> "<artifact id> <sha256>"
    http GET "/api/analyses/$1/artifacts"
    [[ $HTTP_CODE == 200 ]] || { echo "GET artifacts answered $HTTP_CODE" >&2; return 1; }
    body | json_eval '" ".join(next((a["id"], a["sha256"]) for a in v["dropped"] if a["downloadable"]))' 2>/dev/null ||
        { echo "no downloadable dropped file" >&2; return 1; }
}

dropped_file_downloads_as_a_locked_zip() { # id
    local artifact sha probe
    read -r artifact sha < <(first_dropped_artifact "$1") && [[ -n $artifact ]] || { echo "no downloadable dropped file"; return 1; }
    http GET "/api/analyses/$1/artifacts/$artifact/download"
    [[ $HTTP_CODE == 200 ]] || { echo "download answered $HTTP_CODE"; return 1; }
    probe=$(probe_zip "$RESPONSE_FILE") || { echo "could not read the zip: $probe"; return 1; }
    [[ $probe == "locked $sha" ]] || { echo "expected 'locked $sha', got '$probe'"; return 1; }
    echo "needs the password, and holds the dropped file's sha256"
}

path_traversal_artifact_is_404() { # id
    http GET "/api/analyses/$1/artifacts/$TRAVERSAL_ARTIFACT_ID/download"
    [[ $HTTP_CODE == 404 ]] || { echo "answered $HTTP_CODE"; return 1; }
}

# --- all of it --------------------------------------------------------------------------------

check_finished_analysis_views() { # id sha256
    local id=$1 sha=$2
    check "(a) event_count is positive and the lane counts add up to it" event_count_matches_lanes "$id"
    check "(a) the event index holds exactly event_count documents" index_holds_every_event "$id"
    check "(a) /processes has a root with a child, all with end times" process_tree_has_a_parent_and_child "$id"
    check "(a) /network has a DNS row and is simulated" network_has_dns_and_is_simulated "$id"
    check "(a) /detections is not empty and every related event is in the index" detections_resolve "$id"
    check "(a) /attack has a technique under a known tactic" attack_has_a_known_tactic "$id"
    check "(a) /iocs has a hash for the sample's own sha256" iocs_include_hash "$id" "$sha"
    check "(a) a dropped file downloads as a zip that needs the password" dropped_file_downloads_as_a_locked_zip "$id"
    check "(a) a path-traversal artifact id answers 404" path_traversal_artifact_is_404 "$id"
}
