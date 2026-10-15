"""Tests of `bin/finish_logic.py`: ending a run by asking a guest's agent for the folder CAPE's
analyzer watches for. The guest is a fake agent on a loopback port that records what it is asked.
"""

import importlib
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest
from test_control_http import BIN  # noqa: F401 - importing it puts bin/ on sys.path

finish_logic = importlib.import_module("finish_logic")

# CAPE's analyzer looks for md5("cape-<task id>").
MD5_OF_TASK_7 = "e1b195e357506023df3e0309f42a438e"
MD5_OF_TASK_144 = "f6dc66cb0ffda3e53542c6bdceb57c46"
LINUX_FINISH_DIR = "/srv/finish"

AGENT_ANSWERS = {
    "ok": (200, {"message": "Successfully created directory", "status_code": 200}),
    "refuse": (
        500,
        {"message": "Error creating directory", "error_code": 500, "traceback": "secret traceback"},
    ),
    "bad_request": (400, {"message": "No dirpath has been provided", "error_code": 400}),
    "garbage": (200, None),
}


class FakeAgent:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.asked: list[dict] = []
        self.port = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@contextmanager
def fake_agent(mode: str = "ok") -> Iterator[FakeAgent]:
    agent = FakeAgent(mode)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode())
            agent.asked.append({"path": self.path, "form": form})
            if agent.mode == "hang":
                time.sleep(5)
            status, body = AGENT_ANSWERS.get(agent.mode, AGENT_ANSWERS["ok"])
            payload = b"<html>not json</html>" if body is None else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    agent.port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield agent
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def unused_url() -> str:
    with fake_agent() as agent:
        return agent.url


def test_the_folder_is_the_md5_of_cape_dash_the_task_id():
    assert finish_logic.completion_folder(7) == MD5_OF_TASK_7
    assert finish_logic.completion_folder(144) == MD5_OF_TASK_144


@pytest.mark.parametrize(
    ("finish_dir", "expected_prefix"),
    [
        ("C:\\Windows\\Temp", "C:\\Windows\\Temp\\"),
        ("C:\\Windows\\Temp\\", "C:\\Windows\\Temp\\"),
        (LINUX_FINISH_DIR, "/srv/finish/"),
        ("/srv/finish/", "/srv/finish/"),
    ],
)
def test_the_folder_is_joined_with_the_separator_the_finish_dir_uses(finish_dir, expected_prefix):
    assert finish_logic.folder_path(finish_dir, 7) == expected_prefix + MD5_OF_TASK_7


def test_a_finish_dir_with_both_separators_is_joined_with_a_backslash():
    assert finish_logic.folder_path("C:\\Users/x\\Temp", 7).endswith("\\" + MD5_OF_TASK_7)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7", 7), ("007", 7), ("9" * 18, int("9" * 18))],
)
def test_a_task_id_is_digits(raw, expected):
    assert finish_logic.parse_task_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "7a", "-1", "%2e%2e", "7 ", "9" * 19, "\u0663"])
def test_a_task_id_that_is_not_digits_is_refused(raw):
    assert finish_logic.parse_task_id(raw) is None


def test_the_agent_is_asked_to_make_the_folder_in_the_finish_dir():
    with fake_agent() as agent:
        finish_logic.finish_task(7, agent.url, "C:\\Windows\\Temp", 5)

    assert agent.asked == [
        {"path": "/mkdir", "form": {"dirpath": ["C:\\Windows\\Temp\\" + MD5_OF_TASK_7]}}
    ]


def test_a_created_folder_is_200_finished():
    with fake_agent() as agent:
        assert finish_logic.finish_task(7, agent.url, LINUX_FINISH_DIR, 5) == (
            200,
            {"finished": True},
        )


def test_finishing_again_asks_the_agent_again():
    with fake_agent() as agent:
        finish_logic.finish_task(7, agent.url, LINUX_FINISH_DIR, 5)
        finish_logic.finish_task(7, agent.url, LINUX_FINISH_DIR, 5)

    assert len(agent.asked) == 2


def test_an_unreachable_agent_is_a_502_naming_the_failure():
    status, body = finish_logic.finish_task(7, unused_url(), LINUX_FINISH_DIR, 5)

    assert status == 502
    assert "unreachable" in body["error"]


def test_an_agent_that_refuses_is_a_502_without_its_traceback():
    with fake_agent("refuse") as agent:
        status, body = finish_logic.finish_task(7, agent.url, LINUX_FINISH_DIR, 5)

    assert status == 502
    assert "Error creating directory" in body["error"]
    assert "traceback" not in json.dumps(body)


@pytest.mark.parametrize("mode", ["bad_request", "garbage"])
def test_an_agent_that_answers_400_or_something_unreadable_is_a_502(mode):
    with fake_agent(mode) as agent:
        assert finish_logic.finish_task(7, agent.url, LINUX_FINISH_DIR, 5)[0] == 502


def test_an_agent_that_hangs_is_given_up_on_after_the_timeout():
    started = time.monotonic()
    with fake_agent("hang") as agent:
        status, _ = finish_logic.finish_task(7, agent.url, LINUX_FINISH_DIR, 0.5)

    assert status == 502
    assert time.monotonic() - started < 4


def test_a_response_for_a_task_id_that_is_not_digits_is_400_and_looks_nothing_up():
    looked_up = []

    def destination():
        looked_up.append(True)
        return "http://127.0.0.1:1", LINUX_FINISH_DIR

    status, body = finish_logic.finish_response("7a", destination, 5)

    assert status == 400
    assert "error" in body
    assert looked_up == []


def test_a_response_for_a_valid_task_id_finishes_it():
    with fake_agent() as agent:
        assert finish_logic.finish_response("7", lambda: (agent.url, LINUX_FINISH_DIR), 5) == (
            200,
            {"finished": True},
        )
