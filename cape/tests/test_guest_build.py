"""Tests of `bin/guest-build`, the command-line client of the control service.

The real `guest-control` routes run on a loopback port in front of a scripted engine; the client
runs as a subprocess, so what is checked is what a person at a terminal sees: the lines printed,
the exit code, and the requests that reached the engine.
"""

import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer

import pytest
from test_control_http import BIN, TOKEN, load_script

from guest_engine.errors import Conflict, InvalidParameters

guest_control = load_script("guest-control")
GUEST_BUILD = BIN / "guest-build"

WINDOWS_PROFILE = {
    "id": "windows",
    "options": [
        {"key": "defender", "type": "bool"},
        {"key": "decoys", "type": "bool"},
        {"key": "sysmon", "type": "bool"},
        {"key": "key", "type": "secret"},
        {"key": "keyboard", "type": "choice"},
    ],
}
STEP_NAMES = ("preflight", "install")
KEY = "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"
SELFTEST_NOTE = {"by": "guest-build CLI, no analysis was run"}


def view(status="running", step=0, percent=0, *, message="", pause=None):
    return {
        "id": "b1",
        "guest": "alpha",
        "kind": "build",
        "status": status,
        "step": step,
        "steps": [{"name": name, "status": "pending", "progress": 0} for name in STEP_NAMES],
        "percent": percent,
        "message": message,
        "pause": pause,
    }


@dataclass
class ScriptedEngine:
    """A control-service engine; a build shows each of `views` in turn, then the last for good."""

    views: list[dict] = field(default_factory=lambda: [view("succeeded", 1, 100)])
    log: list[str] = field(default_factory=list)
    refusal: Exception | None = None
    calls: list[tuple] = field(default_factory=list)
    polls: int = 0

    def profiles(self):
        return [WINDOWS_PROFILE]

    def start_build(self, params):
        self.calls.append(("start_build", params))
        if self.refusal:
            raise self.refusal
        return "b1"

    def build(self, build_id):
        self.calls.append(("build", build_id))
        shown = self.views[min(self.polls, len(self.views) - 1)]
        self.polls += 1
        return shown

    def build_log(self, build_id, tail):
        self.calls.append(("build_log", build_id, tail))
        return self.log[-tail:]

    def complete_build(self, build_id, passed, selftest):
        self.calls.append(("complete_build", build_id, passed, selftest))

    def requests(self, name):
        return [call for call in self.calls if call[0] == name]


@pytest.fixture
def control():
    engine = ScriptedEngine()
    handler = guest_control.make_handler(engine, token=TOKEN)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    engine.port = server.server_address[1]
    yield engine
    server.shutdown()
    server.server_close()
    thread.join()


BASE_ARGUMENTS = [
    "--profile", "windows", "--media", "win.iso", "--variant", "5", "--name", "alpha",
    "--poll-seconds", "0.01",
]  # fmt: skip


def run(engine, *arguments, environment=None, token=TOKEN):
    env = {
        "PATH": os.environ["PATH"],
        "CAPE_CONTROL_IP": "127.0.0.1",
        "GUEST_CONTROL_PORT": str(engine.port),
        "GUEST_CONTROL_TOKEN": token,
        **(environment or {}),
    }
    return subprocess.run(  # noqa: S603
        [sys.executable, "-I", str(GUEST_BUILD), *arguments],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def build(engine, *extra, **named):
    return run(engine, *BASE_ARGUMENTS, *extra, **named)


class TestTheRequestItSends:
    def test_the_required_arguments_make_the_smallest_request(self, control):
        build(control)
        assert control.requests("start_build") == [
            (
                "start_build",
                {
                    "name": "alpha",
                    "profile": "windows",
                    "media": {"file": "win.iso", "variant": "5"},
                },
            )
        ]

    def test_identity_and_resources_are_sent_when_given(self, control):
        build(
            control,
            "--username", "casey", "--computer-name", "DESKTOP-Q1", "--password", "Pa55word!",
            "--vcpus", "4", "--ram-mb", "8192", "--disk-gb", "100",
        )  # fmt: skip
        (_, params) = control.requests("start_build")[0]
        assert params["identity"] == {
            "account": "casey",
            "machine": "DESKTOP-Q1",
            "password": "Pa55word!",
        }
        assert params["resources"] == {"vcpus": 4, "ram_mb": 8192, "disk_gb": 100}

    def test_options_are_typed_by_the_profiles_option_schema(self, control):
        build(
            control,
            "--option", "defender=false", "--option", "decoys=TRUE",
            "--option", "keyboard=German", "--option", "key=AAAAA-BBBBB-CCCCC-DDDDD-EEEEE",
        )  # fmt: skip
        (_, params) = control.requests("start_build")[0]
        assert params["options"] == {
            "defender": False,
            "decoys": True,
            "keyboard": "German",
            "key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE",
        }

    def test_an_option_the_profile_does_not_have_is_passed_on_for_the_service_to_refuse(
        self, control
    ):
        control.refusal = InvalidParameters({"options.bogus": "is not an option of this profile"})
        result = build(control, "--option", "bogus=1")
        assert control.requests("start_build")[0][1]["options"] == {"bogus": "1"}
        assert result.returncode == 2
        assert "options.bogus: is not an option of this profile" in result.stderr

    def test_a_bool_option_that_is_not_true_or_false_is_refused_before_asking(self, control):
        result = build(control, "--option", "defender=maybe")
        assert result.returncode == 2
        assert "defender" in result.stderr
        assert control.requests("start_build") == []

    def test_an_option_without_a_value_is_refused(self, control):
        result = build(control, "--option", "defender")
        assert result.returncode == 2
        assert "key=value" in result.stderr

    def test_the_password_and_key_may_come_from_the_environment_instead_of_the_command_line(
        self, control
    ):
        build(
            control,
            environment={"GUEST_PASSWORD": "from-env-pass", "GUEST_PRODUCT_KEY": KEY},
        )
        (_, params) = control.requests("start_build")[0]
        assert params["identity"] == {"password": "from-env-pass"}
        assert params["options"] == {"key": KEY}

    def test_the_command_line_wins_over_the_environment(self, control):
        build(control, "--password", "flag-pass", environment={"GUEST_PASSWORD": "env-pass"})
        assert control.requests("start_build")[0][1]["identity"] == {"password": "flag-pass"}


class TestTheOutcome:
    def test_a_succeeded_build_exits_0_and_leaves_the_guest_in_testing(self, control):
        result = build(control)
        assert result.returncode == 0
        assert "testing" in result.stdout
        assert control.requests("complete_build") == []

    def test_accepting_without_a_selftest_sends_the_minimal_verdict(self, control):
        result = build(control, "--accept-without-selftest")
        assert result.returncode == 0
        assert control.requests("complete_build") == [("complete_build", "b1", True, SELFTEST_NOTE)]
        assert "no self-test" in result.stdout

    def test_a_failed_build_exits_1_with_the_services_message_and_no_verdict(self, control):
        control.views = [view("failed", 1, 40, message="step install failed (exit 3)")]
        result = build(control, "--accept-without-selftest")
        assert result.returncode == 1
        assert "step install failed (exit 3)" in result.stderr
        assert control.requests("complete_build") == []

    def test_a_paused_build_prints_the_instructions_and_exits_75(self, control):
        control.views = [
            view("paused", 1, 70, pause={"instructions": "Switch Tamper Protection off."})
        ]
        result = build(control)
        assert result.returncode == 75
        assert "Switch Tamper Protection off." in result.stdout
        assert "b1" in result.stdout
        assert "continue" in result.stdout.lower()

    def test_the_services_422_lists_each_field(self, control):
        control.refusal = InvalidParameters(
            {"media.variant": "must be one of 5, 6", "name": "is already used by another guest"}
        )
        result = build(control)
        assert result.returncode == 2
        assert "media.variant: must be one of 5, 6" in result.stderr
        assert "name: is already used by another guest" in result.stderr
        assert control.requests("build") == []

    def test_a_busy_service_exits_1_with_its_reason(self, control):
        control.refusal = Conflict("the build of beta is running; only one at a time")
        result = build(control)
        assert result.returncode == 1
        assert "the build of beta is running" in result.stderr


class TestWhatItShowsWhileWaiting:
    def test_each_step_and_percentage_is_printed_once_as_it_changes(self, control):
        control.views = [
            view("running", 0, 0),
            view("running", 0, 0),
            view("running", 1, 30),
            view("running", 1, 30),
            view("succeeded", 1, 100),
        ]
        out = build(control).stdout
        assert out.count("preflight") == 1
        assert re.search(r"\[\s*30%\]\s+install", out)
        assert out.count("30%") == 1

    def test_log_lines_are_printed_once_each_in_order_even_when_the_tail_overlaps(self, control):
        control.views = [view("running", 0, 0)] * 2 + [view("succeeded", 1, 100)]
        lines = [f"line {number}" for number in range(1, 6)]
        original = control.build_log
        shown_so_far = iter([2, 4, 5])

        def growing(build_id, tail):
            count = next(shown_so_far, 5)
            control.log = lines[:count]
            return original(build_id, tail)

        control.build_log = growing
        out = build(control).stdout
        printed = [line.strip() for line in out.splitlines() if line.strip().startswith("line ")]
        assert printed == lines

    def test_lines_the_service_masked_are_printed_as_masked(self, control):
        control.log = ["password is ***"]
        assert "password is ***" in build(control).stdout


class TestTheConnection:
    def test_a_wrong_token_exits_1_and_says_so_without_printing_it(self, control):
        wrong = "w" * 40
        result = build(control, token=wrong)
        assert result.returncode == 1
        assert "401" in result.stderr or "unauthorized" in result.stderr.lower()
        assert wrong not in result.stdout + result.stderr

    def test_nothing_listening_exits_1(self, control):
        control.port = 9
        result = build(control)
        assert result.returncode == 1
        assert "control service" in result.stderr

    def test_a_missing_token_is_reported_before_any_request(self, control):
        result = run(control, *BASE_ARGUMENTS, token="")
        assert result.returncode == 1
        assert "GUEST_CONTROL_TOKEN is not set" in result.stderr
        assert control.calls == []


class TestTheAddress:
    def test_without_cape_control_ip_the_control_network_alias_is_used(self):
        guest_build = load_script("guest-build")
        assert guest_build.control_address({}) == "cape-control"
        assert guest_build.control_address({"CAPE_CONTROL_IP": "10.0.0.2"}) == "10.0.0.2"

    def test_the_port_defaults_to_8002(self):
        guest_build = load_script("guest-build")
        assert guest_build.control_port({}) == 8002
        assert guest_build.control_port({"GUEST_CONTROL_PORT": "9000"}) == 9000


class TestNewLines:
    def test_the_part_of_the_tail_not_seen_before(self):
        guest_build = load_script("guest-build")
        assert guest_build.new_lines(["a", "b"], ["a", "b", "c"]) == ["c"]
        assert guest_build.new_lines(["a", "b"], ["b", "c", "d"]) == ["c", "d"]
        assert guest_build.new_lines([], ["a"]) == ["a"]
        assert guest_build.new_lines(["a"], ["a"]) == []

    def test_a_tail_that_left_no_overlap_is_printed_whole(self):
        guest_build = load_script("guest-build")
        assert guest_build.new_lines(["a", "b"], ["x", "y"]) == ["x", "y"]

    def test_repeated_lines_are_not_swallowed(self):
        guest_build = load_script("guest-build")
        assert guest_build.new_lines(["a", "a"], ["a", "a", "a"]) == ["a"]
