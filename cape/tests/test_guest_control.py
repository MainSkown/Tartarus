"""Tests of `bin/guest-control`: HTTP in front of the `GuestEngine` protocol, against a fake engine.

The service runs for real on a loopback port; what is checked is the translation: the route to
the engine call, the engine's exceptions to status codes, and who may ask at all.
"""

import inspect
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest
from test_control_http import AUTH, BIN, TOKEN, Client, load_script, served
from test_guest_control_finish import MD5_OF_TASK_7, fake_agent

from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters
from guest_engine.protocol import GuestEngine

guest_control = load_script("guest-control")

CAPE_DIR = BIN.parent
PROTOCOL_METHODS = [
    name
    for name, member in inspect.getmembers(GuestEngine, inspect.isfunction)
    if not name.startswith("_")
]
WINDOWS_FINISH_DIR = "C:\\Windows\\Temp"
LINUX_FINISH_DIR = "/srv/finish"


class FakeEngine:
    """Answers from canned data and records every call as `(method, *arguments)`."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.failures: dict[str, Exception] = {}
        self.address = {"ip": "127.0.0.1", "agent_port": 0, "finish_dir": WINDOWS_FINISH_DIR}
        self.display_answer: dict | None = {"host": "127.0.0.1", "port": 5900}

    def _called(self, method: str, *arguments):
        self.calls.append((method, *arguments))
        if method in self.failures:
            raise self.failures[method]

    def profiles(self):
        self._called("profiles")
        return [{"id": "windows"}]

    def media(self):
        self._called("media")
        return [{"file": "win.iso"}]

    def guests(self):
        self._called("guests")
        return [{"name": "win"}]

    def guest(self, name):
        self._called("guest", name)
        return {"name": name}

    def guest_address(self, name):
        self._called("guest_address", name)
        return self.address

    def delete_guest(self, name):
        self._called("delete_guest", name)

    def start_build(self, params):
        self._called("start_build", params)
        return "build-1"

    def start_clone(self, source, params):
        self._called("start_clone", source, params)
        return "build-2"

    def build(self, build_id):
        self._called("build", build_id)
        return {"id": build_id, "status": "running"}

    def build_log(self, build_id, tail):
        self._called("build_log", build_id, tail)
        return ["line one", "line two"]

    def resume(self, build_id):
        self._called("resume", build_id)

    def restart(self, build_id):
        self._called("restart", build_id)

    def continue_after_pause(self, build_id):
        self._called("continue_after_pause", build_id)

    def complete_build(self, build_id, passed, selftest):
        self._called("complete_build", build_id, passed, selftest)

    def check(self, name):
        self._called("check", name)
        return {"name": name, "checks": []}

    def display(self, name):
        self._called("display", name)
        return self.display_answer

    def shutdown(self):
        self._called("shutdown")


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


def running(engine, **options):
    handler = guest_control.make_handler(engine, token=TOKEN, **options)
    return served(handler)


@pytest.fixture
def client(engine):
    with running(engine, agent_timeout=2) as started:
        yield started


def signature_of(function) -> list[str]:
    return list(inspect.signature(function).parameters)[1:]


def test_the_fake_engine_implements_every_method_of_the_protocol():
    for name in PROTOCOL_METHODS:
        assert signature_of(getattr(FakeEngine, name)) == signature_of(
            getattr(GuestEngine, name)
        ), name


def test_the_not_ready_engine_has_every_method_of_the_protocol():
    for name in PROTOCOL_METHODS:
        assert callable(getattr(guest_control.NotReadyEngine, name)), name


READ_ROUTES = [
    ("/profiles", [{"id": "windows"}], ("profiles",)),
    ("/media", [{"file": "win.iso"}], ("media",)),
    ("/guests", [{"name": "win"}], ("guests",)),
    ("/guests/win", {"name": "win"}, ("guest", "win")),
    ("/guests/win/display", {"host": "127.0.0.1", "port": 5900}, ("display", "win")),
    ("/builds/build-1", {"id": "build-1", "status": "running"}, ("build", "build-1")),
]


@pytest.mark.parametrize(("path", "expected", "call"), READ_ROUTES)
def test_a_get_route_answers_what_the_engine_returns(client, engine, path, expected, call):
    reply = client.request("GET", path, headers=AUTH)

    assert (reply.status, reply.json) == (200, expected)
    assert engine.calls == [call]


def test_delete_a_guest_is_204(client, engine):
    reply = client.request("DELETE", "/guests/win", headers=AUTH)

    assert (reply.status, reply.text) == (204, "")
    assert engine.calls == [("delete_guest", "win")]


def test_a_check_runs_the_guests_checks(client, engine):
    reply = client.request("POST", "/guests/win/check", headers=AUTH)

    assert (reply.status, reply.json) == (200, {"name": "win", "checks": []})
    assert engine.calls == [("check", "win")]


def test_a_build_starts_with_the_body_as_its_parameters_and_answers_202_with_the_id(client, engine):
    params = {"name": "win-two", "iso": "win.iso"}

    reply = client.request("POST", "/builds", params, AUTH)

    assert (reply.status, reply.json) == (202, {"id": "build-1"})
    assert engine.calls == [("start_build", params)]


def test_a_build_without_a_body_reaches_the_engine_as_no_parameters(client, engine):
    client.request("POST", "/builds", headers=AUTH)

    assert engine.calls == [("start_build", {})]


def test_a_clone_starts_from_the_named_guest_with_the_body_as_its_parameters(client, engine):
    reply = client.request("POST", "/guests/win/clone", {"name": "win-copy"}, AUTH)

    assert (reply.status, reply.json) == (202, {"id": "build-2"})
    assert engine.calls == [("start_clone", "win", {"name": "win-copy"})]


@pytest.mark.parametrize(
    ("action", "method"),
    [("resume", "resume"), ("restart", "restart"), ("continue", "continue_after_pause")],
)
def test_a_build_can_be_resumed_restarted_and_continued(client, engine, action, method):
    reply = client.request("POST", f"/builds/build-1/{action}", headers=AUTH)

    assert (reply.status, reply.json) == (202, {"id": "build-1"})
    assert engine.calls == [(method, "build-1")]


def test_the_backends_verdict_completes_a_build(client, engine):
    reply = client.request(
        "POST", "/builds/build-1/complete", {"passed": True, "selftest": {"a": 1}}, AUTH
    )

    assert (reply.status, reply.text) == (204, "")
    assert engine.calls == [("complete_build", "build-1", True, {"a": 1})]


def test_a_verdict_without_a_selftest_is_passed_on_with_an_empty_one(client, engine):
    client.request("POST", "/builds/build-1/complete", {"passed": False}, AUTH)

    assert engine.calls == [("complete_build", "build-1", False, {})]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "passed"),
        ({"passed": "yes"}, "passed"),
        ({"passed": 1}, "passed"),
        ({"passed": True, "selftest": []}, "selftest"),
    ],
)
def test_a_verdict_that_is_not_a_bool_and_an_object_is_422_naming_the_field(
    client, engine, body, field
):
    reply = client.request("POST", "/builds/build-1/complete", body, AUTH)

    assert reply.status == 422
    assert field in reply.json["fields"]
    assert engine.calls == []


def test_a_display_that_the_engine_does_not_have_is_404(client, engine):
    engine.display_answer = None

    reply = client.request("GET", "/guests/win/display", headers=AUTH)

    assert reply.status == 404
    assert "error" in reply.json


@pytest.mark.parametrize(
    ("query", "tail"), [("", 200), ("?tail=5", 5), ("?tail=2000", 2000), ("?tail=1", 1)]
)
def test_the_log_tail_defaults_to_200_and_may_be_up_to_2000(client, engine, query, tail):
    reply = client.request("GET", f"/builds/build-1/log{query}", headers=AUTH)

    assert (reply.status, reply.json) == (200, ["line one", "line two"])
    assert engine.calls == [("build_log", "build-1", tail)]


@pytest.mark.parametrize(
    "query", ["?tail=0", "?tail=-1", "?tail=2001", "?tail=abc", "?tail=", "?tail=1.5"]
)
def test_a_log_tail_outside_1_to_2000_is_422_and_asks_the_engine_nothing(client, engine, query):
    reply = client.request("GET", f"/builds/build-1/log{query}", headers=AUTH)

    assert reply.status == 422
    assert "tail" in reply.json["fields"]
    assert engine.calls == []


@pytest.mark.parametrize(
    ("failure", "status", "body"),
    [
        (GuestNotFound("no guest called win"), 404, {"error": "no guest called win"}),
        (Conflict("an analysis is running"), 409, {"error": "an analysis is running"}),
        (
            InvalidParameters({"name": "taken", "ram_mb": "too small"}),
            422,
            {
                "error": "name: taken, ram_mb: too small",
                "fields": {"name": "taken", "ram_mb": "too small"},
            },
        ),
    ],
)
def test_the_engines_exceptions_become_status_codes(client, engine, failure, status, body):
    engine.failures["guest"] = failure

    reply = client.request("GET", "/guests/win", headers=AUTH)

    assert (reply.status, reply.json) == (status, body)


@pytest.mark.parametrize(
    ("method", "path", "failing_call"),
    [
        ("GET", "/profiles", "profiles"),
        ("GET", "/media", "media"),
        ("GET", "/guests", "guests"),
        ("DELETE", "/guests/win", "delete_guest"),
        ("POST", "/guests/win/check", "check"),
        ("POST", "/guests/win/clone", "start_clone"),
        ("POST", "/builds", "start_build"),
        ("GET", "/builds/b1", "build"),
        ("GET", "/builds/b1/log", "build_log"),
        ("POST", "/builds/b1/resume", "resume"),
        ("POST", "/builds/b1/restart", "restart"),
        ("POST", "/builds/b1/continue", "continue_after_pause"),
        ("POST", "/builds/b1/complete", "complete_build"),
        ("GET", "/guests/win/display", "display"),
    ],
)
def test_every_route_maps_an_engine_conflict_to_409(client, engine, method, path, failing_call):
    engine.failures[failing_call] = Conflict("busy")
    body = {"passed": True} if path.endswith("complete") else None

    reply = client.request(method, path, body, AUTH)

    assert (reply.status, reply.json) == (409, {"error": "busy"})


def test_any_other_engine_exception_is_a_generic_500_with_the_detail_in_the_log(
    client, engine, capsys
):
    engine.failures["guests"] = RuntimeError("libvirt said: /var/lib/libvirt/images/secret.qcow2")

    reply = client.request("GET", "/guests", headers=AUTH)

    assert (reply.status, reply.json) == (500, {"error": "internal error"})
    assert "secret.qcow2" not in reply.text
    assert "secret.qcow2" in capsys.readouterr().out


ALL_ROUTES = [
    ("GET", "/profiles"),
    ("GET", "/media"),
    ("GET", "/guests"),
    ("GET", "/guests/win"),
    ("DELETE", "/guests/win"),
    ("POST", "/guests/win/check"),
    ("POST", "/guests/win/clone"),
    ("GET", "/guests/win/display"),
    ("POST", "/builds"),
    ("GET", "/builds/b1"),
    ("GET", "/builds/b1/log"),
    ("POST", "/builds/b1/resume"),
    ("POST", "/builds/b1/restart"),
    ("POST", "/builds/b1/continue"),
    ("POST", "/builds/b1/complete"),
    ("POST", "/tasks/7/finish"),
]


@pytest.mark.parametrize(("method", "path"), ALL_ROUTES)
@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": f"Token {TOKEN}"}]
)
def test_no_route_answers_without_the_token_and_the_engine_is_never_asked(
    client, engine, method, path, headers
):
    reply = client.request(method, path, {"passed": True, "guest": "win"}, headers)

    assert (reply.status, reply.json) == (401, {"error": "unauthorized"})
    assert engine.calls == []


def test_healthz_is_the_only_route_without_a_token_and_says_nothing_else(client, engine):
    reply = client.request("GET", "/healthz")

    assert (reply.status, reply.json) == (200, {"ok": True})
    assert engine.calls == []


def test_healthz_is_a_get_only(client):
    assert client.request("POST", "/healthz").status == 401
    assert client.request("POST", "/healthz", headers=AUTH).status == 405


def test_an_unknown_route_is_404_and_a_wrong_method_is_405(client):
    assert client.request("GET", "/", headers=AUTH).status == 404
    assert client.request("GET", "/guests/win/nothing", headers=AUTH).status == 404
    assert client.request("GET", "/builds/b1/log/more", headers=AUTH).status == 404
    assert client.request("PUT", "/guests", headers=AUTH).status == 405
    assert client.request("POST", "/profiles", headers=AUTH).status == 405
    assert client.request("GET", "/builds/b1/resume", headers=AUTH).status == 405


def test_a_body_over_64_kib_is_413_and_the_engine_is_not_asked(client, engine):
    reply = client.request("POST", "/builds", raw=b" " * (64 * 1024 + 1), headers=AUTH)

    assert reply.status == 413
    assert engine.calls == []


def test_a_body_that_is_not_json_is_400_and_the_engine_is_not_asked(client, engine):
    reply = client.request("POST", "/builds", raw=b"{not json", headers=AUTH)

    assert reply.status == 400
    assert engine.calls == []


VALID_GUEST_NAMES = ["ab", "win", "win-2", "a" + "b" * 31]
INVALID_GUEST_NAMES = [
    "a",
    "A",
    "Win",
    "1win",
    "-win",
    "win_2",
    "a" + "b" * 32,
    "win.iso",
    "%2e%2e",
    "w%2fin",
    "win%20",
    "w%C3%AEn",
]


@pytest.mark.parametrize("name", INVALID_GUEST_NAMES)
def test_a_guest_name_that_is_not_a_slug_is_400_before_it_reaches_the_engine(client, engine, name):
    for method, suffix in [
        ("GET", ""),
        ("DELETE", ""),
        ("POST", "/check"),
        ("POST", "/clone"),
        ("GET", "/display"),
    ]:
        reply = client.request(method, f"/guests/{name}{suffix}", headers=AUTH)
        assert reply.status == 400, (method, suffix)
    assert engine.calls == []


@pytest.mark.parametrize("name", VALID_GUEST_NAMES)
def test_a_guest_name_that_is_a_slug_reaches_the_engine(client, engine, name):
    assert client.request("GET", f"/guests/{name}", headers=AUTH).status == 200
    assert engine.calls == [("guest", name)]


INVALID_BUILD_IDS = ["a%20b", "a" * 65, "a.b", "%2e%2e", "a%2fb", "id%C3%A9"]


@pytest.mark.parametrize("build_id", INVALID_BUILD_IDS)
def test_a_build_id_outside_its_pattern_is_400_before_it_reaches_the_engine(
    client, engine, build_id
):
    for method, suffix in [
        ("GET", ""),
        ("GET", "/log"),
        ("POST", "/resume"),
        ("POST", "/restart"),
        ("POST", "/continue"),
    ]:
        assert client.request(method, f"/builds/{build_id}{suffix}", headers=AUTH).status == 400, (
            method,
            suffix,
        )
    assert engine.calls == []


@pytest.mark.parametrize("build_id", ["B", "a_b-C9", "a" * 64])
def test_a_build_id_inside_its_pattern_reaches_the_engine(client, engine, build_id):
    assert client.request("GET", f"/builds/{build_id}", headers=AUTH).status == 200
    assert engine.calls == [("build", build_id)]


# NotReadyEngine: the stand-in until guest_engine.engine is installed in the image.


@pytest.fixture
def not_ready_client():
    with running(guest_control.NotReadyEngine(), agent_timeout=2) as started:
        yield started


@pytest.mark.parametrize(
    ("method", "path"), [route for route in ALL_ROUTES if route[1] != "/tasks/7/finish"]
)
def test_every_engine_route_is_409_while_the_engine_is_not_installed(
    not_ready_client, method, path
):
    reply = not_ready_client.request(method, path, {"passed": True}, AUTH)

    assert (reply.status, reply.json) == (
        409,
        {"error": "the guest engine is not installed in this image yet"},
    )


def test_the_finish_route_is_409_while_the_engine_is_not_installed(not_ready_client):
    reply = not_ready_client.request("POST", "/tasks/7/finish", {"guest": "win"}, AUTH)

    assert reply.status == 409


def test_not_ready_still_enforces_the_token_and_serves_healthz(not_ready_client):
    assert not_ready_client.request("GET", "/guests").status == 401
    assert not_ready_client.request("GET", "/healthz").json == {"ok": True}


def test_every_protocol_method_of_the_not_ready_engine_refuses_but_stopping_it():
    engine = guest_control.NotReadyEngine()
    for name in PROTOCOL_METHODS:
        if name == "shutdown":
            continue
        arguments = [None] * len(signature_of(getattr(GuestEngine, name)))
        with pytest.raises(Conflict):
            getattr(engine, name)(*arguments)


# Finishing a run on the guest the request names.


@pytest.mark.parametrize(
    ("finish_dir", "expected_dirpath"),
    [
        (WINDOWS_FINISH_DIR, f"{WINDOWS_FINISH_DIR}\\{MD5_OF_TASK_7}"),
        (LINUX_FINISH_DIR, f"{LINUX_FINISH_DIR}/{MD5_OF_TASK_7}"),
    ],
)
def test_finish_asks_the_named_guests_agent_for_the_folder(
    client, engine, finish_dir, expected_dirpath
):
    with fake_agent() as agent:
        engine.address = {"ip": "127.0.0.1", "agent_port": agent.port, "finish_dir": finish_dir}

        reply = client.request("POST", "/tasks/7/finish", {"guest": "win"}, AUTH)

    assert (reply.status, reply.json) == (200, {"finished": True})
    assert engine.calls == [("guest_address", "win")]
    assert agent.asked == [{"path": "/mkdir", "form": {"dirpath": [expected_dirpath]}}]


def test_finish_for_an_unknown_guest_is_404_and_no_agent_is_asked(client, engine):
    engine.failures["guest_address"] = GuestNotFound("no guest called ghost")
    with fake_agent() as agent:
        engine.address = {
            "ip": "127.0.0.1",
            "agent_port": agent.port,
            "finish_dir": WINDOWS_FINISH_DIR,
        }

        reply = client.request("POST", "/tasks/7/finish", {"guest": "ghost"}, AUTH)

    assert (reply.status, reply.json) == (404, {"error": "no guest called ghost"})
    assert agent.asked == []


def test_finish_with_an_agent_that_cannot_be_reached_is_502(client, engine):
    with fake_agent() as agent:
        unused_port = agent.port
    engine.address = {
        "ip": "127.0.0.1",
        "agent_port": unused_port,
        "finish_dir": WINDOWS_FINISH_DIR,
    }

    reply = client.request("POST", "/tasks/7/finish", {"guest": "win"}, AUTH)

    assert reply.status == 502
    assert "unreachable" in reply.json["error"]


@pytest.mark.parametrize("mode", ["refuse", "bad_request", "garbage"])
def test_finish_with_an_agent_that_misbehaves_is_502(client, engine, mode):
    with fake_agent(mode) as agent:
        engine.address = {
            "ip": "127.0.0.1",
            "agent_port": agent.port,
            "finish_dir": WINDOWS_FINISH_DIR,
        }

        reply = client.request("POST", "/tasks/7/finish", {"guest": "win"}, AUTH)

    assert reply.status == 502
    assert "traceback" not in reply.text


@pytest.mark.parametrize(
    "body", [{}, {"guest": 7}, {"guest": "Win"}, {"guest": "../x"}, {"guest": ""}]
)
def test_finish_without_a_valid_guest_name_is_422_and_the_engine_is_not_asked(client, engine, body):
    reply = client.request("POST", "/tasks/7/finish", body, AUTH)

    assert reply.status == 422
    assert "guest" in reply.json["fields"]
    assert engine.calls == []


@pytest.mark.parametrize("task_id", ["abc", "7a", "-1", "%2e%2e", "9" * 19, ""])
def test_finish_with_a_task_id_that_is_not_digits_is_400_and_asks_nothing(client, engine, task_id):
    reply = client.request("POST", f"/tasks/{task_id}/finish", {"guest": "win"}, AUTH)

    assert reply.status == 400
    assert engine.calls == []


# Starting up.


def test_the_engine_is_the_one_the_image_ships_when_it_is_installed():
    class Installed:
        @staticmethod
        def create_engine():
            return "the real engine"

    assert guest_control.load_engine(lambda _name: Installed) == "the real engine"


@pytest.mark.parametrize("missing", ["guest_engine", "guest_engine.engine"])
def test_a_missing_engine_module_is_the_not_ready_engine(missing):
    def not_installed(name):
        raise ModuleNotFoundError(f"No module named {missing!r}", name=missing)

    assert isinstance(guest_control.load_engine(not_installed), guest_control.NotReadyEngine)


def test_an_engine_that_is_installed_but_broken_stops_the_service():
    def broken(name):
        raise ModuleNotFoundError("No module named 'libvirt'", name="libvirt")

    with pytest.raises(ModuleNotFoundError):
        guest_control.load_engine(broken)


GOOD_ENVIRONMENT = {"CAPE_CONTROL_IP": "10.9.8.7", "GUEST_CONTROL_TOKEN": TOKEN}


def test_the_settings_come_from_the_environment_with_the_default_port():
    settings = guest_control.settings_from(GOOD_ENVIRONMENT)

    assert (settings.address, settings.port, settings.token) == ("10.9.8.7", 8002, TOKEN)


def test_the_port_can_be_set():
    settings = guest_control.settings_from({**GOOD_ENVIRONMENT, "GUEST_CONTROL_PORT": "9100"})

    assert settings.port == 9100


@pytest.mark.parametrize(
    ("removed", "mentioned"),
    [("CAPE_CONTROL_IP", "CAPE_CONTROL_IP"), ("GUEST_CONTROL_TOKEN", "GUEST_CONTROL_TOKEN")],
)
def test_the_service_refuses_to_start_without_its_address_or_its_token(removed, mentioned):
    environment = {k: v for k, v in GOOD_ENVIRONMENT.items() if k != removed}

    with pytest.raises(SystemExit, match=mentioned):
        guest_control.settings_from(environment)


def test_the_service_refuses_a_token_that_is_too_short_to_be_a_secret():
    with pytest.raises(SystemExit, match="GUEST_CONTROL_TOKEN"):
        guest_control.settings_from({**GOOD_ENVIRONMENT, "GUEST_CONTROL_TOKEN": "short"})


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def launch_script_without_engine(tmp_path) -> tuple[subprocess.Popen, Client]:
    """The script as the image runs it, once it listens."""
    # The image lays the scripts, their modules and guest_engine/ side by side; the engine
    # module is left out, as it is until the engine is installed.
    shutil.copytree(
        CAPE_DIR / "guest_engine",
        tmp_path / "guest_engine",
        ignore=shutil.ignore_patterns("engine.py", "__pycache__"),
    )
    for name in ["guest-control", "control_http.py", "finish_logic.py"]:
        shutil.copy(BIN / name, tmp_path / name)
    port = free_port()
    environment = {
        **os.environ,
        **GOOD_ENVIRONMENT,
        "CAPE_CONTROL_IP": "127.0.0.1",
        "GUEST_CONTROL_PORT": str(port),
    }
    service = subprocess.Popen(  # noqa: S603 - runs this repository's own script
        [sys.executable, "-I", str(tmp_path / "guest-control")],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        return service, wait_until_listening(port, service)
    except BaseException:
        service.kill()
        raise


def test_the_script_runs_as_the_image_runs_it_and_answers_not_ready_without_an_engine(tmp_path):
    service, client = launch_script_without_engine(tmp_path)
    try:
        assert client.request("GET", "/healthz").json == {"ok": True}
        assert client.request("GET", "/guests").status == 401
        assert client.request("GET", "/guests", headers=AUTH).status == 409
    finally:
        service.terminate()
        output = service.communicate(timeout=10)[0]
    assert TOKEN not in output
    assert "not installed" in output


@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGINT])
def test_the_script_stops_cleanly_when_told_to(tmp_path, stop):
    service, _ = launch_script_without_engine(tmp_path)

    service.send_signal(stop)

    output = service.communicate(timeout=10)[0]
    assert service.returncode == 0
    assert "stopped" in output


class FakeServer:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def shutdown(self) -> None:
        self.calls.append(("server stopped",))


def test_stopping_the_service_stops_the_engines_step_before_the_server(engine):
    guest_control.stop_service(engine, FakeServer(engine.calls))

    assert engine.calls == [("shutdown",), ("server stopped",)]


@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGINT])
def test_a_stop_signal_stops_the_service_from_a_thread_of_its_own(engine, stop):
    # server.shutdown() waits for serve_forever() to return, and that loop is what the signal
    # interrupted, so the handler must not call it on the thread that runs the loop.
    stopped = threading.Event()
    server = FakeServer(engine.calls)
    server.shutdown = stopped.set
    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        guest_control.stop_when_told(engine, server)
        signal.raise_signal(stop)
        assert stopped.wait(5)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)

    assert engine.calls == [("shutdown",)]


def wait_until_listening(port: int, service: subprocess.Popen):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        assert service.poll() is None, "the service exited"
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return Client(port)
        except OSError:
            time.sleep(0.05)
    raise AssertionError("the service never listened")
