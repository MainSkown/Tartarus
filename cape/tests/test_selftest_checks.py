"""The protocol a profile's check step speaks on its output, and how a run of it ends."""

import stat

import pytest

from guest_engine.selftest import (
    CHECK_LOG_LINES,
    ChecksCollector,
    ChecksFailed,
    PreparedChecks,
    run_check_step,
)
from guest_engine.steps import Redactor, StepControl

SECRET = "Sup3r-secret-pw"  # noqa: S105 - a fixture value


def collected(*lines: str) -> dict:
    collector = ChecksCollector()
    for line in lines:
        collector.add(line)
    return collector.report()


def test_a_fact_line_is_a_key_and_a_value():
    report = collected("FACT system.model=Standard PC (Q35 + ICH9, 2009)", "FACT os.build=26200.1")

    assert report["facts"] == {
        "system.model": "Standard PC (Q35 + ICH9, 2009)",
        "os.build": "26200.1",
    }
    assert report["log"] == []


def test_a_fact_value_may_hold_equals_signs_and_may_be_empty():
    assert collected("FACT a=b=c", "FACT empty=")["facts"] == {"a": "b=c", "empty": ""}


def test_a_giveaway_line_is_a_giveaway():
    report = collected("GIVEAWAY service: Tartarus agent", "GIVEAWAY folder under C:\\: sandbox")

    assert report["giveaways"] == ["service: Tartarus agent", "folder under C:\\: sandbox"]


def test_a_proof_is_ok_or_failed_with_a_message():
    report = collected("PROOF defender=ok", "PROOF eicar=failed the file was kept after 15 s")

    assert report["proofs"] == {
        "defender": {"ok": True, "message": ""},
        "eicar": {"ok": False, "message": "the file was kept after 15 s"},
    }


def test_a_failed_proof_may_have_no_message():
    assert collected("PROOF defender=failed")["proofs"] == {
        "defender": {"ok": False, "message": ""}
    }


def test_the_last_line_about_a_fact_or_a_proof_wins():
    report = collected("FACT a=1", "FACT a=2", "PROOF p=failed no", "PROOF p=ok")

    assert report["facts"] == {"a": "2"}
    assert report["proofs"] == {"p": {"ok": True, "message": ""}}


def test_every_other_line_is_log_with_the_log_prefix_dropped():
    report = collected("STEP Reverting", "PROGRESS 40", "LOG waiting for the agent", "plain text")

    assert report["log"] == ["STEP Reverting", "PROGRESS 40", "waiting for the agent", "plain text"]
    assert (report["facts"], report["giveaways"], report["proofs"]) == ({}, [], {})


@pytest.mark.parametrize(
    "line",
    [
        "FACT",
        "FACT novalue",
        "FACT =orphan",
        "FACT bad key=1",
        "GIVEAWAY",
        "GIVEAWAY   ",
        "PROOF",
        "PROOF defender",
        "PROOF defender=maybe",
        "PROOF defender=okay",
        "PROOF  =ok",
        "PROOF Bad Name=ok",
        "PROOF defender = ok",
        "fact a=1",
        " FACT a=1",
        "FACTS a=1",
    ],
)
def test_a_malformed_protocol_line_is_just_log(line):
    report = collected(line)

    assert (report["facts"], report["giveaways"], report["proofs"]) == ({}, [], {})
    assert report["log"] == [line]


@pytest.mark.parametrize("line", ["PROOF defender=ok", "FACT a=1", "GIVEAWAY the service"])
def test_a_protocol_line_that_came_from_the_guest_is_log_because_the_step_prefixes_guest_output(
    line,
):
    report = collected(f"LOG {line}")

    assert (report["facts"], report["giveaways"], report["proofs"]) == ({}, [], {})
    assert report["log"] == [line]


def test_only_the_last_log_lines_are_kept():
    report = collected(*(f"line {number}" for number in range(CHECK_LOG_LINES + 20)))

    assert len(report["log"]) == CHECK_LOG_LINES == 50
    assert report["log"][0] == "line 20"
    assert report["log"][-1] == f"line {CHECK_LOG_LINES + 19}"


def test_the_report_has_exactly_the_four_parts_of_the_contract():
    assert set(collected()) == {"facts", "giveaways", "proofs", "log"}


# --- running a step ----------------------------------------------------------------------


@pytest.fixture
def step(tmp_path):
    def make(body: str):
        path = tmp_path / "check-step"
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    return make


def run(path, tmp_path, *, timeout_s=30, secrets=(SECRET,), control=None, **environment):
    log = tmp_path / "log"
    prepared = PreparedChecks(path, {"PATH": "/usr/bin:/bin", **environment}, timeout_s, log)
    report = run_check_step(prepared, redact=Redactor(secrets), control=control or StepControl())
    return report, log


def test_a_step_that_exits_zero_gives_the_report_of_what_it_printed(step, tmp_path):
    path = step('echo "FACT a=1"\necho "GIVEAWAY x"\necho "PROOF p=ok"\necho "LOG hello"')

    report, _ = run(path, tmp_path)

    assert report == {
        "facts": {"a": "1"},
        "giveaways": ["x"],
        "proofs": {"p": {"ok": True, "message": ""}},
        "log": ["hello"],
    }


def test_the_step_gets_the_environment_it_is_given_and_nothing_else_from_the_service(
    step, tmp_path, monkeypatch
):
    monkeypatch.setenv("GUEST_CONTROL_TOKEN", "must-not-leak")
    path = step('echo "LOG token=${GUEST_CONTROL_TOKEN:-unset} mine=$TT_MINE"')

    report, _ = run(path, tmp_path, TT_MINE="yes")

    assert report["log"] == ["token=unset mine=yes"]


def test_every_line_the_step_wrote_goes_to_the_log_file(step, tmp_path):
    path = step('echo "FACT a=1"\necho "noise"')

    _, log = run(path, tmp_path)

    assert log.read_text().splitlines() == ["FACT a=1", "noise"]


def test_the_guests_secrets_never_reach_the_report_or_the_log_file(step, tmp_path):
    path = step(
        f'echo "FACT password={SECRET}"\necho "GIVEAWAY {SECRET} in a name"\n'
        f'echo "PROOF p=failed saw {SECRET}"\necho "LOG {SECRET}"'
    )

    report, log = run(path, tmp_path)

    assert SECRET not in str(report)
    assert SECRET not in log.read_text()
    assert report["facts"] == {"password": "***"}


@pytest.mark.parametrize("code", [1, 3, 75])
def test_a_step_that_exits_non_zero_fails_with_the_end_of_its_log_and_the_code(
    step, tmp_path, code
):
    path = step(f'echo "FACT a=1"\necho "LOG the agent never answered"\nexit {code}')

    with pytest.raises(ChecksFailed) as raised:
        run(path, tmp_path)

    assert f"exit code {code}" in str(raised.value)
    assert "the agent never answered" in str(raised.value)


def test_a_failure_message_holds_only_the_last_lines_and_never_a_secret(step, tmp_path):
    path = step(f'for n in $(seq 1 40); do echo "line $n"; done\necho "LOG {SECRET}"\nexit 2')

    with pytest.raises(ChecksFailed) as raised:
        run(path, tmp_path)

    message = str(raised.value)
    assert "line 40" in message
    assert "line 5\n" not in message
    assert SECRET not in message


def test_a_step_past_its_timeout_is_stopped_and_the_failure_says_so(step, tmp_path):
    path = step("sleep 300")

    with pytest.raises(ChecksFailed, match="timed out after 1 s"):
        run(path, tmp_path, timeout_s=1)


def test_a_step_that_cannot_be_started_is_a_failure_that_says_why(tmp_path):
    with pytest.raises(ChecksFailed, match="could not be started"):
        run(tmp_path / "missing", tmp_path)


def test_a_step_stopped_by_the_services_shutdown_says_that(step, tmp_path):
    control = StepControl()
    control.stop(0)
    path = step("sleep 300")

    with pytest.raises(ChecksFailed, match="service was stopped"):
        run(path, tmp_path, control=control)
