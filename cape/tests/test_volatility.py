"""Tests of `bin/volatility.py`: the one place a `vol` command line is built and its output read.

The runner is injected, so nothing here needs Volatility3 installed; the fake returns real
Volatility3 2.28.2 output (fixtures/volatility/).
"""

import sys
from pathlib import Path

import pytest
from fixtures.volatility_output import BANNER, UNSATISFIED, failure, fixture_rows, success
from volatility import (
    NO_SYMBOLS,
    VOLATILITY_COMMAND,
    CommandResult,
    Volatility,
    VolatilityUnavailableError,
    run_command,
)

DUMP = Path("/store/analyses/7/memory.dmp")
SYMBOLS = Path("/var/lib/libvirt/tartarus/symbols")


class FakeRunner:
    def __init__(self, *results: CommandResult | Exception) -> None:
        self.results = list(results)
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, command, timeout):
        self.calls.append((list(command), timeout))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def volatility(runner) -> Volatility:
    ticks = iter(range(0, 1000, 2))
    return Volatility(DUMP, SYMBOLS, runner, clock=lambda: next(ticks))


def test_the_command_line_reads_the_dump_in_place_offline_with_the_symbols_directory():
    command = volatility(FakeRunner()).command("windows.pslist")

    assert command == [
        VOLATILITY_COMMAND,
        "-q",
        "--offline",
        "-s",
        str(SYMBOLS),
        "-f",
        str(DUMP),
        "-r",
        "json",
        "windows.pslist",
    ]


def test_the_pids_follow_the_plugin_name_as_its_own_option():
    command = volatility(FakeRunner()).command("windows.malware.malfind", pids=[1936, 6304])

    assert command[command.index("windows.malware.malfind") :] == [
        "windows.malware.malfind",
        "--pid",
        "1936",
        "6304",
    ]


def test_the_command_never_allows_a_download():
    command = volatility(FakeRunner()).command("windows.pslist")

    assert "--offline" in command
    assert "-u" not in command
    assert "--remote-isf-url" not in command


def test_a_plugins_rows_are_returned_as_volatility_gave_them():
    runner = FakeRunner(success("windows.malware.malfind"))

    ran = volatility(runner).run("windows.malware.malfind", timeout=60, pids=[1936])

    assert ran.error is None
    assert ran.rows == fixture_rows("windows.malware.malfind")
    assert runner.calls[0][1] == 60


def test_the_seconds_are_what_the_runner_took():
    ran = volatility(FakeRunner(success("windows.pslist"))).run("windows.pslist", timeout=60)

    assert ran.seconds == 2


def test_an_empty_plugin_result_is_zero_rows_and_no_error():
    ran = volatility(FakeRunner(CommandResult(0, "[]\n", BANNER))).run("windows.pslist", 60)

    assert (ran.rows, ran.error) == ([], None)


def test_the_version_comes_from_the_banner_volatility_prints_to_stderr():
    ran = volatility(FakeRunner(success("windows.info"))).run("windows.info", timeout=60)

    assert ran.version == "2.28.2"


def test_a_run_without_a_banner_has_no_version():
    ran = volatility(FakeRunner(CommandResult(0, "[]", ""))).run("windows.pslist", timeout=60)

    assert ran.version is None


def test_missing_symbols_are_named_as_such_whichever_stream_volatility_wrote_them_to():
    runner = FakeRunner(
        failure(stdout=UNSATISFIED, stderr=BANNER + "Unable to validate the plugin requirements\n"),
        failure(stderr=BANNER + UNSATISFIED),
    )

    first = volatility(runner).run("windows.pslist", 60)
    second = volatility(runner).run("windows.pslist", 60)

    assert (first.rows, first.error) == (None, NO_SYMBOLS)
    assert second.error == NO_SYMBOLS


def test_any_other_failure_carries_the_status_and_the_last_line_volatility_wrote():
    stderr = BANNER + "Traceback (most recent call last):\n  ...\nValueError: bad page\n\n"

    ran = volatility(FakeRunner(failure(2, stderr=stderr))).run("windows.pslist", 60)

    assert ran.error == "volatility exited with status 2: ValueError: bad page"


def test_a_failure_with_no_stderr_still_has_a_message():
    ran = volatility(FakeRunner(failure(3, stderr=""))).run("windows.pslist", 60)

    assert ran.error == "volatility exited with status 3"


def test_a_very_long_last_line_is_cut():
    ran = volatility(FakeRunner(failure(1, stderr="x" * 5000))).run("windows.pslist", 60)

    assert len(ran.error) < 400


def test_a_plugin_that_ran_out_of_time_says_how_long_it_was_given():
    runner = FakeRunner(CommandResult(-9, "", "", timed_out=True))

    ran = volatility(runner).run("windows.malware.malfind", timeout=45.0)

    assert (ran.rows, ran.error) == (None, "timed out after 45 s")


@pytest.mark.parametrize(
    "stdout",
    ["", "not json", '{"PID": 4}', "[1, 2]", '[{"PID": 4}, "x"]'],
)
def test_output_that_is_not_a_list_of_rows_is_an_error_not_a_crash(stdout):
    ran = volatility(FakeRunner(CommandResult(0, stdout, BANNER))).run("windows.pslist", 60)

    assert ran.rows is None
    assert ran.error == "volatility printed output that is not a list of rows"


def test_output_larger_than_the_limit_is_refused_unparsed(monkeypatch):
    monkeypatch.setattr("volatility.MAX_OUTPUT_BYTES", 10)

    ran = volatility(FakeRunner(success("windows.pslist"))).run("windows.pslist", 60)

    assert ran.rows is None
    assert "larger than" in ran.error


@pytest.mark.parametrize("error", [FileNotFoundError("vol"), PermissionError("vol")])
def test_a_volatility_that_cannot_be_started_is_unavailable_not_a_plugin_failure(error):
    with pytest.raises(VolatilityUnavailableError, match=type(error).__name__):
        volatility(FakeRunner(error)).run("windows.pslist", 60)


# The real runner, against harmless commands of this interpreter.


def test_the_real_runner_returns_status_and_both_streams():
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"

    result = run_command([sys.executable, "-c", code], 10)

    assert result == CommandResult(3, "out\n", "err\n")


def test_the_real_runner_kills_a_command_that_runs_over_and_says_so():
    result = run_command([sys.executable, "-c", "import time; time.sleep(30)"], 0.3)

    assert result.timed_out


def test_the_real_runner_hands_the_child_only_the_environment_it_is_given(monkeypatch):
    monkeypatch.setenv("GUEST_CONTROL_TOKEN", "secret" * 8)
    code = "import os; print(sorted(os.environ))"

    result = run_command([sys.executable, "-c", code], 10, environment={"HOME": "/home/cape"})

    assert "GUEST_CONTROL_TOKEN" not in result.stdout
    assert "HOME" in result.stdout


def test_the_real_runner_does_not_read_the_services_stdin():
    result = run_command([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], 10)

    assert result.stdout == "''\n"
