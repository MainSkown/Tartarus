"""The scan, and the fixture, that fail a test leaving a process of its own folder running."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fixtures.leaks import has_child_processes, kill, processes_running_under

from guest_engine.steps import terminate_group

TESTS = Path(__file__).parent
CAPE = TESTS.parent


@pytest.fixture
def stray(tmp_path):
    script = tmp_path / "stray"
    script.write_text("#!/bin/sh\nwhile :; do sleep 0.05; done\n")
    script.chmod(0o755)
    process = subprocess.Popen([str(script)], start_new_session=True)  # noqa: S603
    yield script, process
    terminate_group(process.pid, grace_s=2)
    process.wait(5)


def test_a_process_running_a_file_of_the_folder_is_reported_with_its_command_line(tmp_path, stray):
    script, process = stray

    leaked = processes_running_under(tmp_path)

    assert list(leaked) == [process.pid]
    assert str(script) in leaked[process.pid]


def test_nothing_is_reported_once_the_process_is_gone(tmp_path, stray):
    _, process = stray

    kill([process.pid])
    process.wait(5)

    assert processes_running_under(tmp_path) == {}


def test_a_process_of_another_folder_is_not_reported(tmp_path, stray):
    assert processes_running_under(tmp_path / "elsewhere") == {}


LEAKING_TEST = textwrap.dedent(
    """
    import subprocess

    def test_that_leaves_a_process_behind(tmp_path):
        script = tmp_path / "stray-step"
        script.write_text("#!/bin/sh\\nwhile :; do sleep 0.05; done\\n")
        script.chmod(0o755)
        subprocess.Popen([str(script)], start_new_session=True)

    def test_that_cleans_up_after_itself(tmp_path):
        pass
    """
)


def test_a_test_that_leaves_a_process_behind_errors_at_teardown_naming_it(tmp_path):
    (tmp_path / "test_leaky.py").write_text(LEAKING_TEST)
    (tmp_path / "conftest.py").write_text((TESTS / "conftest.py").read_text())
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(TESTS), str(CAPE)])}

    result = subprocess.run(  # noqa: S603 - this interpreter, running a test file written above
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp={tmp_path / 'base'}",
            str(tmp_path / "test_leaky.py"),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert "2 passed, 1 error" in result.stdout
    assert "the test left processes running" in result.stdout
    assert "stray-step" in result.stdout


def test_a_running_child_is_seen_and_a_finished_one_is_not(tmp_path):
    process = subprocess.Popen(["sleep", "300"])  # noqa: S607
    try:
        assert has_child_processes()
    finally:
        process.kill()
        process.wait(5)
    assert not has_child_processes()


def test_a_thread_that_exits_while_the_listing_is_read_is_not_an_error(tmp_path, monkeypatch):
    gone = tmp_path / "exited-thread" / "children"
    monkeypatch.setattr(Path, "glob", lambda *_: iter([gone]))

    assert not has_child_processes()
