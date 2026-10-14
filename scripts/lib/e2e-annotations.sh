# Assertions for scripts/e2e.sh on the analyst's tags and notes: added on the analysis, a process and an
# event of a finished run, read back exactly, filtered and counted, refused where the API says so,
# kept by a re-ingest, and removed with the analysis (down to the database rows). Sourced after
# e2e-api.sh, e2e-views.sh and e2e-query.sh (whose QUERY_API_PRELUDE gives each block `answer` and
# `problem`).
#
# The names and texts below are chosen by choose_annotations and read by every check, so they are
# set in the caller's shell, never inside `check`'s subshell. Every tag this run creates starts with
# `e2e-<analysis id>-`, which is how the delete step knows no tag of the run is left.

ANNOTATION_TARGET_EVENT_QUERY='tartarus.lane:process AND event.kind:event'

annotation_tag_prefix() { echo "e2e-$1-"; }

# The pid of the process that ran the sample (the first one listed if none carries its name).
process_to_annotate() { # id sample-name
    http GET "/api/analyses/$1/processes"
    [[ $HTTP_CODE == 200 ]] || { echo "GET processes answered $HTTP_CODE"; return 1; }
    json_assert <<PY
def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node["children"])
processes = list(walk(v["roots"]))
assert processes, "the analysis has no process"
named = [process for process in processes if process["name"] == "$2"]
detail = (named or processes)[0]["pid"]
PY
}

# A process-lane event that is not an alert: alerts come and go with the rules, ordinary events keep their id.
event_to_annotate() { # id
    http POST "/api/analyses/$1/events/search" -H 'content-type: application/json' \
        -d "{\"query\": \"$ANNOTATION_TARGET_EVENT_QUERY\", \"size\": 1}"
    [[ $HTTP_CODE == 200 ]] || { echo "the search answered $HTTP_CODE: $(body)"; return 1; }
    body | json_eval 'v["events"][0]["id"]' 2>/dev/null || { echo "no process event to annotate"; return 1; }
}

# Sets ANN_ID, ANN_PID, ANN_EVENT_ID and the names and texts of the annotations of this run.
choose_annotations() { # id sample-name
    ANN_ID=$1
    ANN_PID=$(process_to_annotate "$1" "$2") || { echo "$ANN_PID" >&2; return 1; }
    ANN_EVENT_ID=$(event_to_annotate "$1") || { echo "$ANN_EVENT_ID" >&2; return 1; }
    local prefix
    prefix=$(annotation_tag_prefix "$1")
    ANN_CASE_TAG=${prefix}case
    ANN_PROCESS_TAG=${prefix}process
    ANN_EVENT_TAG=${prefix}event
    ANN_TEMP_TAG=${prefix}temp
    ANN_ABSENT_TAG=${prefix}absent
    ANN_CASE_NOTE_DRAFT="first impression of analysis $1: probably a dropper"
    ANN_CASE_NOTE="analyst verdict on analysis $1: benign test sample"
    ANN_PROCESS_NOTE="process $ANN_PID is the sample itself"
    ANN_EVENT_NOTE="this event is where the sample starts a child"
    ANN_TEMP_NOTE="a note that is about to be removed"
}

# The Python every annotation check starts with: the names above, and what reading annotations takes.
annotation_prelude() {
    printf '%s\n' "$QUERY_API_PRELUDE"
    cat <<PY
ID = $ANN_ID
PID = "$ANN_PID"
EVENT_ID = "$ANN_EVENT_ID"
CASE_TAG, PROCESS_TAG, EVENT_TAG = "$ANN_CASE_TAG", "$ANN_PROCESS_TAG", "$ANN_EVENT_TAG"
TEMP_TAG, ABSENT_TAG = "$ANN_TEMP_TAG", "$ANN_ABSENT_TAG"
CASE_NOTE_DRAFT, CASE_NOTE = "$ANN_CASE_NOTE_DRAFT", "$ANN_CASE_NOTE"
PROCESS_NOTE, EVENT_NOTE, TEMP_NOTE = "$ANN_PROCESS_NOTE", "$ANN_EVENT_NOTE", "$ANN_TEMP_NOTE"
ANALYSIS_TARGET = {"target_type": "analysis", "target_ref": ""}
PROCESS_TARGET = {"target_type": "process", "target_ref": PID}
EVENT_TARGET = {"target_type": "event", "target_ref": EVENT_ID}

def annotations_of(analysis=ID, narrowed=""):
    return answer("GET", f"/api/analyses/{analysis}/annotations{narrowed}")

def tag_usage():
    return {usage["name"]: usage["count"] for usage in answer("GET", "/api/tags")}

def tags_of(annotations):
    return sorted((link["tag"], link["target_type"], link["target_ref"]) for link in annotations["tags"])

def notes_of(annotations):
    return sorted((note["target_type"], note["target_ref"], note["body"]) for note in annotations["notes"])

def add_tag(name, target):
    return answer("POST", f"/api/analyses/{ID}/tags", {"tag": name, **target}, expect=201)

def add_note(body, target):
    return answer("POST", f"/api/analyses/{ID}/notes", {"body": body, **target}, expect=201)
PY
}

# Runs the Python block on stdin with the prelude above, over the analysis the annotations are on.
annotation_assert() {
    {
        annotation_prelude
        cat
    } | { http GET "/api/analyses/$ANN_ID"; json_assert; }
}

# --- adding, reading back, filtering ------------------------------------------------------------

annotations_are_added_on_the_analysis_a_process_and_an_event() {
    annotation_assert <<'PY'
for name, target in ((CASE_TAG, ANALYSIS_TARGET), (PROCESS_TAG, PROCESS_TARGET), (EVENT_TAG, EVENT_TARGET)):
    link = add_tag(name, target)
    assert (link["tag"], link["target_type"], link["target_ref"]) == (name, target["target_type"], target["target_ref"]), f"the tag came back as {link}"
for body, target in ((CASE_NOTE_DRAFT, ANALYSIS_TARGET), (PROCESS_NOTE, PROCESS_TARGET), (EVENT_NOTE, EVENT_TARGET)):
    note = add_note(body, target)
    assert (note["body"], note["target_type"], note["target_ref"]) == (body, target["target_type"], target["target_ref"]), f"the note came back as {note}"
detail = f"3 tags and 3 notes on the analysis, pid {PID} and event {EVENT_ID[:8]}"
PY
}

annotations_read_back_exactly_and_narrow_by_target() {
    annotation_assert <<'PY'
everything = annotations_of()
assert tags_of(everything) == sorted([(CASE_TAG, "analysis", ""), (PROCESS_TAG, "process", PID), (EVENT_TAG, "event", EVENT_ID)]), f"tags are {tags_of(everything)}"
assert notes_of(everything) == sorted([("analysis", "", CASE_NOTE_DRAFT), ("process", PID, PROCESS_NOTE), ("event", EVENT_ID, EVENT_NOTE)]), f"notes are {notes_of(everything)}"
orphans = [item for item in everything["tags"] + everything["notes"] if item["orphaned"]]
assert not orphans, f"{len(orphans)} annotations are orphaned: {orphans}"
for target, tag, note in ((PROCESS_TARGET, PROCESS_TAG, PROCESS_NOTE), (EVENT_TARGET, EVENT_TAG, EVENT_NOTE)):
    narrowed = annotations_of(narrowed=f"?target_type={target['target_type']}&target_ref={target['target_ref']}")
    assert [link["tag"] for link in narrowed["tags"]] == [tag] and [item["body"] for item in narrowed["notes"]] == [note], f"{target['target_type']} target: {narrowed}"
only_analysis = annotations_of(narrowed="?target_type=analysis")
assert [link["tag"] for link in only_analysis["tags"]] == [CASE_TAG], f"the analysis target holds {only_analysis}"
detail = "3 tags and 3 notes exactly as written, none orphaned, and each target narrows to its own"
PY
}

tag_counts_and_the_tag_filter_follow_the_links() {
    annotation_assert <<'PY'
usage = tag_usage()
for name in (CASE_TAG, PROCESS_TAG, EVENT_TAG):
    assert usage.get(name) == 1, f"GET /api/tags lists {name} with count {usage.get(name)}, wanted 1"
def analyses_with(tag):
    return [item["id"] for item in answer("GET", f"/api/analyses?limit=200&tag={tag}")["items"]]
assert analyses_with(CASE_TAG) == [ID], f"?tag={CASE_TAG} returns {analyses_with(CASE_TAG)}, wanted [{ID}]"
# The filter reads the analysis's own tags, so a tag that exists only on a process is a different tag.
for other in (PROCESS_TAG, ABSENT_TAG):
    assert analyses_with(other) == [], f"?tag={other} returns {analyses_with(other)}, wanted none"
tagged = {item["id"]: item["tags"] for item in answer("GET", f"/api/analyses?limit=200&tag={CASE_TAG}")["items"]}
assert tagged[ID] == [CASE_TAG], f"the listed analysis carries tags {tagged[ID]}"
detail = f"counts of 1 for 3 tags; ?tag={CASE_TAG} returns the analysis, {PROCESS_TAG} and a tag that does not exist return none"
PY
}

duplicate_tag_is_409_and_bad_names_are_422() {
    annotation_assert <<'PY'
before = annotations_of()
problem("POST", f"/api/analyses/{ID}/tags", {"tag": CASE_TAG, **ANALYSIS_TARGET}, 409)
problem("POST", f"/api/analyses/{ID}/tags", {"tag": CASE_TAG.upper(), **ANALYSIS_TARGET}, 409)
for bad in ("has space", "a:b:c", "", "x" * 41, "semi;colon"):
    error = problem("POST", f"/api/analyses/{ID}/tags", {"tag": bad, **ANALYSIS_TARGET}, 422)
    assert error["code"] == "validation_error", f"tag {bad!r}: error code {error['code']}"
problem("POST", f"/api/analyses/{ID}/notes", {"body": "", **ANALYSIS_TARGET}, 422)
problem("POST", "/api/analyses/999999999/tags", {"tag": CASE_TAG, **ANALYSIS_TARGET}, 404)
assert annotations_of() == before, "a refused request changed the annotations"
detail = "a duplicate (also in capitals) is 409; five bad names and an empty note are 422; an unknown analysis is 404; nothing changed"
PY
}

patching_a_note_replaces_its_text() {
    annotation_assert <<'PY'
draft = next(note for note in annotations_of()["notes"] if note["target_type"] == "analysis")
patched = answer("PATCH", f"/api/notes/{draft['id']}", {"body": CASE_NOTE})
assert patched["id"] == draft["id"] and patched["body"] == CASE_NOTE, f"PATCH answered {patched}"
notes = annotations_of()["notes"]
assert len(notes) == 3, f"{len(notes)} notes after the patch, wanted 3"
assert [note["body"] for note in notes if note["id"] == draft["id"]] == [CASE_NOTE], "the read does not show the patched text"
assert CASE_NOTE_DRAFT not in [note["body"] for note in notes], "the draft text is still there"
problem("PATCH", "/api/notes/0", {"body": "nobody's"}, 404)
detail = "the draft became the verdict, still one note, and an unknown note is 404"
PY
}

removing_a_tag_removes_the_link_and_a_tag_no_link_uses() {
    annotation_assert <<'PY'
link = add_tag(TEMP_TAG, PROCESS_TARGET)
assert tag_usage().get(TEMP_TAG) == 1, f"the new tag is not listed with count 1: {tag_usage().get(TEMP_TAG)}"
status, _ = api("DELETE", f"/api/analyses/{ID}/tags/{link['link_id']}")
assert status == 204, f"DELETE answered {status}"
assert TEMP_TAG not in [item["tag"] for item in annotations_of()["tags"]], "the removed tag is still on the analysis"
assert TEMP_TAG not in tag_usage(), "GET /api/tags still lists a tag no link uses"
status, _ = api("DELETE", f"/api/analyses/{ID}/tags/{link['link_id']}")
assert status == 404, f"removing the link twice answered {status}"
usage = tag_usage()
assert all(usage.get(name) == 1 for name in (CASE_TAG, PROCESS_TAG, EVENT_TAG)), f"the other tags changed: {usage}"
detail = "removed: 204, gone from the analysis and from /api/tags, a second removal is 404, the others untouched"
PY
}

removing_a_note_removes_it() {
    annotation_assert <<'PY'
note = add_note(TEMP_NOTE, PROCESS_TARGET)
assert TEMP_NOTE in [item["body"] for item in annotations_of()["notes"]], "the new note is not listed"
status, _ = api("DELETE", f"/api/notes/{note['id']}")
assert status == 204, f"DELETE answered {status}"
assert TEMP_NOTE not in [item["body"] for item in annotations_of()["notes"]], "the removed note is still listed"
status, _ = api("DELETE", f"/api/notes/{note['id']}")
assert status == 404, f"removing the note twice answered {status}"
detail = "removed: 204, gone from the listing, a second removal is 404"
PY
}

# An event can only be annotated once its analysis is done: a live event's id may still change.
event_annotations_are_refused_on_an_unfinished_analysis() { # unfinished-id
    annotation_assert <<PY
other = $1
status = answer("GET", f"/api/analyses/{other}")["status"]
assert status != "done", f"analysis {other} is done, it cannot show the refusal"
problem("POST", f"/api/analyses/{other}/tags", {"tag": CASE_TAG, **EVENT_TARGET}, 409)
problem("POST", f"/api/analyses/{other}/notes", {"body": EVENT_NOTE, **EVENT_TARGET}, 409)
assert annotations_of(other) == {"tags": [], "notes": []}, "a refused annotation was stored"
assert CASE_TAG in tag_usage() and tag_usage()[CASE_TAG] == 1, "the refused tag was counted"
detail = f"a tag and a note on an event of the {status} analysis {other} are 409 and not stored"
PY
}

# --- a re-ingest keeps them ---------------------------------------------------------------------

annotation_snapshot_file() { echo "${WORK_DIR:?}/annotations-$1.json"; }

# Called directly: what the annotations are right before the re-ingest, for annotations_survive_the_reingest.
snapshot_annotations() { # id
    http GET "/api/analyses/$1/annotations"
    [[ $HTTP_CODE == 200 ]] || { echo "GET annotations answered $HTTP_CODE" >&2; return 1; }
    cp "$RESPONSE_FILE" "$(annotation_snapshot_file "$1")"
}

annotations_survive_the_reingest() {
    {
        annotation_prelude
        printf 'SNAPSHOT = json.load(open("%s"))\n' "$(annotation_snapshot_file "$ANN_ID")"
        cat <<'PY'
now = annotations_of()
assert now["tags"] == SNAPSHOT["tags"], f"tags changed: {SNAPSHOT['tags']} -> {now['tags']}"
assert now["notes"] == SNAPSHOT["notes"], f"notes changed: {SNAPSHOT['notes']} -> {now['notes']}"
assert len(now["tags"]) == 3 and len(now["notes"]) == 3, f"{len(now['tags'])} tags and {len(now['notes'])} notes, wanted 3 and 3"
orphans = [item for item in now["tags"] + now["notes"] if item["orphaned"]]
assert not orphans, f"after the re-ingest {len(orphans)} annotations are orphaned (event id {EVENT_ID} or pid {PID} is gone from the index): {orphans}"
usage = tag_usage()
assert all(usage.get(name) == 1 for name in (CASE_TAG, PROCESS_TAG, EVENT_TAG)), f"tag counts changed: {usage}"
detail = "3 tags and 3 notes identical (links, ids, text, times), none orphaned"
PY
    } | { http GET "/api/analyses/$ANN_ID"; json_assert; }
}

event_and_process_views_still_show_their_annotations() {
    annotation_assert <<'PY'
event = answer("GET", f"/api/analyses/{ID}/events/{EVENT_ID}")
shown = event["annotations"]
assert [link["tag"] for link in shown["tags"]] == [EVENT_TAG], f"the event detail shows tags {shown['tags']}"
assert [note["body"] for note in shown["notes"]] == [EVENT_NOTE], f"the event detail shows notes {shown['notes']}"
process = answer("GET", f"/api/analyses/{ID}/processes/{PID}")
assert process["tags"] == [PROCESS_TAG], f"the process view shows tags {process['tags']}"
assert process["note_count"] == 1, f"the process view counts {process['note_count']} notes"
detail = f"event {EVENT_ID[:8]} shows its tag and note, pid {PID} its tag and one note"
PY
}

# --- removed with the analysis ------------------------------------------------------------------

sql_scalar() { # statement
    compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -c "$1"' _ "$1"
}

annotation_rows_of() { # id -> "<links> <notes> <tags named for the run>"
    sql_scalar "select (select count(*) from tag_link where analysis_id = $1), (select count(*) from note where analysis_id = $1), (select count(*) from tag where name like '$(annotation_tag_prefix "$1")%')" | tr '|' ' '
}

annotation_rows_exist_in_the_database() { # id
    local rows links notes tags
    rows=$(annotation_rows_of "$1") || { echo "psql failed: $rows"; return 1; }
    read -r links notes tags <<<"$rows"
    ((links >= 3 && notes >= 3 && tags >= 3)) || { echo "$links tag links, $notes notes, $tags tags in the database"; return 1; }
    echo "$links tag links, $notes notes, $tags tags in the database"
}

annotation_rows_are_gone_from_the_database() { # id
    local rows
    rows=$(annotation_rows_of "$1") || { echo "psql failed: $rows"; return 1; }
    [[ $rows == "0 0 0" ]] || { echo "left in the database: $rows (tag links, notes, tags named e2e-$1-*)"; return 1; }
    echo "0 tag links, 0 notes, 0 tags"
}

annotations_of_a_deleted_analysis_are_gone() { # id
    http GET "/api/analyses/$1/annotations"
    [[ $HTTP_CODE == 404 ]] || { echo "GET annotations answered $HTTP_CODE"; return 1; }
    http GET /api/tags
    [[ $HTTP_CODE == 200 ]] || { echo "GET /api/tags answered $HTTP_CODE"; return 1; }
    local left
    left=$(body | json_eval '", ".join(t["name"] for t in v if t["name"].startswith("'"$(annotation_tag_prefix "$1")"'"))')
    [[ -z $left ]] || { echo "GET /api/tags still lists: $left"; return 1; }
    echo "annotations answer 404 and /api/tags lists none of the run's tags"
}
