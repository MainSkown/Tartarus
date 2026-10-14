"""A stand-in for the jobs API, used by test_e2e_exports.sh.

`python3 fake_jobs_api.py <port> <mode>` serves job 1. Modes: `done` (pending, then running, then
done after a few reads), `failed` (failed with a log), `stuck` (running for ever), `early-done`
(done at the first read). The download answers 409 until the job is done, and 200 once it is;
`download-ignores-state` answers 200 whatever the job's state, as a broken API would.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, MODE = int(sys.argv[1]), sys.argv[2]
READS = {"count": 0}
DONE_AFTER_READS = 3


def status():
    if MODE == "failed":
        return "failed"
    if MODE == "stuck":
        return "running"
    if MODE == "early-done":
        return "done"
    return "done" if READS["count"] >= DONE_AFTER_READS else "pending" if READS["count"] == 0 else "running"


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, payload, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/jobs/1":
            current = status()
            READS["count"] += 1
            log = "weasyprint exploded\nsecond line" if current == "failed" else ""
            return self.reply(200, {"id": 1, "status": current, "step": "Saving the file", "progress": 50, "result": None, "log": log})
        if self.path == "/api/jobs/1/download":
            if MODE != "download-ignores-state" and status() != "done":
                return self.reply(409, {"error": {"code": "conflict"}})
            return self.reply(200, b"report", "text/html")
        return self.reply(404, {"error": {"code": "not_found"}})

    def log_message(self, *_):
        pass


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
