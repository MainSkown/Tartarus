"""What the clone's reconfigure step needs from the agent client beyond a build's use of it.

The copy boots on an address the guest record does not hold yet (a DHCP lease), and the call that
changes the address dies with the connection, so it is made asynchronously.
"""

import json
import os
import subprocess
import sys

import pytest
from test_guest_build_agent import CLIENT, WORK_DIR, FakeGuest, guest_agent

UNREACHABLE_RECORDED_ADDRESS = "127.0.0.2"  # loopback, but the fake agent binds only 127.0.0.1


@pytest.fixture
def guest(tmp_path):
    fake = FakeGuest(tmp_path)
    yield fake
    fake.stop()


@pytest.fixture
def scripts(tmp_path):
    folder = tmp_path / "scripts"
    folder.mkdir()
    (folder / "apply.ps1").write_text("apply script")
    return folder


class TestAnAsynchronousScript:
    def test_the_execute_call_carries_the_async_flag(self, guest, scripts):
        agent = guest_agent.GuestAgent(guest.url, WORK_DIR, timeout=5)

        agent.start_script(scripts, "apply.ps1")

        (execute,) = [r for r in guest.requests() if r["path"] == "/execute"]
        assert execute["asynchronous"] is True
        assert execute["form"]["async"] == "1"

    def test_a_synchronous_script_is_not_flagged(self, guest, scripts):
        agent = guest_agent.GuestAgent(guest.url, WORK_DIR, timeout=5)

        agent.run_script(scripts, "apply.ps1")

        (execute,) = [r for r in guest.requests() if r["path"] == "/execute"]
        assert execute["asynchronous"] is False

    def test_it_is_uploaded_and_run_like_any_script(self, guest, scripts):
        agent = guest_agent.GuestAgent(guest.url, WORK_DIR, timeout=5)

        agent.start_script(scripts, "apply.ps1", arguments={"Mode": "Go"})

        assert guest.on_disk("apply.ps1").read_text() == "apply script"
        (execute,) = [r for r in guest.requests() if r["path"] == "/execute"]
        assert "-Mode 'Go'" in execute["driver"]
        assert execute["command"].startswith("C:/Windows/Sysnative/")

    def test_an_agent_that_cannot_be_reached_is_an_error(self, scripts):
        agent = guest_agent.GuestAgent("http://127.0.0.1:9", WORK_DIR, timeout=1)

        with pytest.raises(guest_agent.AgentError):
            agent.start_script(scripts, "apply.ps1")


class TestTheCommandLine:
    @pytest.fixture
    def environment(self, guest, tmp_path, scripts):
        context = tmp_path / "context.json"
        context.write_text(
            json.dumps(
                {
                    "guest": {"ip": UNREACHABLE_RECORDED_ADDRESS, "work_dir": WORK_DIR},
                    "profile": {"agent": {"port": guest.port}},
                }
            )
        )
        return {
            "PATH": os.environ["PATH"],
            "TT_CONTEXT_JSON": str(context),
            "TT_PROFILE_DIR": str(scripts),
        }

    @staticmethod
    def call(environment, *arguments):
        return subprocess.run(  # noqa: S603
            [sys.executable, "-I", str(CLIENT), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_the_agent_is_asked_at_the_override_when_there_is_one(self, environment):
        environment["TT_AGENT_HOST"] = "127.0.0.1"

        assert self.call(environment, "answers").returncode == 0

    def test_without_an_override_the_recorded_address_is_used(self, environment):
        assert self.call(environment, "answers").returncode == 1

    def test_run_async_succeeds_without_an_exit_code_and_prints_nothing(self, environment, guest):
        environment["TT_AGENT_HOST"] = "127.0.0.1"

        result = self.call(environment, "run", "apply.ps1", "--async")

        assert (result.returncode, result.stdout) == (0, "")
        (execute,) = [r for r in guest.requests() if r["path"] == "/execute"]
        assert execute["asynchronous"] is True

    def test_run_async_still_reports_an_agent_that_cannot_be_reached(self, environment):
        result = self.call(environment, "run", "apply.ps1", "--async")

        assert result.returncode == guest_agent.AGENT_FAILED
