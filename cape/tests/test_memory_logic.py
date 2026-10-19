"""Tests of `bin/memory_logic.py`: running Volatility3 on an analysis's memory dump and
writing what it found next to the dump, where the backend (read-only) reads it.

The `vol` runner is a fake that returns real Volatility3 output; the storage is a temp folder.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from fixtures.volatility_output import (
    BANNER,
    KERNEL_GUID,
    UNSATISFIED,
    failure,
    fixture_rows,
    missing_symbols_log,
    success,
)
from memory_logic import (
    ANALYSIS_FILE_MODE,
    AlreadyRunningError,
    DumpMissingError,
    MemoryAnalyser,
    analyse_response,
    delete_dump_response,
    pids_from_report,
)
from volatility import NO_SYMBOLS, CommandResult, VolatilityUnavailableError

PLUGINS = [
    "windows.pslist",
    "windows.cmdline",
    "windows.malware.malfind",
    "windows.malware.hollowprocesses",
]
ISF = "ntkrnlmp-24DE61DB3A27C5B383DFF181CB51F7E1-1.json.xz"
DUMP_CONTENT = b"ELF" * 100
REPORT_PIDS = [6304, 1936, 1384]


def report_with_processes(pids=REPORT_PIDS) -> dict:
    return {"behavior": {"processes": [{"process_id": pid, "process_name": "x"} for pid in pids]}}


class ScriptedRunner:
    """Answers each `vol` call with the fixture of the plugin it names, unless told otherwise."""

    def __init__(self, clock=None) -> None:
        self.calls: list[tuple[list[str], float]] = []
        self.overrides: dict[str, CommandResult] = {}
        self.durations: dict[str, float] = {}
        self.clock = clock
        self.on_call = None

    @staticmethod
    def plugin_of(command) -> str:
        return next(word for word in command if word.startswith("windows."))

    def pids_of(self, command) -> list[int]:
        return (
            [int(word) for word in command[command.index("--pid") + 1 :]]
            if "--pid" in command
            else []
        )

    def __call__(self, command, timeout):
        self.calls.append((list(command), timeout))
        plugin = self.plugin_of(command)
        if self.on_call:
            self.on_call(plugin)
        if self.clock is not None:
            self.clock.now += self.durations.get(plugin, 0)
        return self.overrides.get(plugin) or success(plugin)

    @property
    def plugins_run(self) -> list[str]:
        return [self.plugin_of(command) for command, _ in self.calls]


def fails_with(error: Exception):
    def raise_error(_plugin: str) -> None:
        raise error

    return raise_error


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def storage(tmp_path) -> Path:
    analysis = tmp_path / "storage" / "analyses" / "7"
    (analysis / "reports").mkdir(parents=True)
    (analysis / "memory.dmp").write_bytes(DUMP_CONTENT)
    (analysis / "reports" / "report.json").write_text(json.dumps(report_with_processes()))
    return tmp_path / "storage"


@pytest.fixture
def runner() -> ScriptedRunner:
    return ScriptedRunner()


@pytest.fixture
def logged() -> list[str]:
    return []


@pytest.fixture
def proc(tmp_path) -> Path:
    root = tmp_path / "proc"
    root.mkdir()
    return root


@pytest.fixture
def analyser(storage, tmp_path, runner, logged, proc) -> MemoryAnalyser:
    analyser = MemoryAnalyser(storage, tmp_path / "symbols", runner, log=logged.append)
    analyser.proc_directory = proc
    return analyser


def memory_folder(storage: Path) -> Path:
    return storage / "analyses" / "7" / "memory"


def written(storage: Path, name: str):
    return json.loads((memory_folder(storage) / name).read_text())


def run_json(storage: Path) -> dict:
    return written(storage, "run.json")


# pids_from_report


def test_the_pids_are_the_analysis_own_processes_sorted_and_without_repeats(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps(report_with_processes([30, 10, 30, 20])))

    assert pids_from_report(report) == [10, 20, 30]


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "not json",
        "[]",
        "{}",
        '{"behavior": null}',
        '{"behavior": {"processes": null}}',
        '{"behavior": {"processes": []}}',
        '{"behavior": {"processes": ["x", 5, null]}}',
    ],
)
def test_a_report_that_cannot_give_pids_gives_none_and_no_error(tmp_path, content):
    report = tmp_path / "report.json"
    if content is not None:
        report.write_text(content)

    assert pids_from_report(report) == []


def test_entries_whose_process_id_is_not_a_real_pid_are_skipped(tmp_path):
    processes = [{"process_id": "12"}, {"process_id": True}, {"process_id": -4}, {"process_id": 8}]
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"behavior": {"processes": processes}}))

    assert pids_from_report(report) == [8]


# analyse: what is run


def test_the_first_run_is_the_info_probe_and_each_plugin_follows_in_order(analyser, runner):
    analyser.analyse(7)

    assert runner.plugins_run == ["windows.info", *PLUGINS]


def test_only_the_per_process_plugins_are_limited_to_the_analysis_pids(analyser, runner):
    analyser.analyse(7)

    pids_by_plugin = {runner.plugin_of(c): runner.pids_of(c) for c, _ in runner.calls}
    assert pids_by_plugin == {
        "windows.info": [],
        "windows.pslist": [],
        "windows.cmdline": [],
        "windows.malware.malfind": [1384, 1936, 6304],
        "windows.malware.hollowprocesses": [1384, 1936, 6304],
    }


def test_volatility_reads_the_dump_where_it_is(analyser, runner, storage):
    analyser.analyse(7)

    commands = [command for command, _ in runner.calls]
    dump = str(storage / "analyses" / "7" / "memory.dmp")
    assert all(command[command.index("-f") + 1] == dump for command in commands)


# analyse: what is written


def test_each_plugin_is_written_as_one_json_array_of_the_rows_volatility_gave(analyser, storage):
    analyser.analyse(7)

    for plugin in PLUGINS:
        assert written(storage, f"{plugin}.json") == fixture_rows(plugin)


def test_run_json_says_what_ran_with_what_and_how_long(analyser, storage, runner):
    clock = Clock()
    analyser.clock = clock
    runner.clock = clock
    runner.durations = {"windows.pslist": 1.5, "windows.malware.malfind": 0.5}

    analyser.analyse(7)

    run = run_json(storage)
    assert run["volatility"] == "2.28.2"
    assert run["dump_bytes"] == len(DUMP_CONTENT)
    assert run["pids"] == [1384, 1936, 6304]
    assert run["symbols"] == ISF
    assert {name: (entry["rows"], entry["error"]) for name, entry in run["plugins"].items()} == {
        "windows.pslist": (144, None),
        "windows.cmdline": (144, None),
        "windows.malware.malfind": (10, None),
        "windows.malware.hollowprocesses": (2, None),
    }
    assert run["plugins"]["windows.pslist"]["seconds"] == 1.5
    assert run["plugins"]["windows.malware.malfind"]["seconds"] == 0.5
    assert set(run) == {"volatility", "dump_bytes", "pids", "plugins", "symbols"}


def test_the_answer_summarises_rows_errors_pids_and_seconds(analyser):
    summary = analyser.analyse(7)

    assert summary == {
        "plugins": {
            "windows.pslist": 144,
            "windows.cmdline": 144,
            "windows.malware.malfind": 10,
            "windows.malware.hollowprocesses": 2,
        },
        "errors": {},
        "seconds": summary["seconds"],
        "pids": [1384, 1936, 6304],
    }
    assert summary["seconds"] >= 0


def test_what_is_written_can_be_read_by_other_users_whatever_the_services_umask(analyser, storage):
    previous = os.umask(0o077)
    try:
        analyser.analyse(7)
    finally:
        os.umask(previous)

    folder = memory_folder(storage)
    assert stat.S_IMODE(folder.stat().st_mode) == 0o755
    modes = {stat.S_IMODE(file.stat().st_mode) for file in folder.iterdir()}
    assert modes == {ANALYSIS_FILE_MODE}


def test_a_second_run_replaces_the_first_and_leaves_no_file_of_a_plugin_that_now_fails(
    analyser, storage, runner
):
    analyser.analyse(7)
    runner.overrides["windows.cmdline"] = failure(2, stderr=BANNER + "boom\n")

    analyser.analyse(7)

    assert not (memory_folder(storage) / "windows.cmdline.json").exists()
    assert (memory_folder(storage) / "windows.pslist.json").exists()


def test_run_json_is_written_last_so_its_presence_means_the_run_finished(analyser, monkeypatch):
    order: list[str] = []
    original = Path.write_text

    def recording(self, *arguments, **options):
        order.append(self.name)
        return original(self, *arguments, **options)

    monkeypatch.setattr(Path, "write_text", recording)

    analyser.analyse(7)

    assert order[-1].startswith("run.json")
    assert len(order) == 5


# analyse: no pids, failures


@pytest.mark.parametrize("report", [None, "garbage", json.dumps(report_with_processes([]))])
def test_without_pids_only_the_cheap_plugins_run_and_findings_are_empty_not_an_error(
    analyser, storage, runner, report
):
    report_file = storage / "analyses" / "7" / "reports" / "report.json"
    if report is None:
        report_file.unlink()
    else:
        report_file.write_text(report)

    summary = analyser.analyse(7)

    assert runner.plugins_run == ["windows.info", "windows.pslist", "windows.cmdline"]
    assert written(storage, "windows.malware.malfind.json") == []
    assert written(storage, "windows.malware.hollowprocesses.json") == []
    run = run_json(storage)
    assert run["pids"] == []
    findings = run["plugins"]["windows.malware.malfind"]
    assert (findings["rows"], findings["error"]) == (0, None)
    assert findings["skipped"] == "the report names no process of the analysis"
    assert summary["errors"] == {}


def test_a_plugin_that_fails_records_its_error_writes_no_file_and_the_others_still_run(
    analyser, storage, runner
):
    runner.overrides["windows.cmdline"] = failure(2, stderr=BANNER + "ValueError: bad page\n")

    summary = analyser.analyse(7)

    cmdline = run_json(storage)["plugins"]["windows.cmdline"]
    assert cmdline["rows"] == 0
    assert cmdline["error"] == "volatility exited with status 2: ValueError: bad page"
    assert not (memory_folder(storage) / "windows.cmdline.json").exists()
    assert summary["errors"] == {"windows.cmdline": cmdline["error"]}
    assert summary["plugins"]["windows.cmdline"] == 0
    assert summary["plugins"]["windows.malware.hollowprocesses"] == 2


def test_missing_symbols_fail_every_plugin_the_same_way_and_nothing_else_runs(
    analyser, storage, runner
):
    runner.overrides["windows.info"] = failure(stdout=UNSATISFIED)

    summary = analyser.analyse(7)

    assert runner.plugins_run == ["windows.info"]
    run = run_json(storage)
    assert run["symbols"] is None
    assert run["volatility"] == "2.28.2"
    assert {entry["error"] for entry in run["plugins"].values()} == {NO_SYMBOLS}
    assert set(run["plugins"]) == set(PLUGINS)
    assert summary["errors"] == dict.fromkeys(PLUGINS, NO_SYMBOLS)
    assert sorted(file.name for file in memory_folder(storage).iterdir()) == ["run.json"]


def test_only_the_probe_asks_volatility_for_its_info_log(analyser, runner):
    analyser.analyse(7)

    verbose = {runner.plugin_of(command): "-v" in command for command, _ in runner.calls}
    assert verbose == {"windows.info": True, **dict.fromkeys(PLUGINS, False)}


def test_missing_symbols_name_the_kernels_pdb_id_in_the_answer_and_in_run_json(
    analyser, storage, runner
):
    runner.overrides["windows.info"] = failure(
        stdout=UNSATISFIED, stderr=BANNER + missing_symbols_log(age=3)
    )

    summary = analyser.analyse(7)

    expected = {"guid": KERNEL_GUID, "age": 3}
    assert summary["missing_symbols"] == expected
    assert run_json(storage)["missing_symbols"] == expected
    assert summary["errors"] == dict.fromkeys(PLUGINS, NO_SYMBOLS)


def test_missing_symbols_whose_id_cannot_be_read_say_so_without_an_id(analyser, storage, runner):
    runner.overrides["windows.info"] = failure(stdout=UNSATISFIED)

    summary = analyser.analyse(7)

    assert "missing_symbols" not in summary
    assert "missing_symbols" not in run_json(storage)


def test_a_dump_that_has_its_symbols_carries_no_missing_symbols_key(analyser, storage):
    summary = analyser.analyse(7)

    assert "missing_symbols" not in summary
    assert "missing_symbols" not in run_json(storage)


def test_a_dump_volatility_cannot_open_fails_every_plugin_with_the_probes_reason(analyser, runner):
    runner.overrides["windows.info"] = CommandResult(-9, "", "", timed_out=True)

    summary = analyser.analyse(7)

    assert runner.plugins_run == ["windows.info"]
    assert set(summary["errors"].values()) == {"timed out after 120 s"}


def test_symbols_are_null_when_the_probe_does_not_say_which_file_it_used(analyser, storage, runner):
    runner.overrides["windows.info"] = CommandResult(0, "[]", BANNER)

    analyser.analyse(7)

    assert run_json(storage)["symbols"] is None


def test_a_volatility_that_cannot_start_is_raised_and_leaves_the_earlier_results_alone(
    analyser, storage, runner
):
    analyser.analyse(7)
    before = (memory_folder(storage) / "run.json").read_text()

    def cannot_start(*_arguments):
        raise FileNotFoundError("vol")

    analyser.runner = cannot_start
    with pytest.raises(VolatilityUnavailableError):
        analyser.analyse(7)

    assert (memory_folder(storage) / "run.json").read_text() == before


# analyse: time


def test_each_plugin_gets_the_per_plugin_limit_or_what_is_left_of_the_overall_one(analyser, runner):
    clock = Clock()
    analyser.clock = clock
    runner.clock = clock
    analyser.plugin_timeout = 60
    analyser.overall_timeout = 100
    runner.durations = {"windows.info": 30, "windows.pslist": 30, "windows.cmdline": 30}

    analyser.analyse(7)

    timeouts = {runner.plugin_of(c): timeout for c, timeout in runner.calls}
    assert timeouts["windows.info"] == 60
    assert timeouts["windows.pslist"] == 60
    assert timeouts["windows.cmdline"] == 40
    assert timeouts["windows.malware.malfind"] == 10


def test_a_plugin_that_would_start_after_the_overall_limit_is_not_run_and_says_so(
    analyser, storage, runner
):
    clock = Clock()
    analyser.clock = clock
    runner.clock = clock
    analyser.plugin_timeout = 60
    analyser.overall_timeout = 100
    runner.durations = {"windows.info": 50, "windows.pslist": 50}

    summary = analyser.analyse(7)

    assert runner.plugins_run == ["windows.info", "windows.pslist"]
    assert summary["errors"]["windows.cmdline"] == "the overall time limit of 100 s was reached"
    assert summary["errors"]["windows.malware.hollowprocesses"].startswith("the overall time limit")
    assert summary["plugins"]["windows.pslist"] == 144


# analyse: the dump and the lock


def test_an_analysis_without_a_dump_is_missing(analyser, storage):
    (storage / "analyses" / "7" / "memory.dmp").unlink()

    with pytest.raises(DumpMissingError):
        analyser.analyse(7)


def test_an_analysis_that_does_not_exist_is_missing(analyser):
    with pytest.raises(DumpMissingError):
        analyser.analyse(99)


def test_a_dump_that_is_a_symlink_is_not_followed(analyser, storage, tmp_path):
    dump = storage / "analyses" / "7" / "memory.dmp"
    outside = tmp_path / "outside"
    outside.write_bytes(b"x")
    dump.unlink()
    dump.symlink_to(outside)

    with pytest.raises(DumpMissingError):
        analyser.analyse(7)

    assert outside.exists()


def test_a_second_analyse_of_the_same_task_while_one_runs_is_refused(analyser, runner):
    refused = []

    def asks_again(plugin):
        if plugin == "windows.pslist":
            with pytest.raises(AlreadyRunningError) as raised:
                analyser.analyse(7)
            refused.append(raised.value)

    runner.on_call = asks_again

    analyser.analyse(7)

    assert len(refused) == 1


def test_the_task_is_free_again_after_a_run_that_failed(analyser, runner):
    runner.on_call = fails_with(FileNotFoundError("vol"))
    with pytest.raises(VolatilityUnavailableError):
        analyser.analyse(7)
    runner.on_call = None

    assert analyser.analyse(7)["plugins"]["windows.pslist"] == 144


# delete_dump


def test_deleting_the_dump_removes_only_the_dump(analyser, storage):
    analyser.analyse(7)

    analyser.delete_dump(7)

    assert not (storage / "analyses" / "7" / "memory.dmp").exists()
    assert (memory_folder(storage) / "run.json").exists()
    assert (storage / "analyses" / "7" / "reports" / "report.json").exists()


def test_deleting_a_dump_that_is_not_there_is_missing(analyser, storage):
    (storage / "analyses" / "7" / "memory.dmp").unlink()

    with pytest.raises(DumpMissingError):
        analyser.delete_dump(7)


def test_a_dump_cannot_be_deleted_while_it_is_being_read(analyser, runner):
    refused = []

    def deletes(plugin):
        if plugin == "windows.pslist":
            with pytest.raises(AlreadyRunningError) as raised:
                analyser.delete_dump(7)
            refused.append(raised.value)

    runner.on_call = deletes

    analyser.analyse(7)

    assert len(refused) == 1


def hold_open(proc: Path, pid: int, name: str, path: Path, *, deleted: bool) -> None:
    descriptors = proc / str(pid) / "fd"
    descriptors.mkdir(parents=True)
    (proc / str(pid) / "comm").write_text(name + "\n")
    os.symlink(f"{path}{' (deleted)' if deleted else ''}", descriptors / "7")


def test_a_process_still_holding_the_deleted_dump_is_reported_and_logged(
    analyser, storage, proc, logged
):
    dump = storage / "analyses" / "7" / "memory.dmp"
    hold_open(proc, 4242, "cape-processor", dump, deleted=True)
    hold_open(proc, 99, "cat", storage / "analyses" / "7" / "other", deleted=True)
    hold_open(proc, 100, "tail", dump, deleted=False)

    holders = analyser.delete_dump(7)

    assert [(holder.pid, holder.name) for holder in holders] == [(4242, "cape-processor")]
    assert any("4242" in line and "cape-processor" in line for line in logged)


def test_the_real_proc_shows_a_process_that_holds_the_deleted_dump(analyser, storage):
    dump = storage / "analyses" / "7" / "memory.dmp"
    reader = subprocess.Popen(  # noqa: S603 - this interpreter, a fixed script
        [
            sys.executable,
            "-c",
            "import sys, time; f = open(sys.argv[1]); print(1, flush=True); time.sleep(60)",
            str(dump),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        reader.stdout.readline()
        analyser.proc_directory = Path("/proc")

        holders = analyser.delete_dump(7)
    finally:
        reader.kill()
        reader.wait()

    assert [holder.pid for holder in holders] == [reader.pid]


def test_no_holder_means_the_space_is_free_and_nothing_is_logged_as_a_problem(analyser, logged):
    assert analyser.delete_dump(7) == []
    assert not any("still open" in line for line in logged)


def test_an_unreadable_proc_entry_does_not_fail_the_delete(analyser, proc):
    (proc / "5").mkdir()
    (proc / "not-a-pid").mkdir()

    assert analyser.delete_dump(7) == []


# The responses


@pytest.mark.parametrize("raw", ["", "abc", "7a", "-1", "%2e%2e", "../7", "9" * 19, "٣"])
def test_a_task_id_that_is_not_digits_is_400_and_nothing_is_touched(analyser, runner, raw):
    assert analyse_response(raw, analyser) == (400, {"error": "the task id must be digits only"})
    assert delete_dump_response(raw, analyser) == (
        400,
        {"error": "the task id must be digits only"},
    )
    assert runner.calls == []


def test_a_task_id_with_leading_zeros_is_the_same_task(analyser):
    status, _ = analyse_response("007", analyser)

    assert status == 200


def test_analyse_answers_200_with_the_summary(analyser):
    status, body = analyse_response("7", analyser)

    assert status == 200
    assert body["plugins"]["windows.malware.malfind"] == 10
    assert body["pids"] == [1384, 1936, 6304]


def test_analyse_without_a_dump_is_404(analyser):
    assert analyse_response("99", analyser) == (404, {"error": "no memory dump for this task"})


def test_analyse_while_running_is_409(analyser, runner):
    answers = []
    runner.on_call = lambda _plugin: answers.append(analyse_response("7", analyser))

    analyser.analyse(7)

    assert answers[0] == (409, {"error": "this task's memory dump is being analysed"})


def test_analyse_with_a_volatility_that_cannot_start_is_502_with_a_readable_error(analyser, runner):
    runner.on_call = fails_with(PermissionError("vol"))

    status, body = analyse_response("7", analyser)

    assert (status, body) == (502, {"error": "volatility could not be started (PermissionError)"})


def test_analyse_that_cannot_write_its_results_is_500_naming_the_problem(analyser, storage):
    (storage / "analyses" / "7").chmod(0o555)
    try:
        if os.access(storage / "analyses" / "7", os.W_OK):
            pytest.skip("running as a user that ignores directory permissions")
        status, body = analyse_response("7", analyser)
    finally:
        (storage / "analyses" / "7").chmod(0o755)

    assert status == 500
    assert body["error"].startswith("the results could not be written (")


def test_delete_answers_204_then_404(analyser):
    assert delete_dump_response("7", analyser) == (204, None)
    assert delete_dump_response("7", analyser) == (
        404,
        {"error": "no memory dump for this task"},
    )


def test_delete_while_analysing_is_409(analyser, runner):
    answers = []
    runner.on_call = lambda _plugin: answers.append(delete_dump_response("7", analyser))

    analyser.analyse(7)

    assert answers[0] == (409, {"error": "this task's memory dump is being analysed"})
