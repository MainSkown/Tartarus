#!/usr/bin/env bash
# Tests scripts/lib/e2e-exports.sh: the content checks `make e2e` runs on a downloaded IOC export or
# report, each on a good file and on files that are wrong in one way, and the job waits against
# fixtures/fake_jobs_api.py. A check that could never fail would be found here and not on the real stack.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAKE_API=$REPO/scripts/tests/fixtures/fake_jobs_api.py
WORK_DIR="$(mktemp -d)"
SERVER_PID=""
trap 'stop_server; rm -rf "$WORK_DIR"' EXIT

cd "$REPO" || exit 1
source "$REPO/scripts/lib/e2e-api.sh"
source "$REPO/scripts/lib/e2e-views.sh"
source "$REPO/scripts/lib/e2e-exports.sh"
JOB_POLL_SECONDS=0.05
REPORT_TIMEOUT=2

SHA=$(printf 'a%.0s' {1..64})
NOTE="analyst verdict: benign test sample"
TAG=e2e-7-case

# `fails_saying file-check-and-args... -- words`: the check must fail and its message must hold the words.
fails_saying() {
    local words=${*: -1} output
    set -- "${@:1:$# - 1}"
    if output=$("$@" 2>&1); then echo "passed, but should fail saying '$words': $output" >&2; return 1; fi
    [[ $output == *"$words"* && $output != *Traceback* ]] || { echo "failed without '$words': $output" >&2; return 1; }
}

write() { # file python-expression-building-the-content
    python3 -I -c "import json, sys; sys.stdout.write($2)" >"$1"
}

# --- STIX ---------------------------------------------------------------------------------------

stix_with() { # file overrides-python
    write "$1" "json.dumps((lambda b: ($2, b)[1])({
        'type': 'bundle',
        'objects': [
            {'type': 'identity', 'spec_version': '2.1'},
            {'type': 'indicator', 'spec_version': '2.1', 'pattern': \"[file:hashes.'SHA-256' = '$SHA']\"},
            {'type': 'note', 'spec_version': '2.1', 'content': '$NOTE'},
        ]}))"
}

test_a_good_stix_bundle_passes() {
    stix_with "$WORK_DIR/s" 'None' && stix_bundle_holds_the_sample_and_the_note "$WORK_DIR/s" "$SHA" "$NOTE" >/dev/null
}
test_a_stix_object_that_is_not_a_bundle_is_caught() {
    stix_with "$WORK_DIR/s" "b.update(type='object')" && fails_saying stix_bundle_holds_the_sample_and_the_note "$WORK_DIR/s" "$SHA" "$NOTE" "not 'bundle'"
}
test_an_old_spec_version_is_caught() {
    stix_with "$WORK_DIR/s" "b['objects'][1].update(spec_version='2.0')" && fails_saying stix_bundle_holds_the_sample_and_the_note "$WORK_DIR/s" "$SHA" "$NOTE" "not spec_version 2.1"
}
test_a_bundle_without_the_sample_indicator_is_caught() {
    stix_with "$WORK_DIR/s" "b['objects'][1].update(pattern='[ipv4-addr:value = \"1.2.3.4\"]')" && fails_saying stix_bundle_holds_the_sample_and_the_note "$WORK_DIR/s" "$SHA" "$NOTE" "no indicator whose pattern holds the sample sha256"
}
test_a_bundle_without_the_note_is_caught() {
    stix_with "$WORK_DIR/s" "b['objects'].pop()" && fails_saying stix_bundle_holds_the_sample_and_the_note "$WORK_DIR/s" "$SHA" "$NOTE" "no note object"
}

# --- MISP ---------------------------------------------------------------------------------------

misp_with() { # file overrides-python
    write "$1" "json.dumps((lambda e: ($2, {'Event': e})[1])({
        'info': 'Tartarus analysis #7 – e2e-a.exe',
        'Tag': [{'name': 'tlp:amber'}, {'name': '$TAG'}],
        'Attribute': [
            {'type': 'sha256', 'value': '$SHA', 'to_ids': True},
            {'type': 'comment', 'value': '$NOTE'},
        ]}))"
}

misp_check() { misp_event_carries_the_tag_and_the_note "$WORK_DIR/m" 7 "$TAG" "$NOTE" "$SHA"; }

test_a_good_misp_event_passes() { misp_with "$WORK_DIR/m" None && misp_check >/dev/null; }
test_a_misp_event_named_for_another_analysis_is_caught() { misp_with "$WORK_DIR/m" "e.update(info='Tartarus analysis #8')" && fails_saying misp_check "Event.info is"; }
test_a_misp_event_without_the_analyst_tag_is_caught() { misp_with "$WORK_DIR/m" "e['Tag'].pop()" && fails_saying misp_check "is not among Event.Tag"; }
test_a_misp_event_without_the_note_is_caught() { misp_with "$WORK_DIR/m" "e['Attribute'].pop()" && fails_saying misp_check "no comment attribute"; }
test_a_sample_hash_without_to_ids_is_caught() { misp_with "$WORK_DIR/m" "e['Attribute'][0].update(to_ids=False)" && fails_saying misp_check "no sha256 attribute with to_ids"; }

# --- CSV ----------------------------------------------------------------------------------------

csv_check() { csv_has_the_columns_and_the_sample "$WORK_DIR/c" "$SHA"; }

test_a_good_csv_passes() {
    printf '%s\nhash,%s,Submitted sample,,\ndomain,x.example,DNS query,2026-10-14T16:43:32.062Z,e2e-a.exe (9)\n' "$CSV_HEADER" "$SHA" >"$WORK_DIR/c" && csv_check >/dev/null
}
test_a_csv_with_another_header_is_caught() {
    printf 'type,value\nhash,%s\n' "$SHA" >"$WORK_DIR/c" && fails_saying csv_check "the header is"
}
test_a_csv_without_the_sample_row_is_caught() {
    printf '%s\ndomain,x.example,DNS query,2026-10-14T16:43:32.062Z,\n' "$CSV_HEADER" >"$WORK_DIR/c" && fails_saying csv_check "no hash row for the sample"
}
test_a_csv_with_no_first_seen_is_caught() {
    printf '%s\nhash,%s,Submitted sample,,\n' "$CSV_HEADER" "$SHA" >"$WORK_DIR/c" && fails_saying csv_check "first_seen is empty"
}

# --- HTML report --------------------------------------------------------------------------------

test_html_text_is_found_through_tags_and_entities() {
    printf '<html><body><p>Verdict: <b>benign</b> &amp; quiet</p><style>.x{color:red}</style></body></html>' >"$WORK_DIR/h" &&
        html_report_says "$WORK_DIR/h" "Verdict: benign & quiet" >/dev/null
}
test_a_text_the_html_does_not_say_is_caught() {
    printf '<p>one thing</p>' >"$WORK_DIR/h" && fails_saying html_report_says "$WORK_DIR/h" "one thing" "another" "does not say ['another']"
}
test_text_that_is_only_in_a_style_block_does_not_count() {
    printf '<style>.verdict{content:"benign"}</style><p>nothing</p>' >"$WORK_DIR/h" && fails_saying html_report_says "$WORK_DIR/h" "benign" "does not say"
}
test_a_left_out_text_that_is_in_the_html_is_caught() {
    printf '<p>%s</p>' "$NOTE" >"$WORK_DIR/h" && fails_saying html_report_lacks "$WORK_DIR/h" "$NOTE" "still holds"
}
test_a_left_out_text_that_is_not_there_passes() {
    printf '<p>other</p>' >"$WORK_DIR/h" && html_report_lacks "$WORK_DIR/h" "$NOTE" >/dev/null
}
test_a_self_contained_page_passes_even_with_urls_in_its_text() {
    printf '<svg xmlns="http://www.w3.org/2000/svg"></svg><img src="data:image/png;base64,AAAA"><a href="#top">top</a><p>http://evil.example/x is an IOC</p><style>.a{background:url(data:image/png;base64,AA)}</style>' >"$WORK_DIR/h" &&
        html_report_has_no_external_reference "$WORK_DIR/h" >/dev/null
}
external_reference_is_caught() { # html
    printf '%s' "$1" >"$WORK_DIR/h" && fails_saying html_report_has_no_external_reference "$WORK_DIR/h" "external references"
}
test_an_external_image_is_caught() { external_reference_is_caught '<img src="https://cdn.example/a.png">'; }
test_an_external_link_is_caught() { external_reference_is_caught "<a href='http://x.example/'>x</a>"; }
test_an_external_stylesheet_is_caught() { external_reference_is_caught '<link rel=stylesheet href=//fonts.example/a.css>'; }
test_an_external_css_url_is_caught() { external_reference_is_caught '<style>.a{background:url("https://x.example/a.png")}</style>'; }
test_an_external_import_is_caught() { external_reference_is_caught '<style>@import "http://x.example/a.css";</style>'; }

# --- PDF report ---------------------------------------------------------------------------------

# A one-page PDF with the text on it, enough for pdftotext and pypdf.
minimal_pdf() { # file text
    python3 -I - "$1" "$2" <<'PY'
import sys
path, text = sys.argv[1:]
stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
objects = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
]
out, offsets = b"%PDF-1.4\n", []
for number, body in enumerate(objects, 1):
    offsets.append(len(out))
    out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
xref = len(out)
out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
open(path, "wb").write(out)
PY
}

test_a_pdf_that_says_the_texts_passes() {
    pdf_text_reader_is_available || { echo "no pdf reader here" >&2; return 1; }
    minimal_pdf "$WORK_DIR/p" "e2e-a.exe and the analyst verdict" && pdf_report_says "$WORK_DIR/p" "e2e-a.exe" "analyst verdict" >/dev/null
}
test_a_pdf_missing_a_text_is_caught() {
    pdf_text_reader_is_available || return 1
    minimal_pdf "$WORK_DIR/p" "only this" && fails_saying pdf_report_says "$WORK_DIR/p" "only this" "the note" "does not say: the note"
}
test_a_file_that_is_not_a_pdf_is_caught() {
    printf '<html>not a pdf</html>' >"$WORK_DIR/p" && fails_saying pdf_report_says "$WORK_DIR/p" "x" "not %PDF"
}

# --- headers ------------------------------------------------------------------------------------

test_a_header_is_found_whatever_its_case_and_without_the_return() {
    printf 'HTTP/1.1 200 OK\r\nContent-Type: text/csv; charset=utf-8\r\ncontent-disposition: attachment; filename="a.csv"\r\n\r\n' >"$WORK_DIR/f.headers" &&
        [[ $(header_of "$WORK_DIR/f" content-type) == "text/csv; charset=utf-8" && $(header_of "$WORK_DIR/f" Content-Disposition) == 'attachment; filename="a.csv"' ]]
}
test_a_missing_header_is_empty() {
    printf 'HTTP/1.1 200 OK\r\n\r\n' >"$WORK_DIR/f.headers" && [[ -z $(header_of "$WORK_DIR/f" content-type) ]]
}

# --- jobs ---------------------------------------------------------------------------------------

start_server() { # mode
    local port tries=0
    port=$(python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
    python3 -I "$FAKE_API" "$port" "$1" &
    SERVER_PID=$!
    BASE=http://127.0.0.1:$port
    until curl -s -o /dev/null -m 1 "$BASE/api/jobs/9"; do
        ((++tries > 50)) && { echo "the fake API did not start" >&2; return 1; }
        sleep 0.1
    done
}

stop_server() { [[ -n $SERVER_PID ]] && { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }; SERVER_PID=""; return 0; }

test_a_job_that_finishes_is_done() { start_server done && wait_for_job 1 >/dev/null; }
test_a_failed_job_is_reported_with_its_log() { start_server failed && fails_saying wait_for_job 1 "weasyprint exploded"; }
test_a_job_that_never_ends_times_out_saying_where_it_stands() { start_server stuck && fails_saying wait_for_job 1 "still 'running' after 2 s"; }
test_a_download_before_done_is_refused_with_409() { start_server done && [[ $(download_before_the_job_is_done_is_refused 1) == "409 while the job was not done" ]]; }
test_a_job_already_done_says_the_refusal_was_not_observable() {
    start_server early-done && [[ $(download_before_the_job_is_done_is_refused 1) == *"not observable"* ]]
}
test_a_download_that_works_before_the_job_is_done_is_caught() {
    start_server download-ignores-state && fails_saying download_before_the_job_is_done_is_refused 1 "answered 200 while the job is"
}

failures=0
for name in $(declare -F | awk '{print $3}' | grep '^test_'); do
    stop_server
    if "$name"; then echo "ok   $name"; else echo "FAIL $name"; failures=$((failures + 1)); fi
done
((failures == 0)) && echo "all tests passed"
exit "$failures"
