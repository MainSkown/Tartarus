"""A stand-in for the zip submission API, small enough to read, used by test_e2e_zip.sh.

It answers what scripts/lib/e2e-zip.sh calls: the member list of a zip, a submission with
`archive_password` and `archive_entry` (refused with 422 for a wrong password or an entry the zip
lacks), the analysis and the list that must not hold the password, and the events search that finds
a process-created event for the entry only. A file is "a zip" when it starts with `PK`; its members
are always payload.exe, other.exe and readme.txt.
It also builds the HTML report as a job and says, in the analysis summary and in the report, the
hash of the entry the test put in the environment (`FAKE_ENTRY_SHA`, `FAKE_DECOY_SHA`).
`python3 fake_zip_api.py <port> <password> [fault ...]` serves a correct API; each fault names one
way it goes wrong, so the test can show the matching check fails. `GET /calls` lists the requests
seen and `GET /stored/<sha256>` answers whether that sample file is kept.
"""

import hashlib
import json
import os
import re
import sys
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASSWORD = sys.argv[2]
FAULTS = set(sys.argv[3:])
MEMBERS = ["payload.exe", "other.exe", "readme.txt"]
ANALYSES: dict[int, dict] = {}
STORED: set[str] = set()
CALLS: list[str] = []
ENTRY_SHA = os.environ.get("FAKE_ENTRY_SHA", "")
DECOY_SHA = os.environ.get("FAKE_DECOY_SHA", "")


def parse_multipart(content_type, body):
    message = BytesParser(policy=default).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    return {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}


def member_listing(password):
    members = MEMBERS[:2] if "two_members" in FAULTS else MEMBERS
    password_ok = True if "wrong_password_is_ok" in FAULTS else password == PASSWORD
    return {"members": [{"name": name, "size": 10, "encrypted": True, "unsafe": False, "unsupported": False} for name in members], "password_ok": password_ok}


def refusal(location):
    field = {"location": ["body", *location.split(".")], "message": "refused", "type": "value_error.archive"}
    return {"error": {"code": "validation_error", "message": "Request validation failed", "details": {"fields": [field]}}}


def analysis_read(analysis, leaks_password=False):
    options = {"package": "exe" if "package_not_zip" in FAULTS else "zip", "archive_entry": analysis["entry"]}
    if "entry_missing_from_options" in FAULTS:
        del options["archive_entry"]
    if leaks_password:
        options["archive_password"] = PASSWORD
    filename = analysis["filename"].removesuffix(".zip") if "filename_not_zip" in FAULTS else analysis["filename"]
    failed = "analysis_fails" in FAULTS or is_unrunnable(analysis)
    return {
        "id": analysis["id"],
        "status": "failed" if failed else "done",
        "filename": filename,
        "options": options,
        "error": None,
        "cape_task_id": 100 + analysis["id"],
        "summary": {"sample": {"name": filename, "type": "PE32", "entry_sha256": entry_sha256(analysis)}},
    }


def is_unrunnable(analysis):
    return "bin_name_fails" in FAULTS and not analysis["filename"].endswith(".zip")


def entry_sha256(analysis):
    if "entry_sha_null" in FAULTS:
        return None
    if "entry_sha_is_the_decoys" in FAULTS:
        return DECOY_SHA
    if "entry_sha_is_the_zips" in FAULTS:
        return analysis["sha"]
    return ENTRY_SHA


def report_html(analysis):
    entry_sha = "not recorded" if "report_without_entry_sha" in FAULTS else entry_sha256(analysis)
    password = f"<p>password {PASSWORD}</p>" if "report_holds_password" in FAULTS else ""
    return (
        f"<html><body><h1>{analysis['filename']}</h1><dl><dt>archive</dt><dd>{analysis['filename']}</dd>"
        f"<dt>archive sha256</dt><dd>{analysis['sha']}</dd><dt>file run</dt><dd>{analysis['entry']}</dd>"
        f"<dt>file run sha256</dt><dd>{entry_sha}</dd></dl>{password}</body></html>"
    ).encode()


def search_total(query, analysis):
    ran = "payload.exe" in query or ("other.exe" in query and "decoy_ran" in FAULTS)
    if is_unrunnable(analysis):
        ran = False
    if "entry_did_not_run" in FAULTS and "payload.exe" in query:
        ran = False
    return {"total": 1 if ran else 0, "events": [{"id": "e1"}] if ran else [], "next_cursor": None}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload=None):
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        return self.rfile.read(int(self.headers.get("content-length") or 0))

    def archive_members(self):
        parts = parse_multipart(self.headers["content-type"], self.read_body())
        upload = parts["file"].get_payload(decode=True)
        if not upload.startswith(b"PK") and "not_a_zip_is_listed" not in FAULTS:
            return self.reply(422, refusal("file"))
        password = parts["password"].get_content() if "password" in parts else "infected"
        return self.reply(200, member_listing(password))

    def create(self):
        parts = parse_multipart(self.headers["content-type"], self.read_body())
        upload = parts["file"].get_payload(decode=True)
        options = json.loads(parts["options"].get_content())
        sha = hashlib.sha256(upload).hexdigest()
        if "wrong_password_stores_sample" in FAULTS:
            STORED.add(sha)
        if options.get("archive_password") != PASSWORD and "wrong_password_accepted" not in FAULTS:
            if "wrong_password_adds_a_row" in FAULTS:
                ANALYSES[len(ANALYSES) + 1] = {"id": len(ANALYSES) + 1, "entry": "", "filename": "x.zip", "sha": sha}
            return self.reply(422, refusal("options.archive_password"))
        if options["archive_entry"] not in MEMBERS and "missing_entry_accepted" not in FAULTS:
            return self.reply(422, refusal("options.archive_password" if "refusal_on_wrong_field" in FAULTS else "options.archive_entry"))
        identifier = len(ANALYSES) + 1
        analysis = {"id": identifier, "entry": options["archive_entry"], "filename": parts["file"].get_filename(), "sha": sha}
        ANALYSES[identifier] = analysis
        STORED.add(sha)
        return self.reply(201, analysis_read(analysis, leaks_password="password_in_create" in FAULTS))

    def job(self, analysis, download):
        if analysis is None:
            return self.reply(404, {"error": {"code": "not_found"}})
        if not download:
            return self.reply(200, {"id": analysis["id"], "status": "done", "step": "rendered", "progress": 100, "result": None, "log": ""})
        data = report_html(analysis)
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-disposition", f'attachment; filename="tartarus-report-{analysis["id"]}.html"')
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_method(self, method):
        CALLS.append(f"{method} {self.path}")
        if self.path == "/calls":
            return self.reply(200, CALLS)
        stored = re.fullmatch(r"/stored/([0-9a-f]{64})", self.path)
        if stored:
            return self.reply(200 if stored.group(1) in STORED else 404, {})
        if method == "POST" and self.path == "/api/analyses/archive-members":
            return self.archive_members()
        if method == "POST" and self.path == "/api/analyses":
            return self.create()
        if method == "GET" and self.path.startswith("/api/analyses?"):
            return self.reply(200, {"items": [analysis_read(a, leaks_password="password_in_list" in FAULTS) for a in ANALYSES.values()], "total": len(ANALYSES)})
        if method == "POST" and re.fullmatch(r"/api/analyses/\d+/export/report", self.path):
            self.read_body()
            return self.reply(202, {"id": int(self.path.split("/")[3])})
        job = re.fullmatch(r"/api/jobs/(\d+)(/download)?", self.path)
        if job and method == "GET":
            return self.job(ANALYSES.get(int(job.group(1))), bool(job.group(2)))
        found = re.fullmatch(r"/api/analyses/(\d+)(/events/search)?", self.path)
        analysis = ANALYSES.get(int(found.group(1))) if found else None
        if analysis is None:
            return self.reply(404, {"error": {"code": "not_found"}})
        if found.group(2) and method == "POST":
            return self.reply(200, search_total(json.loads(self.read_body())["query"], analysis))
        if method == "GET":
            return self.reply(200, analysis_read(analysis, leaks_password="password_in_get" in FAULTS))
        return self.reply(404, {"error": {"code": "not_found"}})

    def do_GET(self):
        self.handle_method("GET")

    def do_POST(self):
        self.handle_method("POST")

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
