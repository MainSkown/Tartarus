"""A stand-in for the analyses API's lifecycle, used by test_e2e_cleanup.sh.

`python3 fake_analyses_api.py <port> <id>:<status>[:<polls>[:<sha>]] ...` serves those analyses. An
analysis that starts `running` or `queued` becomes `done` after <polls> reads of its status (0 or
absent: it never changes). Like the real API, cancel works on a queued analysis only and delete
answers 409 for an active one.
"""

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACTIVE = {"queued", "starting", "running", "processing", "ingesting"}
ANALYSES = {}
for spec in sys.argv[2:]:
    identifier, status, polls, sha = (spec.split(":") + ["0", ""])[:4]
    ANALYSES[int(identifier)] = {"id": int(identifier), "status": status, "polls_left": int(polls), "sample_sha256": sha or "0" * 64}
CALLS = []


def read_status(analysis):
    if analysis["status"] in ACTIVE and analysis["polls_left"] > 0:
        analysis["polls_left"] -= 1
        if analysis["polls_left"] == 0:
            analysis["status"] = "done"
    return {key: analysis[key] for key in ("id", "status", "sample_sha256")}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload=None):
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_method(self, method):
        CALLS.append(f"{method} {self.path}")
        if self.path == "/calls":
            return self.reply(200, CALLS)
        if method == "GET" and self.path.startswith("/api/analyses?"):
            return self.reply(200, {"items": [read_status(analysis) for analysis in ANALYSES.values()]})
        found = re.fullmatch(r"/api/analyses/(\d+)(/cancel)?", self.path)
        analysis = ANALYSES.get(int(found.group(1))) if found else None
        if analysis is None:
            return self.reply(404, {"error": {"code": "not_found"}})
        if found.group(2) and method == "POST":
            if analysis["status"] != "queued":
                return self.reply(409, {"error": {"code": "conflict"}})
            analysis["status"] = "cancelled"
            return self.reply(200, read_status(analysis))
        if method == "GET":
            return self.reply(200, read_status(analysis))
        if method == "DELETE":
            if analysis["status"] in ACTIVE:
                return self.reply(409, {"error": {"code": "conflict"}})
            del ANALYSES[analysis["id"]]
            return self.reply(204)
        return self.reply(404, {"error": {"code": "not_found"}})

    def do_GET(self):
        self.handle_method("GET")

    def do_POST(self):
        self.handle_method("POST")

    def do_DELETE(self):
        self.handle_method("DELETE")

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
