# Assertions for scripts/e2e.sh on a submission from a password-protected zip: the member list
# (POST /api/analyses/archive-members), the submission with `archive_password` and `archive_entry`,
# the password kept out of every answer and out of the backend log, the chosen entry running and the
# decoy next to it not, and the refusals (a wrong password, an entry the zip lacks) leaving no
# analysis and no sample behind. Sourced after e2e-api.sh and e2e-views.sh (json_assert); expects the
# helpers scripts/e2e.sh defines (remember, unique_sample, sha256_of, stored_sample_exists).
# Z1 to Z8 in the check descriptions are the groups of docs/features/zip-submission-plan.md's proof.
# Also expects e2e-exports.sh (build_report, html_report_says, html_report_lacks) to be sourced.

# Distinctive on purpose: the log check greps for it, and the default `infected` would match anything.
ARCHIVE_PASSWORD=s3cret-Pass
ARCHIVE_WRONG_PASSWORD=wrong-Pass-9
ARCHIVE_ENTRY=payload.exe
ARCHIVE_DECOY=other.exe
ARCHIVE_MEMBERS="$ARCHIVE_ENTRY $ARCHIVE_DECOY readme.txt"

# --- the zip ---------------------------------------------------------------------------------------

archive_members_dir() { echo "${WORK_DIR:?}/archive-members"; }

archive_member_sha256() { sha256_of "$(archive_members_dir)/$1"; }

# The entry and the decoy are two different executables (the benign sample with their own trailing
# bytes), so a decoy that ran would show as a process of its own.
stage_archive_members() { # directory
    mkdir -p "$1"
    mv "$(unique_sample "$ARCHIVE_ENTRY")" "$1/$ARCHIVE_ENTRY"
    mv "$(unique_sample "$ARCHIVE_DECOY")" "$1/$ARCHIVE_DECOY"
    echo "Harmless: the Tartarus self-test sample next to a decoy." >"$1/readme.txt"
}

# The AES zip is built by pyzipper inside the backend container, from a tar on stdin to a zip on
# stdout (scripts/lib/aes_zip.py), because no host tool here writes AES.
build_archive_zip() { # output-path
    local members
    members=$(archive_members_dir)
    stage_archive_members "$members" || return 1
    tar -C "$members" -c . | compose exec -T backend python -I -c "$(cat scripts/lib/aes_zip.py)" "$ARCHIVE_PASSWORD" >"$1"
    [[ -s $1 ]] && [[ $(head -c 2 "$1") == PK ]]
}

archive_options() { # password entry
    printf '{"archive_password": "%s", "archive_entry": "%s"%s}' "$1" "$2" "${E2E_GUEST:+, \"guest\": \"$E2E_GUEST\"}"
}

# --- Z1: the member list -----------------------------------------------------------------------------

list_archive_members() { # zip [password]
    http POST /api/analyses/archive-members -F "file=@$1" ${2:+-F "password=$2"}
}

archive_members_lists_the_three_members_with_the_right_password() { # zip
    list_archive_members "$1" "$ARCHIVE_PASSWORD"
    [[ $HTTP_CODE == 200 ]] || { echo "answered $HTTP_CODE: $(body)"; return 1; }
    json_assert <<PY
names = [member["name"] for member in v["members"]]
assert len(names) == 3, f"lists {len(names)} members: {names}"
assert sorted(names) == sorted("$ARCHIVE_MEMBERS".split()), f"the members are {names}"
unfit = [member["name"] for member in v["members"] if member["unsafe"] or member["unsupported"]]
assert not unfit, f"members marked unsafe or unsupported: {unfit}"
assert v["password_ok"] is True, f"password_ok is {v['password_ok']!r} for the right password"
detail = f"200, members {names}, password_ok true"
PY
}

archive_members_reports_a_wrong_password() { # zip
    list_archive_members "$1" "$ARCHIVE_WRONG_PASSWORD"
    [[ $HTTP_CODE == 200 ]] || { echo "answered $HTTP_CODE: $(body)"; return 1; }
    json_assert <<PY
assert v["password_ok"] is False, f"password_ok is {v['password_ok']!r} for a wrong password"
detail = "200, password_ok false"
PY
}

archive_members_refuses_a_file_that_is_not_a_zip() { # file
    list_archive_members "$1" "$ARCHIVE_PASSWORD"
    [[ $HTTP_CODE == 422 ]] || { echo "answered $HTTP_CODE (wanted 422): $(body)"; return 1; }
    echo "422"
}

# --- Z2: the submission, and the password in no answer -----------------------------------------------

# Looks in the raw bytes, so a password in any field, or in an error message, is found.
body_never_holds_the_password() { # what
    if grep -qF -- "$ARCHIVE_PASSWORD" "$RESPONSE_FILE"; then
        echo "$1 holds the password: $(body)"
        return 1
    fi
    [[ -s $RESPONSE_FILE ]] || { echo "$1 is empty, so it proves nothing"; return 1; }
    echo "the password is absent from $1 ($(wc -c <"$RESPONSE_FILE") bytes)"
}

the_create_response_hides_the_password() {
    body_never_holds_the_password "the create response"
}

the_analysis_hides_the_password() { # id
    http GET "/api/analyses/$1"
    [[ $HTTP_CODE == 200 ]] || { echo "GET answered $HTTP_CODE"; return 1; }
    body_never_holds_the_password "GET /api/analyses/$1"
}

the_list_hides_the_password() { # id
    http GET "/api/analyses?limit=200"
    [[ $HTTP_CODE == 200 ]] || { echo "GET answered $HTTP_CODE"; return 1; }
    grep -qF "\"id\":$1," "$RESPONSE_FILE" || grep -qF "\"id\": $1," "$RESPONSE_FILE" || { echo "analysis $1 is not in the list, so it proves nothing"; return 1; }
    body_never_holds_the_password "the list GET /api/analyses"
}

archive_analysis_records_the_zip_and_the_entry() { # id
    http GET "/api/analyses/$1"
    json_assert <<PY
assert v["status"] == "done", f"status {v['status']}: {v['error']}"
assert v["filename"].endswith(".zip"), f"the filename {v['filename']!r} does not end in .zip"
assert v["options"].get("archive_entry") == "$ARCHIVE_ENTRY", f"options.archive_entry is {v['options'].get('archive_entry')!r}"
assert v["options"].get("package") == "zip", f"options.package is {v['options'].get('package')!r}"
detail = f"done, {v['filename']}, archive_entry {v['options']['archive_entry']}, package zip"
PY
}

# --- Z3: the entry ran and only it -------------------------------------------------------------------

events_matching() { # id query -> count
    http POST "/api/analyses/$1/events/search" -H 'content-type: application/json' \
        -d "{\"query\": \"${2//\"/\\\"}\", \"size\": 1}"
    [[ $HTTP_CODE == 200 ]] || { echo "the search answered $HTTP_CODE: $(body)" >&2; return 1; }
    body | json_field .total
}

# The sample the analyzer starts is a process of its own, so its name is the member's.
process_created_events_of() { # id image-name -> count
    events_matching "$1" "event.action:process-created AND process.name:\"$2\""
}

the_entry_ran_and_the_decoy_did_not() { # id
    local entry_count decoy_count
    entry_count=$(process_created_events_of "$1" "$ARCHIVE_ENTRY") || return 1
    decoy_count=$(process_created_events_of "$1" "$ARCHIVE_DECOY") || return 1
    ((entry_count >= 1)) || { echo "no process-created event for $ARCHIVE_ENTRY (the decoy has $decoy_count)"; return 1; }
    ((decoy_count == 0)) || { echo "$decoy_count process-created events for the decoy $ARCHIVE_DECOY (the entry has $entry_count)"; return 1; }
    echo "$entry_count process-created for $ARCHIVE_ENTRY, 0 for $ARCHIVE_DECOY"
}

# --- Z7: the hash of the file that ran ---------------------------------------------------------------

# The entry and the decoy each carry their own trailing bytes, so only the payload's own hash
# identifies the file the guest ran; the zip's hash and the decoy's are the wrong answers a lazy
# implementation would give.
entry_sha256_is_the_payloads_hash() { # id payload-sha decoy-sha zip-sha
    http GET "/api/analyses/$1"
    json_assert <<PY
entry_sha = ((v.get("summary") or {}).get("sample") or {}).get("entry_sha256")
assert entry_sha is not None, "summary.sample.entry_sha256 is null"
assert entry_sha != "$3", "entry_sha256 is the decoy's hash"
assert entry_sha != "$4", "entry_sha256 is the zip's hash"
assert entry_sha == "$2", f"entry_sha256 is {entry_sha}, the $ARCHIVE_ENTRY in the zip hashes to $2"
detail = f"entry_sha256 {entry_sha} is the hash of the $ARCHIVE_ENTRY inside the zip"
PY
}

# The report as an HTML job (the cheap form: no PDF engine), through the export helpers.
check_archive_report() { # id zip-name zip-sha payload-sha
    build_report "$1" html '{"notes": false, "screenshots": false, "raw_iocs": false}' "zip report" || return 1
    check "(z7) the HTML report says the archive name, the entry name and both hashes" \
        html_report_says "$REPORT_FILE" "$2" "$ARCHIVE_ENTRY" "$3" "$4"
    check "(z7) the HTML report does not hold the archive password" html_report_lacks "$REPORT_FILE" "$ARCHIVE_PASSWORD"
}

# --- Z8: a zip whose name does not end in .zip ---------------------------------------------------------

analysis_keeps_the_name_and_the_entry() { # id filename
    http GET "/api/analyses/$1"
    json_assert <<PY
assert v["status"] == "done", f"status {v['status']}: {v['error']}"
assert v["filename"] == "$2", f"the filename is {v['filename']!r}"
assert v["options"].get("archive_entry") == "$ARCHIVE_ENTRY", f"options.archive_entry is {v['options'].get('archive_entry')!r}"
detail = f"done, {v['filename']}, archive_entry {v['options']['archive_entry']}"
PY
}

cape_analysis_log() { # cape-task-id
    compose exec -T cape sh -c "tail -n 40 /opt/CAPEv2/storage/analyses/$1/analysis.log" 2>&1
}

# For the reader of a failed run: what the analysis and CAPE's own log say, before the cleanup deletes both.
show_archive_run_evidence() { # id
    local task
    info "analysis $1: status $(analysis_field "$1" status), error $(analysis_field "$1" error)"
    task=$(analysis_field "$1" cape_task_id) || return 1
    info "analysis.log of CAPE task $task (last 40 lines):"
    cape_analysis_log "$task" | sed 's/^/[INFO]   /'
}

# --- Z4 and Z5: a refused submission leaves nothing behind -------------------------------------------

analyses_total() {
    http GET "/api/analyses?limit=1"
    [[ $HTTP_CODE == 200 ]] || { echo "GET answered $HTTP_CODE" >&2; return 1; }
    body | json_field .total
}

# The fields a 422 names, as dotted paths without the leading "body", comma separated.
refused_fields() {
    body | json_eval '",".join(".".join(map(str, field["location"][1:])) for field in v["error"]["details"]["fields"])'
}

# 422 on the field the options name, with neither the password in the answer nor an analysis or a
# stored sample left.
archive_submission_is_refused_leaving_nothing() { # zip options field
    local before after sha fields
    before=$(analyses_total) || return 1
    sha=$(sha256_of "$1")
    http POST /api/analyses -F "file=@$1" -F "options=$2"
    [[ $HTTP_CODE == 422 ]] || { echo "answered $HTTP_CODE (wanted 422): $(body)"; return 1; }
    fields=$(refused_fields) || { echo "the refusal is not the API's error document: $(body)"; return 1; }
    [[ $fields == "$3" ]] || { echo "the refusal names '$fields', not $3"; return 1; }
    grep -qF -e "$ARCHIVE_PASSWORD" -e "$ARCHIVE_WRONG_PASSWORD" "$RESPONSE_FILE" && { echo "the refusal holds a password"; return 1; }
    after=$(analyses_total) || return 1
    [[ $before == "$after" ]] || { echo "there were $before analyses before and $after after"; return 1; }
    ! stored_sample_exists "$sha" || { echo "the sample $sha is still stored"; return 1; }
    echo "422 on $3; $after analyses before and after; sample not stored"
}

a_wrong_password_is_refused_leaving_nothing() { # zip
    archive_submission_is_refused_leaving_nothing "$1" "$(archive_options "$ARCHIVE_WRONG_PASSWORD" "$ARCHIVE_ENTRY")" options.archive_password
}

an_entry_the_zip_lacks_is_refused_leaving_nothing() { # zip
    archive_submission_is_refused_leaving_nothing "$1" "$(archive_options "$ARCHIVE_PASSWORD" "absent.exe")" options.archive_entry
}

# --- Z6: the backend log -----------------------------------------------------------------------------

backend_log() { compose logs --no-color --no-log-prefix backend 2>&1; }

# A log that shows no request would hold no password either, so the submission must be in it.
the_backend_log_never_holds() { # password what
    local log lines hits
    log=$(backend_log)
    lines=$(wc -l <<<"$log")
    grep -q 'POST /api/analyses' <<<"$log" || { echo "the log ($lines lines) shows no submission, so it proves nothing"; return 1; }
    hits=$(grep -cF -- "$1" <<<"$log")
    ((hits == 0)) || { echo "$2 appears $hits times in the backend log"; return 1; }
    echo "$2 appears 0 times in $lines log lines"
}

# --- the group -------------------------------------------------------------------------------------------

check_zip_without_the_extension() { # zip
    local renamed=$WORK_DIR/e2e-archive.bin id
    cp "$1" "$renamed"
    submit_sample "$renamed" "$(archive_options "$ARCHIVE_PASSWORD" "$ARCHIVE_ENTRY")" || { fail "(z8) POST /api/analyses did not answer 201 for the same zip named e2e-archive.bin"; return 1; }
    id=$SUBMITTED_ID
    remember "$id"
    ok "(z8) the same zip bytes named e2e-archive.bin are accepted with analysis id $id"
    check "(z8) analysis $id reaches done" wait_for_status "$id" done "$ANALYSIS_TIMEOUT" || { show_archive_run_evidence "$id"; return 1; }
    check "(z8) it is done under the name e2e-archive.bin and options keep archive_entry $ARCHIVE_ENTRY" analysis_keeps_the_name_and_the_entry "$id" e2e-archive.bin
    check "(z8) analysis $id has a process-created event for $ARCHIVE_ENTRY and none for $ARCHIVE_DECOY" the_entry_ran_and_the_decoy_did_not "$id" ||
        show_archive_run_evidence "$id"
}

check_zip_submission() {
    local zip=$WORK_DIR/e2e-archive.zip refused_zip=$WORK_DIR/e2e-archive-refused.zip not_a_zip=$WORK_DIR/e2e-not-a-zip.txt id payload_sha decoy_sha zip_sha
    build_archive_zip "$refused_zip" && build_archive_zip "$zip" || { fail "(z) could not build the AES zips in the backend container"; return 1; }
    payload_sha=$(archive_member_sha256 "$ARCHIVE_ENTRY") decoy_sha=$(archive_member_sha256 "$ARCHIVE_DECOY") zip_sha=$(sha256_of "$zip")
    echo "this is plain text, not a zip" >"$not_a_zip"
    check "(z1) archive-members on the AES zip with the right password answers 200 with the three members and password_ok true" \
        archive_members_lists_the_three_members_with_the_right_password "$zip"
    check "(z1) with a wrong password it answers password_ok false" archive_members_reports_a_wrong_password "$zip"
    check "(z1) a file that is not a zip answers 422" archive_members_refuses_a_file_that_is_not_a_zip "$not_a_zip"
    submit_sample "$zip" "$(archive_options "$ARCHIVE_PASSWORD" "$ARCHIVE_ENTRY")" || { fail "(z2) POST /api/analyses did not answer 201 for the AES zip"; return 1; }
    id=$SUBMITTED_ID
    remember "$id"
    ok "(z2) the AES zip is accepted with analysis id $id"
    check "(z2) the create response does not hold the archive password" the_create_response_hides_the_password
    check "(z2) analysis $id reaches done" wait_for_status "$id" done "$ANALYSIS_TIMEOUT"
    check "(z2) it is done, its filename ends .zip and options keep archive_entry $ARCHIVE_ENTRY" archive_analysis_records_the_zip_and_the_entry "$id"
    check "(z2) GET /api/analyses/$id does not hold the archive password" the_analysis_hides_the_password "$id"
    check "(z2) the list does not hold the archive password" the_list_hides_the_password "$id"
    check "(z3) analysis $id has a process-created event for $ARCHIVE_ENTRY and none for $ARCHIVE_DECOY" the_entry_ran_and_the_decoy_did_not "$id"
    check "(z7) summary.sample.entry_sha256 is the hash of the $ARCHIVE_ENTRY inside the zip, not null, not the decoy's, not the zip's" \
        entry_sha256_is_the_payloads_hash "$id" "$payload_sha" "$decoy_sha" "$zip_sha"
    check_archive_report "$id" e2e-archive.zip "$zip_sha" "$payload_sha"
    check "(z4) a wrong password at submit answers 422 on options.archive_password and leaves no analysis and no sample" \
        a_wrong_password_is_refused_leaving_nothing "$refused_zip"
    check "(z5) an entry that is not in the zip answers 422 on options.archive_entry and leaves no analysis and no sample" \
        an_entry_the_zip_lacks_is_refused_leaving_nothing "$refused_zip"
    check_zip_without_the_extension "$zip"
    check "(z6) the backend log of the whole run never holds the Z2 password" the_backend_log_never_holds "$ARCHIVE_PASSWORD" "the password"
    check "(z6) nor the wrong password of Z4" the_backend_log_never_holds "$ARCHIVE_WRONG_PASSWORD" "the wrong password"
}
