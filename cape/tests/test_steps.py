import os
import stat
import time
from pathlib import Path

import pytest

from guest_engine.steps import (
    MAX_LINE_LENGTH,
    PAUSE_EXIT_CODE,
    Log,
    PauseRequest,
    Progress,
    Redactor,
    StepPaths,
    StepTitle,
    parse_line,
    run_step,
    step_environment,
)


def script(directory: Path, body: str, name: str = "step") -> Path:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def run(path: Path, *, environment=None, timeout_s=10):
    lines: list[str] = []
    outcome = run_step([str(path)], environment or {}, timeout_s=timeout_s, on_line=lines.append)
    return outcome, lines


# --- the protocol lines ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "event"),
    [
        ("STEP Installing the system", StepTitle("Installing the system")),
        ("STEP", StepTitle("")),
        ("PROGRESS 0", Progress(0)),
        ("PROGRESS 42", Progress(42)),
        ("PROGRESS 100", Progress(100)),
        ("LOG disk is 5 GB", Log("disk is 5 GB")),
        ("PAUSE Click the toggle, then continue", PauseRequest("Click the toggle, then continue")),
        ("PAUSE", PauseRequest("")),
    ],
)
def test_a_protocol_line_becomes_its_event(line, event):
    assert parse_line(line) == event


@pytest.mark.parametrize(
    "line",
    [
        "PROGRESS 101",
        "PROGRESS -1",
        "PROGRESS lots",
        "PROGRESS",
        "PROGRESS 5 6",
        "STEPPING on it",
        "step lower case",
        "progress 5",
        "just some tool output",
        "",
    ],
)
def test_anything_else_is_only_log(line):
    assert parse_line(line) == Log(line)


# --- redaction ---------------------------------------------------------------------------


def test_every_occurrence_of_every_secret_is_masked():
    redact = Redactor(["Sup3r-secret", "AAAAA-BBBBB"])

    assert (
        redact("pw=Sup3r-secret key=AAAAA-BBBBB again Sup3r-secret") == "pw=*** key=*** again ***"
    )


def test_a_longer_secret_containing_a_shorter_one_is_masked_whole():
    redact = Redactor(["pass", "pass-word-1"])

    assert redact("x pass-word-1 y") == "x *** y"


def test_empty_secrets_mask_nothing():
    assert Redactor(["", ""])("unchanged text") == "unchanged text"


def test_text_without_secrets_is_unchanged():
    assert Redactor(["secret"])("nothing to see") == "nothing to see"


# --- running a step ----------------------------------------------------------------------


def test_stdout_and_stderr_lines_arrive_in_order(tmp_path):
    path = script(tmp_path, "echo one\necho two >&2\necho three")

    outcome, lines = run(path)

    assert lines == ["one", "two", "three"]
    assert outcome.exit_code == 0
    assert not outcome.timed_out


def test_the_exit_code_is_reported(tmp_path):
    outcome, _ = run(script(tmp_path, "echo boom; exit 3"))

    assert outcome.exit_code == 3


def test_the_pause_exit_code_is_the_agreed_one(tmp_path):
    assert PAUSE_EXIT_CODE == 75
    outcome, lines = run(script(tmp_path, "echo 'PAUSE wait for me'; exit 75"))

    assert outcome.exit_code == PAUSE_EXIT_CODE
    assert lines == ["PAUSE wait for me"]


def test_the_step_sees_only_the_environment_it_was_given(tmp_path, monkeypatch):
    monkeypatch.setenv("GUEST_CONTROL_TOKEN", "must-not-leak")
    path = script(tmp_path, 'echo "token=${GUEST_CONTROL_TOKEN-unset} step=$TT_STEP"')

    _, lines = run(path, environment={"TT_STEP": "fetch", "PATH": os.environ["PATH"]})

    assert lines == ["token=unset step=fetch"]


def test_the_command_is_an_argument_list_never_a_shell_string(tmp_path):
    awkward = tmp_path / "dir with spaces; echo injected"
    awkward.mkdir()
    path = script(awkward, "echo ran")

    outcome, lines = run(path)

    assert (outcome.exit_code, lines) == (0, ["ran"])


def test_a_step_that_cannot_be_started_is_a_failure_not_an_exception(tmp_path):
    lines: list[str] = []

    outcome = run_step([str(tmp_path / "missing")], {}, timeout_s=5, on_line=lines.append)

    assert outcome.exit_code is None
    assert outcome.timed_out is False
    assert "missing" in outcome.start_error


def test_a_very_long_line_is_cut(tmp_path):
    path = script(
        tmp_path, f"head -c {MAX_LINE_LENGTH * 3} /dev/zero | tr '\\0' x; echo; echo after"
    )

    _, lines = run(path)

    assert all(len(line) <= MAX_LINE_LENGTH for line in lines)
    assert lines[-1] == "after"


def test_output_that_is_not_text_does_not_break_the_reader(tmp_path):
    path = script(tmp_path, "printf 'caf\\377\\376 ok\\n'; echo next")

    outcome, lines = run(path)

    assert outcome.exit_code == 0
    assert lines[-1] == "next"
    assert lines[0].startswith("caf")


def test_a_step_past_its_timeout_is_killed_with_everything_it_started(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    path = script(tmp_path, f"sleep 60 &\necho $! > {child_pid_file}\nwait")
    started = time.monotonic()

    outcome, _ = run(path, timeout_s=1)

    assert outcome.timed_out is True
    assert time.monotonic() - started < 10
    child = int(child_pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _alive(child):
        time.sleep(0.05)
    assert not _alive(child)


def test_a_helper_left_behind_by_a_finished_step_does_not_hold_the_reader(tmp_path):
    path = script(tmp_path, "sleep 60 &\necho done")
    started = time.monotonic()

    outcome, lines = run(path)

    assert (outcome.exit_code, lines) == (0, ["done"])
    assert time.monotonic() - started < 10


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat_file = Path(f"/proc/{pid}/stat")
    return not (stat_file.exists() and stat_file.read_text().split()[2] == "Z")


# --- the environment ---------------------------------------------------------------------

PATHS = StepPaths(
    guest_dir=Path("/g/alpha"),
    guest_json=Path("/g/alpha/guest.json"),
    profile_dir=Path("/p/fake"),
    state_file=Path("/g/alpha/builds/b1/build.json"),
    build_dir=Path("/g/alpha/builds/b1"),
    log=Path("/g/alpha/builds/b1/log"),
    context_json=Path("/g/alpha/builds/b1/context.json"),
)


def test_a_step_is_told_where_everything_is_and_which_step_it_is():
    environment = step_environment(PATHS, step="define", build_id="b1", inherited={"PATH": "/bin"})

    assert environment == {
        "PATH": "/bin",
        "TT_GUEST_DIR": "/g/alpha",
        "TT_GUEST_JSON": "/g/alpha/guest.json",
        "TT_PROFILE_DIR": "/p/fake",
        "TT_STATE_FILE": "/g/alpha/builds/b1/build.json",
        "TT_BUILD_DIR": "/g/alpha/builds/b1",
        "TT_CONTEXT_JSON": "/g/alpha/builds/b1/context.json",
        "TT_STEP": "define",
        "TT_BUILD_ID": "b1",
        "TT_LOG": "/g/alpha/builds/b1/log",
    }


def test_the_services_secrets_are_not_inherited_by_a_step():
    inherited = {"PATH": "/bin", "GUEST_CONTROL_TOKEN": "t", "CAPE_API_TOKEN": "c", "LANG": "C"}

    environment = step_environment(PATHS, step="x", build_id="b", inherited=inherited)

    assert "GUEST_CONTROL_TOKEN" not in environment
    assert "CAPE_API_TOKEN" not in environment
    assert environment["LANG"] == "C"


def test_a_step_always_has_a_path():
    assert "/usr/bin" in step_environment(PATHS, step="x", build_id="b", inherited={})["PATH"]
