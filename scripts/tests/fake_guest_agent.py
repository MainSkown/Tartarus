#!/usr/bin/env python3
"""A stand-in for CAPE's guest agent, for the tests of the Windows build steps.

Usage: fake_guest_agent.py <port> <guest root dir> <request log> <behaviour file>

It speaks the four calls the steps use (GET /, POST /store, /retrieve, /execute) against a
directory standing in for the guest's disk: `C:\\ProgramData\\x\\f` is `<root>/ProgramData/x/f`.
It cannot run PowerShell; what a script "prints" is scripted in the behaviour file, which is read
again on every request so a test can change it while the agent runs:

    {"answers": true,
     "appears_after_polls": {"path": "C:\\\\ProgramData\\\\x\\\\done", "polls": 3},
     "silent_after_execute": false,
     "scripts": {"tamper-off.ps1": {"stdout": "RESULT a=b\\r\\nEXITCODE 10\\r\\n"}}}

An /execute names a driver script it was told to run; the driver was uploaded with /store and
mentions the script it runs, so the entry of `scripts` whose key the driver mentions answers.
The agent's real reply carries no exit code, and neither does this one.
"""

import json
import re
import sys
import threading
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


def guest_path(root: Path, windows_path: str) -> Path:
    relative = re.sub(r"^[A-Za-z]:", "", windows_path).replace("\\", "/").strip("/")
    return root / relative


def parse_form(content_type: str, body: bytes) -> tuple[dict[str, str], dict[str, bytes]]:
    if content_type.startswith("multipart/form-data"):
        message = message_from_bytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
        fields: dict[str, str] = {}
        files: dict[str, bytes] = {}
        for part in message.get_payload():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True)
            if part.get_filename() is not None:
                files[name] = payload
            else:
                fields[name] = payload.decode()
        return fields, files
    return {key: values[0] for key, values in parse_qs(body.decode()).items()}, {}


class Agent(BaseHTTPRequestHandler):
    root: Path
    log_path: Path
    behaviour_path: Path
    polls = 0
    executed = False
    lock = threading.Lock()

    def behaviour(self) -> dict:
        return json.loads(self.behaviour_path.read_text()) if self.behaviour_path.exists() else {}

    def record(self, **entry: object) -> None:
        with self.lock, self.log_path.open("a") as log:
            log.write(json.dumps({"method": self.command, "path": self.path, **entry}) + "\n")

    def reply(self, status: int, body: dict | bytes) -> None:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        behaviour = self.behaviour()
        with self.lock:
            type(self).polls += 1
        self.record()
        appears = behaviour.get("appears_after_polls")
        if appears and self.polls >= appears["polls"]:
            target = guest_path(self.root, appears["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("done")
        silent = behaviour.get("silent_after_execute") and self.executed
        if behaviour.get("answers", True) and not silent:
            self.reply(200, {"message": "Agent", "status_code": 200})
        else:
            self.reply(503, {"message": "not ready", "error_code": 503})

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        form, files = parse_form(self.headers.get("Content-Type", ""), body)
        self.record(
            form=form,
            uploaded={name: len(data) for name, data in files.items()},
            **self.extras(form),
        )
        handler = {"/store": self.store, "/retrieve": self.retrieve, "/execute": self.execute}
        if self.path not in handler:
            self.reply(404, {"message": "no such call", "error_code": 404})
            return
        handler[self.path](form, files)

    def store(self, form: dict[str, str], files: dict[str, bytes]) -> None:
        if "filepath" not in form or "file" not in files:
            self.reply(400, {"message": "No file has been provided", "error_code": 400})
            return
        target = guest_path(self.root, form["filepath"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files["file"])
        self.reply(200, {"message": "Successfully stored file", "status_code": 200})

    def retrieve(self, form: dict[str, str], _files: dict[str, bytes]) -> None:
        target = guest_path(self.root, form.get("filepath", ""))
        if target.is_file():
            self.reply(200, target.read_bytes())
        else:
            self.reply(404, {"message": "File not found", "error_code": 404})

    def execute(self, form: dict[str, str], _files: dict[str, bytes]) -> None:
        type(self).executed = True
        driver = self.driver_text(form.get("command", ""))
        scripts = self.behaviour().get("scripts", {})
        answer = next(
            (entry for name, entry in scripts.items() if name in driver),
            {"stdout": "EXITCODE 0\r\n"},
        )
        self.reply(
            200,
            {
                "message": "Successfully executed command",
                "status_code": 200,
                "stdout": answer.get("stdout", ""),
                "stderr": answer.get("stderr", ""),
            },
        )

    def extras(self, form: dict[str, str]) -> dict[str, object]:
        if self.path != "/execute":
            return {}
        command = form.get("command", "")
        return {
            "command": command,
            "driver": self.driver_text(command),
            "asynchronous": "async" in form,
        }

    def driver_text(self, command: str) -> str:
        match = re.search(r"-File (\S+)", command)
        if not match:
            return ""
        driver = guest_path(self.root, match.group(1))
        return driver.read_text() if driver.is_file() else ""

    def log_message(self, *_args: object) -> None:
        return


def serve(port: int, root: Path, log_path: Path, behaviour_path: Path) -> ThreadingHTTPServer:
    handler = type(
        "BoundAgent",
        (Agent,),
        {"root": root, "log_path": log_path, "behaviour_path": behaviour_path},
    )
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


if __name__ == "__main__":
    port, root, log_path, behaviour_path = sys.argv[1:5]
    serve(int(port), Path(root), Path(log_path), Path(behaviour_path)).serve_forever()
