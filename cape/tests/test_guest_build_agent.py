"""The guest agent client of the Windows steps (guest/profiles/windows/steps/lib/guest_agent.py).

The guest is scripts/tests/fake_guest_agent.py, served from a thread on a loopback port.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
LIB_DIR = REPO / "guest" / "profiles" / "windows" / "steps" / "lib"
TESTS_DIR = REPO / "scripts" / "tests"
CLIENT = LIB_DIR / "guest_agent.py"
sys.path[:0] = [str(LIB_DIR), str(TESTS_DIR)]

import fake_guest_agent  # noqa: E402
import guest_agent  # noqa: E402

WORK_DIR = "C:\\ProgramData\\abcdefgh"
POWERSHELL = "C:/Windows/Sysnative/WindowsPowerShell/v1.0/powershell.exe"


class FakeGuest:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "disk"
        self.root.mkdir()
        self.requests_file = tmp_path / "requests.jsonl"
        self.behaviour_file = tmp_path / "behaviour.json"
        self.server = fake_guest_agent.serve(0, self.root, self.requests_file, self.behaviour_file)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def behave(self, **behaviour) -> None:
        self.behaviour_file.write_text(json.dumps(behaviour))

    def on_disk(self, name: str) -> Path:
        return self.root / "ProgramData" / "abcdefgh" / name

    def requests(self) -> list[dict]:
        if not self.requests_file.exists():
            return []
        return [json.loads(line) for line in self.requests_file.read_text().splitlines()]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def guest(tmp_path):
    fake = FakeGuest(tmp_path)
    yield fake
    fake.stop()


@pytest.fixture
def agent(guest):
    return guest_agent.GuestAgent(guest.url, WORK_DIR, timeout=5)


def put_system_file(guest, name: str, content: bytes) -> None:
    path = guest.root / "Windows" / "Sysnative" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestSystemFiles:
    def test_a_system_file_comes_back_byte_for_byte_from_the_64_bit_system_folder(
        self, agent, guest
    ):
        put_system_file(guest, "ntoskrnl.exe", b"MZ\x90\x00 kernel")

        assert agent.retrieve_system_file("ntoskrnl.exe") == b"MZ\x90\x00 kernel"

    def test_the_request_names_sysnative_because_the_agent_is_32_bit(self, agent, guest):
        put_system_file(guest, "ntoskrnl.exe", b"x")
        agent.retrieve_system_file("ntoskrnl.exe")

        (request,) = [r for r in guest.requests() if r["path"] == "/retrieve"]
        assert request["form"]["filepath"] == "C:\\Windows\\Sysnative\\ntoskrnl.exe"

    def test_a_missing_system_file_is_an_error_that_says_which(self, agent):
        with pytest.raises(guest_agent.AgentError, match=r"ntoskrnl\.exe.*404"):
            agent.retrieve_system_file("ntoskrnl.exe")

    @pytest.mark.parametrize("name", ["..\\x", "a/b", "C:\\x", "", "a b", "x" * 65])
    def test_a_name_that_is_not_a_plain_file_name_is_refused_without_asking_the_guest(
        self, agent, guest, name
    ):
        with pytest.raises(guest_agent.AgentError, match="plain file name"):
            agent.retrieve_system_file(name)

        assert guest.requests() == []


class TestReachingTheAgent:
    def test_it_answers_when_the_index_does(self, agent):
        assert agent.answers() is True

    def test_it_does_not_answer_when_the_agent_says_it_is_not_ready(self, agent, guest):
        guest.behave(answers=False)
        assert agent.answers() is False

    def test_it_does_not_answer_when_nothing_listens(self, guest):
        unreachable = guest_agent.GuestAgent("http://127.0.0.1:9", WORK_DIR, timeout=1)
        assert unreachable.answers() is False


class TestFilesInTheWorkFolder:
    def test_a_stored_file_lands_in_the_work_folder(self, agent, guest):
        agent.store("note.txt", b"line one\r\nline two\x00\xff")
        assert guest.on_disk("note.txt").read_bytes() == b"line one\r\nline two\x00\xff"

    def test_the_stored_path_uses_backslashes(self, agent, guest):
        agent.store("note.txt", b"x")
        (store,) = [r for r in guest.requests() if r["path"] == "/store"]
        assert store["form"]["filepath"] == f"{WORK_DIR}\\note.txt"

    def test_a_retrieved_file_comes_back_byte_for_byte(self, agent, guest):
        guest.on_disk("done").parent.mkdir(parents=True)
        guest.on_disk("done").write_bytes(b"\xff\xfe binary")
        assert agent.retrieve("done") == b"\xff\xfe binary"

    def test_retrieving_a_missing_file_is_an_error_that_says_which(self, agent):
        with pytest.raises(guest_agent.AgentError, match=r"setup\.log"):
            agent.retrieve("setup.log")

    def test_exists_tells_a_present_file_from_a_missing_one(self, agent, guest):
        guest.on_disk("done").parent.mkdir(parents=True)
        guest.on_disk("done").write_text("x")
        assert (agent.exists("done"), agent.exists("other")) == (True, False)

    def test_a_name_that_leaves_the_work_folder_is_refused(self, agent):
        for name in ("..\\x", "a/b", "C:\\x", ""):
            with pytest.raises(guest_agent.AgentError, match="plain file name"):
                agent.store(name, b"x")


class TestAWorkFolderThatTheAgentCannotRun:
    @pytest.mark.parametrize("bad", ["C:\\Program Files\\x", 'C:\\a"b', "relative", ""])
    def test_it_is_refused(self, bad):
        with pytest.raises(guest_agent.AgentError, match="work folder"):
            guest_agent.GuestAgent("http://127.0.0.1:1", bad)


class TestRunningAScript:
    @pytest.fixture
    def scripts(self, tmp_path):
        folder = tmp_path / "scripts"
        folder.mkdir()
        (folder / "tamper.ps1").write_text("tamper script")
        (folder / "settings.ps1").write_text("settings script")
        return folder

    def run(self, agent, scripts, **arguments):
        return agent.run_script(scripts, "tamper.ps1", with_files=["settings.ps1"], **arguments)

    def test_the_exit_code_and_results_come_from_the_output(self, agent, guest, scripts):
        guest.behave(
            scripts={
                "tamper.ps1": {
                    "stdout": "RESULT window=found\r\nnoise\r\nRESULT IsTamperProtected=False\r\n"
                    "EXITCODE 20\r\n"
                }
            }
        )
        result = self.run(agent, scripts)
        assert result.exit_code == 20
        assert result.results == [("window", "found"), ("IsTamperProtected", "False")]
        assert result.lines == [
            "RESULT window=found",
            "noise",
            "RESULT IsTamperProtected=False",
        ]

    def test_the_script_and_its_helper_are_uploaded_beside_each_other(self, agent, guest, scripts):
        self.run(agent, scripts)
        assert guest.on_disk("tamper.ps1").read_text() == "tamper script"
        assert guest.on_disk("settings.ps1").read_text() == "settings script"

    def test_the_driver_runs_in_the_64_bit_shell_with_slash_paths(self, agent, guest, scripts):
        self.run(agent, scripts)
        (execute,) = [r for r in guest.requests() if r["path"] == "/execute"]
        assert execute["command"] == (
            f"{POWERSHELL} -NoProfile -ExecutionPolicy Bypass -File C:/ProgramData/abcdefgh/run.ps1"
        )
        assert execute["asynchronous"] is False

    def test_the_driver_calls_the_script_with_its_arguments_and_cleans_up(
        self, agent, guest, scripts
    ):
        self.run(agent, scripts, arguments={"LogName": "it's.log"})
        (execute,) = [r for r in guest.requests() if r["path"] == "/execute"]
        driver = execute["driver"]
        assert "& 'C:/ProgramData/abcdefgh/tamper.ps1' -LogName 'it''s.log'" in driver
        for name in ("tamper.ps1", "settings.ps1", "run.ps1"):
            assert f"C:/ProgramData/abcdefgh/{name}" in driver.split("finally")[1]

    def test_an_output_without_an_exit_code_is_reported_as_none(self, agent, guest, scripts):
        guest.behave(scripts={"tamper.ps1": {"stdout": "RESULT a=b\r\n", "stderr": "boom"}})
        result = self.run(agent, scripts)
        assert result.exit_code is None
        assert result.stderr == "boom"

    def test_an_agent_that_refuses_the_command_is_an_error_with_its_message(
        self, agent, scripts, monkeypatch
    ):
        post = guest_agent.GuestAgent._post

        def refuse_execute(self, path, *rest, **named):
            if path == "/execute":
                return 500, b'{"message": "Not allowed"}'
            return post(self, path, *rest, **named)

        monkeypatch.setattr(guest_agent.GuestAgent, "_post", refuse_execute)
        with pytest.raises(
            guest_agent.AgentError, match=r"refused to run tamper\.ps1: Not allowed"
        ):
            self.run(agent, scripts)

    def test_a_local_script_that_does_not_exist_is_an_error(self, agent, scripts):
        with pytest.raises(guest_agent.AgentError, match=r"missing\.ps1"):
            agent.run_script(scripts, "missing.ps1")


class TestTheDriverText:
    def test_values_are_single_quoted_with_quotes_doubled(self):
        text = guest_agent.driver_text("C:/x/s.ps1", {"A": "it's $env:X `n"}, [])
        assert "-A 'it''s $env:X `n'" in text

    def test_a_value_with_a_line_break_is_refused(self):
        with pytest.raises(guest_agent.AgentError, match="line break"):
            guest_agent.driver_text("C:/x/s.ps1", {"A": "a\nb"}, [])

    def test_a_parameter_name_that_is_not_a_name_is_refused(self):
        with pytest.raises(guest_agent.AgentError, match="parameter name"):
            guest_agent.driver_text("C:/x/s.ps1", {"A b; calc": "x"}, [])

    def test_an_earlier_commands_exit_code_is_cleared_before_the_script_runs(self):
        text = guest_agent.driver_text("C:/x/s.ps1", {}, [])
        assert text.index("$global:LASTEXITCODE = $null") < text.index("& 'C:/x/s.ps1'")

    def test_a_script_that_throws_reports_exit_code_40(self):
        text = guest_agent.driver_text("C:/x/s.ps1", {}, [])
        assert "catch" in text
        assert "$code = 40" in text


class TestResultLines:
    def test_only_result_lines_with_a_key_are_results(self):
        stdout = "RESULT a=b\nRESULT c=d=e\nRESULT nokey\nresult x=y\n  RESULT z=1\n"
        assert guest_agent.parse_results(stdout.splitlines()) == [
            ("a", "b"),
            ("c", "d=e"),
            ("z", "1"),
        ]


class TestTheCommandLine:
    @pytest.fixture
    def environment(self, guest, tmp_path):
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        (profile_dir / "tamper.ps1").write_text("tamper script")
        context = tmp_path / "context.json"
        context.write_text(
            json.dumps(
                {
                    "guest": {"ip": "127.0.0.1", "work_dir": WORK_DIR},
                    "profile": {"agent": {"port": guest.port}},
                }
            )
        )
        return {
            "PATH": os.environ["PATH"],
            "TT_CONTEXT_JSON": str(context),
            "TT_PROFILE_DIR": str(profile_dir),
        }

    @staticmethod
    def call(environment, *arguments):
        return subprocess.run(  # noqa: S603
            [sys.executable, "-I", str(CLIENT), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_answers_exits_0_or_1(self, environment, guest):
        assert self.call(environment, "answers").returncode == 0
        guest.behave(answers=False)
        assert self.call(environment, "answers").returncode == 1

    def test_exists_exits_0_or_1(self, environment, guest):
        assert self.call(environment, "exists", "done").returncode == 1
        guest.on_disk("done").parent.mkdir(parents=True)
        guest.on_disk("done").write_text("x")
        assert self.call(environment, "exists", "done").returncode == 0

    def test_retrieve_writes_the_file(self, environment, guest, tmp_path):
        guest.on_disk("setup.log").parent.mkdir(parents=True)
        guest.on_disk("setup.log").write_bytes(b"one\r\ntwo\r\n")
        target = tmp_path / "out.log"
        assert self.call(environment, "retrieve", "setup.log", str(target)).returncode == 0
        assert target.read_bytes() == b"one\r\ntwo\r\n"

    def test_retrieve_system_writes_the_file_from_the_systems_folder(
        self, environment, guest, tmp_path
    ):
        put_system_file(guest, "ntoskrnl.exe", b"kernel bytes")
        target = tmp_path / "ntoskrnl.exe"

        result = self.call(environment, "retrieve-system", "ntoskrnl.exe", str(target))

        assert result.returncode == 0
        assert target.read_bytes() == b"kernel bytes"

    def test_retrieve_system_of_a_missing_file_exits_70_and_writes_nothing(
        self, environment, tmp_path
    ):
        target = tmp_path / "ntoskrnl.exe"

        result = self.call(environment, "retrieve-system", "ntoskrnl.exe", str(target))

        assert result.returncode == guest_agent.AGENT_FAILED
        assert "ntoskrnl.exe" in result.stderr
        assert not target.exists()

    def test_run_exits_with_the_scripts_code_and_logs_its_lines(self, environment, guest):
        guest.behave(scripts={"tamper.ps1": {"stdout": "RESULT a=b\r\nEXITCODE 10\r\n"}})
        result = self.call(environment, "run", "tamper.ps1")
        assert result.returncode == 10
        assert result.stdout.splitlines() == ["LOG RESULT a=b"]

    def test_run_without_an_exit_code_exits_71(self, environment, guest):
        guest.behave(scripts={"tamper.ps1": {"stdout": "RESULT a=b\r\n", "stderr": "boom"}})
        result = self.call(environment, "run", "tamper.ps1")
        assert result.returncode == guest_agent.NO_EXIT_CODE
        assert "boom" in result.stderr

    def test_run_passes_arguments_and_helper_files(self, environment, guest, tmp_path):
        (Path(environment["TT_PROFILE_DIR"]) / "helper.ps1").write_text("helper")
        self.call(environment, "run", "tamper.ps1", "--with", "helper.ps1", "--arg", "Mode=Off")
        assert guest.on_disk("helper.ps1").read_text() == "helper"
        (execute,) = [r for r in guest.requests() if r["path"] == "/execute"]
        assert "-Mode 'Off'" in execute["driver"]

    def test_run_takes_a_script_from_a_folder_of_the_profile_and_stores_it_by_its_plain_name(
        self, environment, guest
    ):
        folder = Path(environment["TT_PROFILE_DIR"]) / "selftest"
        folder.mkdir()
        (folder / "facts.ps1").write_text("facts script")
        (folder / "helper.ps1").write_text("helper")
        guest.behave(scripts={"facts.ps1": {"stdout": "FACT a=1\r\nEXITCODE 0\r\n"}})

        result = self.call(environment, "run", "selftest/facts.ps1", "--with", "helper.ps1")

        assert (result.returncode, result.stdout.splitlines()) == (0, ["LOG FACT a=1"])
        assert guest.on_disk("facts.ps1").read_text() == "facts script"
        assert guest.on_disk("helper.ps1").read_text() == "helper"

    @pytest.mark.parametrize("script", ["../outside.ps1", "/etc/passwd", "selftest/../../x.ps1"])
    def test_run_refuses_a_script_outside_the_profile_folder(self, environment, guest, script):
        result = self.call(environment, "run", script)

        assert result.returncode == guest_agent.AGENT_FAILED
        assert "profile" in result.stderr
        assert guest.requests() == []

    def test_an_unreachable_agent_exits_70_with_a_message(self, environment):
        environment_copy = dict(environment)
        context = json.loads(Path(environment["TT_CONTEXT_JSON"]).read_text())
        context["profile"]["agent"]["port"] = 9
        Path(environment["TT_CONTEXT_JSON"]).write_text(json.dumps(context))
        result = self.call(environment_copy, "run", "tamper.ps1")
        assert result.returncode == guest_agent.AGENT_FAILED
        assert "agent" in result.stderr
