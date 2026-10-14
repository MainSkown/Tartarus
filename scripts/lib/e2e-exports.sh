# Assertions for scripts/e2e.sh on exporting a finished analysis: the three IOC downloads (headers
# and content, the STIX bundle also parsed by the stix2 library when the backend venv has it) and
# the HTML and PDF reports, run as jobs, downloaded and read. The reports and the exports directory
# are checked again after the analysis is deleted. Sourced after e2e-api.sh, e2e-views.sh and
# e2e-annotations.sh, whose choose_annotations sets the tag and the notes the exports must carry.
#
# The content checks take a saved file and nothing else, so scripts/tests/test_e2e_exports.sh can
# run each on a good and a bad file.

REPORT_TIMEOUT=${E2E_REPORT_TIMEOUT:-60}
JOB_POLL_SECONDS=0.5
BACKEND_VENV_PYTHON=${BACKEND_VENV_PYTHON:-backend/.venv/bin/python}
EXPORTS_IN_BACKEND=/data/exports
CSV_HEADER='type,value,context,first_seen,source_process'
# Job ids of every report this run built, read by the checks after the delete. Filled by build_report
# in the caller's shell.
REPORT_JOBS=()

# --- files and headers --------------------------------------------------------------------------

# Saves the answer to FILE and its headers to FILE.headers; sets HTTP_CODE.
download() { # path file
    HTTP_CODE=$(curl -s -m 120 -D "$2.headers" -o "$2" -w '%{http_code}' "$BASE$1") || HTTP_CODE=000
}

header_of() { # file name
    sed -n "s/^$2:[[:space:]]*//Ip" "$1.headers" | tail -n 1 | tr -d '\r'
}

# Runs the Python block on stdin with `path` (the file) and `args` (the rest of the arguments);
# `assert` fails the check with its message, `detail` is printed.
file_assert() { # file args...
    local code
    code=$(cat)
    python3 -I -c '
import sys
path, *args = sys.argv[2:]
scope = {"path": path, "args": args, "detail": ""}
try:
    exec(sys.argv[1], scope)
except AssertionError as error:
    print(error)
    sys.exit(1)
print(scope["detail"])' "$code" "$@"
}

# --- IOC exports --------------------------------------------------------------------------------

ioc_file() { echo "${WORK_DIR:?}/iocs-$1.$2"; }

ioc_export_downloads() { # id format media-type-prefix extension
    local file type disposition
    file=$(ioc_file "$1" "$2")
    download "/api/analyses/$1/export/iocs?format=$2" "$file"
    [[ $HTTP_CODE == 200 ]] || { echo "GET export/iocs?format=$2 answered $HTTP_CODE: $(head -c 300 "$file")"; return 1; }
    type=$(header_of "$file" content-type)
    disposition=$(header_of "$file" content-disposition)
    [[ $type == "$3"* ]] || { echo "Content-Type is '$type', wanted '$3'"; return 1; }
    [[ $disposition == "attachment; filename=\"tartarus-$1-iocs.$4\"" ]] ||
        { echo "Content-Disposition is '$disposition', wanted attachment; filename=\"tartarus-$1-iocs.$4\""; return 1; }
    [[ -s $file ]] || { echo "the file is empty"; return 1; }
    echo "200, $type, $4, $(wc -c <"$file") bytes"
}

stix_bundle_holds_the_sample_and_the_note() { # file sha256 note
    file_assert "$1" "$2" "$3" <<'PY'
import json
sha, note = args
bundle = json.load(open(path))
assert bundle.get("type") == "bundle", f"type is {bundle.get('type')!r}, not 'bundle'"
objects = bundle["objects"]
described = [o for o in objects if o["type"] in ("identity", "malware", "indicator", "note", "relationship")]
old = sorted({o["type"] for o in described if o.get("spec_version") != "2.1"})
assert not old, f"objects of type {old} are not spec_version 2.1"
indicators = [o for o in objects if o["type"] == "indicator" and sha in o["pattern"]]
assert indicators, f"no indicator whose pattern holds the sample sha256 {sha}: {len([o for o in objects if o['type'] == 'indicator'])} indicators"
notes = [o["content"] for o in objects if o["type"] == "note"]
assert note in notes, f"no note object with the analyst's text {note!r} among {notes}"
detail = f"bundle of {len(objects)} objects, spec_version 2.1, an indicator for the sample hash, {len(notes)} note(s)"
PY
}

stix2_is_available() { [[ -x $BACKEND_VENV_PYTHON ]] && "$BACKEND_VENV_PYTHON" -c 'import stix2' 2>/dev/null; }

stix2_parses_the_bundle() { # file
    "$BACKEND_VENV_PYTHON" -I -c '
import sys
import stix2
bundle = stix2.parse(open(sys.argv[1]).read(), allow_custom=False)
print(f"stix2 {stix2.__version__} parsed the bundle: {len(bundle.objects)} objects")' "$1" 2>&1 | tail -n 1
    [[ ${PIPESTATUS[0]} == 0 ]]
}

misp_event_carries_the_tag_and_the_note() { # file id tag note sha256
    file_assert "$1" "$2" "$3" "$4" "$5" <<'PY'
import json
analysis_id, tag, note, sha = args
event = json.load(open(path))["Event"]
assert event["info"].startswith(f"Tartarus analysis #{analysis_id}"), f"Event.info is {event['info']!r}"
tags = [t["name"] for t in event["Tag"]]
assert tag in tags, f"the analyst's tag {tag} is not among Event.Tag: {tags[:5]}"
comments = [a["value"] for a in event["Attribute"] if a["type"] == "comment"]
assert note in comments, f"no comment attribute with the analyst's note {note!r} among {comments}"
hashes = [a for a in event["Attribute"] if a["type"] == "sha256" and a["value"] == sha]
assert hashes and hashes[0]["to_ids"] is True, f"no sha256 attribute with to_ids for the sample {sha}"
detail = f"{event['info']}; tags {len(tags)} with {tag}; the note as a comment; the sample hash with to_ids"
PY
}

csv_has_the_columns_and_the_sample() { # file sha256
    file_assert "$1" "$2" "$CSV_HEADER" <<'PY'
import csv
sha, header = args
with open(path, newline="") as file:
    first_line = file.readline().rstrip("\r\n")
    file.seek(0)
    rows = list(csv.DictReader(file))
assert first_line == header, f"the header is {first_line!r}, wanted {header!r}"
assert [row for row in rows if row["type"] == "hash" and row["value"] == sha], f"no hash row for the sample {sha} among {len(rows)} rows"
timed = [row for row in rows if row["first_seen"]]
assert timed, f"first_seen is empty in all {len(rows)} rows"
assert all(row["first_seen"].endswith("Z") for row in timed), "a first_seen is not a UTC time"
detail = f"{len(rows)} rows, a hash row for the sample, first_seen set in {len(timed)} of them"
PY
}

check_ioc_exports() { # id sha256
    local id=$1 sha=$2
    check "(x) the STIX export downloads with its type and file name" ioc_export_downloads "$id" stix 'application/stix+json;version=2.1' stix.json
    check "(x) the STIX bundle is spec 2.1 with an indicator for the sample's sha256 and the analyst's note" \
        stix_bundle_holds_the_sample_and_the_note "$(ioc_file "$id" stix)" "$sha" "$ANN_CASE_NOTE"
    if stix2_is_available; then
        check "(x) the stix2 library parses the STIX bundle" stix2_parses_the_bundle "$(ioc_file "$id" stix)"
    else
        info "(x) SKIPPED: stix2 is not installed in $BACKEND_VENV_PYTHON (cd backend && uv sync), so the bundle was not parsed by the library"
    fi
    check "(x) the MISP export downloads with its type and file name" ioc_export_downloads "$id" misp application/json misp.json
    check "(x) the MISP event is named for the analysis and carries the analysis tag, the note and the sample hash" \
        misp_event_carries_the_tag_and_the_note "$(ioc_file "$id" misp)" "$id" "$ANN_CASE_TAG" "$ANN_CASE_NOTE" "$sha"
    check "(x) the CSV export downloads with its type and file name" ioc_export_downloads "$id" csv 'text/csv' csv
    check "(x) the CSV has the five columns, a row for the sample's hash and first_seen on event rows" \
        csv_has_the_columns_and_the_sample "$(ioc_file "$id" csv)" "$sha"
}

# --- report content -----------------------------------------------------------------------------

html_report_says() { # file needle...
    file_assert "$@" <<'PY'
import html, re
raw = open(path, encoding="utf-8").read()
without_code = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", without_code)))
missing = [needle for needle in args if re.sub(r"\s+", " ", needle) not in text]
assert not missing, f"the report does not say {missing}; {len(text)} characters of text"
detail = f"says {len(args)} things it should: " + ", ".join(repr(needle[:40]) for needle in args)
PY
}

html_report_lacks() { # file needle...
    file_assert "$@" <<'PY'
import html, re
raw = open(path, encoding="utf-8").read()
text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
found = [needle for needle in args if needle in text or needle in raw]
assert not found, f"the report still holds {found}"
detail = f"none of {len(args)} left-out texts is in it"
PY
}

html_report_has_no_external_reference() { # file
    file_assert "$1" <<'PY'
import re
raw = open(path, encoding="utf-8").read()
quoted = r"""\s*=\s*["']?\s*((?:https?:)?//[^\s"'>)]+)"""
references = re.findall(r"(?i)\b(?:src|href|poster|data|action)" + quoted, raw)
references += re.findall(r"""(?i)url\(\s*["']?\s*((?:https?:)?//[^\s"')]+)""", raw)
references += re.findall(r"""(?i)@import\s+["']?\s*((?:https?:)?//[^\s"';]+)""", raw)
assert not references, f"{len(references)} external references, the first: {references[:3]}"
detail = f"no src, href or url() reaches out of the file ({len(raw)} bytes)"
PY
}

pdf_text_reader_is_available() {
    command -v pdftotext >/dev/null || { [[ -x $BACKEND_VENV_PYTHON ]] && "$BACKEND_VENV_PYTHON" -c 'import pypdf' 2>/dev/null; }
}

pdf_text() { # file
    if command -v pdftotext >/dev/null; then
        pdftotext "$1" -
    else
        "$BACKEND_VENV_PYTHON" -I -c '
import sys, pypdf
print("\n".join(page.extract_text() for page in pypdf.PdfReader(sys.argv[1]).pages))' "$1"
    fi
}

pdf_report_says() { # file needle...
    local file=$1 text
    shift
    [[ $(head -c 4 "$file") == "%PDF" ]] || { echo "the file starts with '$(head -c 8 "$file" | tr -c '[:print:]' '?')', not %PDF"; return 1; }
    text=$(pdf_text "$file" | tr -s '[:space:]' ' ') || { echo "could not read the PDF text"; return 1; }
    local needle missing=()
    for needle; do
        [[ $text == *"$needle"* ]] || missing+=("$needle")
    done
    ((${#missing[@]} == 0)) || { echo "the PDF text does not say: ${missing[*]} (${#text} characters of text)"; return 1; }
    echo "a PDF of $(wc -c <"$file") bytes that says: $*"
}

# --- reports as jobs ----------------------------------------------------------------------------

# A job that has not finished answers 409 to its download. The report of a small run is ready within a
# second, so the answer is read at once after the POST; a job already done at that point could not
# show the refusal, and the detail says so.
download_before_the_job_is_done_is_refused() { # job
    http GET "/api/jobs/$1/download"
    [[ $HTTP_CODE == 409 ]] && { echo "409 while the job was not done"; return 0; }
    [[ $HTTP_CODE == 200 ]] || { echo "the download answered $HTTP_CODE: $(body | head -c 200)"; return 1; }
    http GET "/api/jobs/$1"
    [[ $(body | json_field .status) == done ]] || { echo "the download answered 200 while the job is $(body | json_field .status)"; return 1; }
    echo "the job was already done when asked, so the refusal was not observable"
}

wait_for_job() { # job
    local deadline=$((SECONDS + REPORT_TIMEOUT)) status="?"
    while ((SECONDS < deadline)); do
        http GET "/api/jobs/$1"
        [[ $HTTP_CODE == 200 ]] || { echo "GET /api/jobs/$1 answered $HTTP_CODE"; return 1; }
        status=$(body | json_field .status)
        case $status in
            done) echo "done: $(body | json_field .step)"; return 0 ;;
            failed | interrupted)
                echo "job $1 is $status: result $(body | json_field .result); log: $(body | json_field .log | tail -n 5 | tr '\n' '|')"
                return 1 ;;
        esac
        sleep "$JOB_POLL_SECONDS"
    done
    echo "job $1 is still '$status' after $REPORT_TIMEOUT s ($(body | json_field .step) $(body | json_field .progress)%)"
    return 1
}

report_downloads() { # job file media-type filename
    download "/api/jobs/$1/download" "$2"
    [[ $HTTP_CODE == 200 ]] || { echo "GET /api/jobs/$1/download answered $HTTP_CODE: $(head -c 300 "$2")"; return 1; }
    local type disposition
    type=$(header_of "$2" content-type)
    disposition=$(header_of "$2" content-disposition)
    [[ $type == "$3"* ]] || { echo "Content-Type is '$type', wanted '$3'"; return 1; }
    [[ $disposition == "attachment; filename=\"$4\"" ]] || { echo "Content-Disposition is '$disposition', wanted attachment; filename=\"$4\""; return 1; }
    echo "200, $type, $4, $(wc -c <"$2") bytes"
}

report_is_refused() { # analysis-id expected-code
    http POST "/api/analyses/$1/export/report" -H 'content-type: application/json' -d '{"format": "html", "include": {}}'
    [[ $HTTP_CODE == "$2" ]] || { echo "answered $HTTP_CODE (wanted $2): $(body | head -c 200)"; return 1; }
    echo "answered $HTTP_CODE"
}

# Posts a report, adds its job to REPORT_JOBS and sets REPORT_FILE to where its download is saved
# once it is done. Called directly, never through `check`, so that the globals survive.
# The file of a format is named for the analysis alone, so a later report of the same format
# replaces it: each report is downloaded before the next one is requested.
build_report() { # id format include-json label
    local id=$1 format=$2 include=$3 label=$4 job
    http POST "/api/analyses/$id/export/report" -H 'content-type: application/json' -d "{\"format\": \"$format\", \"include\": $include}"
    if [[ $HTTP_CODE != 202 ]]; then
        fail "(r) POST export/report for the $label answered $HTTP_CODE: $(body | head -c 300)"
        return 1
    fi
    job=$(body | json_field .id)
    REPORT_JOBS+=("$job")
    REPORT_FILE=${WORK_DIR:?}/report-$label.$format
    ok "(r) POST export/report for the $label answered 202 with job $job"
    check "(r) the $label job's download is refused with 409 until it is done" download_before_the_job_is_done_is_refused "$job"
    check "(r) the $label job reaches done within $REPORT_TIMEOUT s" wait_for_job "$job" || return 1
    check "(r) the $label job downloads as tartarus-report-$id.$format" report_downloads "$job" "$REPORT_FILE" \
        "$([[ $format == pdf ]] && echo application/pdf || echo 'text/html')" "tartarus-report-$id.$format"
}

check_reports() { # id sample-name sha256
    local id=$1 sample=$2 sha=$3
    check "(r) a report for an analysis that does not exist answers 404" report_is_refused 999999999 404
    build_report "$id" html '{"notes": true, "screenshots": true, "raw_iocs": true}' "html with notes" &&
        check "(r) the HTML report says the sample's name and hash, the analyst's notes and the analysis tag" \
            html_report_says "$REPORT_FILE" "$sample" "$sha" "$ANN_CASE_NOTE" "$ANN_PROCESS_NOTE" "$ANN_EVENT_NOTE" "$ANN_CASE_TAG" &&
        check "(r) the HTML report is one file: no src, href or url() points outside it" html_report_has_no_external_reference "$REPORT_FILE"
    build_report "$id" pdf '{"notes": true, "screenshots": true, "raw_iocs": true}' "pdf with notes" &&
        if pdf_text_reader_is_available; then
            check "(r) the PDF report is a PDF and its text says the sample's name, the analyst's note and the analysis tag" \
                pdf_report_says "$REPORT_FILE" "$sample" "$ANN_CASE_NOTE" "$ANN_CASE_TAG"
        else
            info "(r) SKIPPED: neither pdftotext nor pypdf (in $BACKEND_VENV_PYTHON) is available, so the PDF text was not read"
            check "(r) the PDF report starts with %PDF" bash -c '[[ $(head -c 4 "$1") == "%PDF" ]]' _ "$REPORT_FILE"
        fi
    build_report "$id" html '{"notes": false, "screenshots": false, "raw_iocs": false}' "html without notes" &&
        check "(r) with include.notes false the HTML report still says the sample and the tag but none of the three notes" \
            html_report_without_the_notes "$REPORT_FILE" "$sample" "$ANN_CASE_TAG" "$ANN_CASE_NOTE" "$ANN_PROCESS_NOTE" "$ANN_EVENT_NOTE"
}

html_report_without_the_notes() { # file sample tag note...
    local file=$1 sample=$2 tag=$3
    shift 3
    html_report_says "$file" "$sample" "$tag" >/dev/null && html_report_lacks "$file" "$@"
}

# --- after the delete ---------------------------------------------------------------------------

exports_directory_holds_both_reports() { # id
    local listing
    listing=$(compose exec -T backend ls "$EXPORTS_IN_BACKEND/$1" 2>&1) || { echo "no $EXPORTS_IN_BACKEND/$1 in the backend: $listing"; return 1; }
    [[ $listing == *"tartarus-report-$1.html"* && $listing == *"tartarus-report-$1.pdf"* ]] || { echo "the directory holds: $(tr '\n' ' ' <<<"$listing")"; return 1; }
    echo "$EXPORTS_IN_BACKEND/$1 holds $(tr '\n' ' ' <<<"$listing")"
}

exports_directory_is_gone() { # id
    ! compose exec -T backend test -e "$EXPORTS_IN_BACKEND/$1" 2>/dev/null || { echo "$EXPORTS_IN_BACKEND/$1 is still in the backend"; return 1; }
}

report_downloads_are_gone() { # job...
    (($# > 0)) || { echo "no report job was built, so there is nothing to check"; return 1; }
    local job still_served=()
    for job; do
        http GET "/api/jobs/$job/download"
        [[ $HTTP_CODE == 404 ]] || still_served+=("job $job answered $HTTP_CODE")
    done
    ((${#still_served[@]} == 0)) || { echo "${still_served[*]}"; return 1; }
    echo "$# report jobs answer 404"
}
