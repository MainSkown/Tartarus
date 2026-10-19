from pathlib import Path

import pytest

from app.analyses.memory import MemoryFindings, MemorySummary
from app.analyses.memory_step import MemoryStep
from app.db.models import Analysis
from app.guest.errors import (
    GuestControlBadResponse,
    GuestControlRejected,
    GuestControlUnreachable,
)
from app.guest.schemas import MemoryAnalysis

TASK_ID = 7
DUMP_BYTES = 4_294_776_995
ANALYSED = MemoryAnalysis(
    plugins={"windows.pslist": 144, "windows.malware.malfind": 2},
    seconds=4.2,
    pids=[1234, 2345],
)


class FakeMemoryControl:
    """The control service's memory routes: answers as scripted and remembers the calls."""

    def __init__(self) -> None:
        self.analysis: MemoryAnalysis | Exception = ANALYSED
        self.deletion: Exception | None = None
        self.calls: list[tuple[str, int]] = []

    async def analyse_memory(self, task_id: int) -> MemoryAnalysis:
        self.calls.append(("analyse", task_id))
        if isinstance(self.analysis, Exception):
            raise self.analysis
        return self.analysis

    async def delete_memory_dump(self, task_id: int) -> None:
        self.calls.append(("delete", task_id))
        if self.deletion is not None:
            raise self.deletion


@pytest.fixture
def control() -> FakeMemoryControl:
    return FakeMemoryControl()


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    return tmp_path / "cape-storage"


@pytest.fixture
def step(control: FakeMemoryControl, storage: Path) -> MemoryStep:
    return MemoryStep(control, storage)


def put_dump(storage: Path, size: int = 1234) -> None:
    folder = storage / "analyses" / str(TASK_ID)
    folder.mkdir(parents=True)
    with (folder / "memory.dmp").open("wb") as dump:
        dump.truncate(size)


def analysis_of(
    *, memory_dump: bool = True, keep: bool = False, summary: dict[str, object] | None = None
) -> Analysis:
    options = {"memory_dump": memory_dump, "keep_memory_dump": keep}
    return Analysis(options=options, summary=summary)


def summary_of(**changes: object) -> MemorySummary:
    fields = {"dump_taken": True, "findings": MemoryFindings.OK, **changes}
    return MemorySummary.model_validate(fields)


async def test_an_analysis_that_did_not_ask_for_a_dump_is_left_alone(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    assert await step.run(analysis_of(memory_dump=False), TASK_ID) is None
    assert control.calls == []


async def test_an_analysed_dump_is_recorded_with_its_size(
    step: MemoryStep, control: FakeMemoryControl, storage: Path
) -> None:
    put_dump(storage, DUMP_BYTES)

    memory = await step.run(analysis_of(), TASK_ID)

    assert memory == summary_of(dump_bytes=DUMP_BYTES)
    assert control.calls == [("analyse", TASK_ID)]


async def test_a_dump_cape_skipped_is_recorded_as_not_taken(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    control.analysis = GuestControlRejected("analyse_memory", 404, "no memory dump for this task")

    memory = await step.run(analysis_of(), TASK_ID)

    assert memory is not None
    assert (memory.dump_taken, memory.findings) == (False, MemoryFindings.UNAVAILABLE)
    assert memory.error is not None
    assert "50000 MB" in memory.error


@pytest.mark.parametrize(
    "failure",
    [
        GuestControlRejected("analyse_memory", 409, "this task's memory dump is being analysed"),
        GuestControlRejected("analyse_memory", 502, "volatility3 could not be started"),
        GuestControlRejected("analyse_memory", 500, "the results could not be written"),
        GuestControlUnreachable("analyse_memory", "ReadTimeout"),
        GuestControlBadResponse("analyse_memory", "wrong shape"),
        RuntimeError("a bug in the step must not fail the analysis"),
    ],
    ids=["busy", "no-volatility", "unwritable", "timeout", "bad-answer", "bug"],
)
async def test_a_failed_analysis_never_raises_and_says_what_went_wrong(
    step: MemoryStep, control: FakeMemoryControl, storage: Path, failure: Exception
) -> None:
    put_dump(storage)
    control.analysis = failure

    memory = await step.run(analysis_of(), TASK_ID)

    assert memory is not None
    assert (memory.dump_taken, memory.findings) == (True, MemoryFindings.FAILED)
    assert memory.error


async def test_the_error_of_a_refused_analysis_is_the_services_own_text(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    control.analysis = GuestControlRejected("analyse_memory", 502, "volatility3 could not start")

    memory = await step.run(analysis_of(), TASK_ID)

    assert memory is not None
    assert memory.error == "volatility3 could not start"


async def test_a_failure_without_a_dump_on_disk_is_not_a_taken_dump(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    control.analysis = GuestControlUnreachable("analyse_memory", "ConnectError")

    memory = await step.run(analysis_of(), TASK_ID)

    assert memory is not None
    assert (memory.dump_taken, memory.dump_bytes) == (False, None)


async def test_a_run_where_every_plugin_failed_has_failed_findings(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    control.analysis = MemoryAnalysis(
        plugins={"windows.pslist": 0, "windows.cmdline": 0},
        seconds=2.0,
        pids=[],
        errors={"windows.pslist": "no symbols", "windows.cmdline": "no symbols"},
    )

    memory = await step.run(analysis_of(), TASK_ID)

    assert memory is not None
    assert memory.findings is MemoryFindings.FAILED
    assert memory.error == "windows.cmdline: no symbols; windows.pslist: no symbols"


async def test_a_run_where_one_plugin_failed_keeps_the_findings_and_names_the_failure(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    control.analysis = MemoryAnalysis(
        plugins={"windows.pslist": 144, "windows.malware.malfind": 0},
        seconds=2.0,
        pids=[1],
        errors={"windows.malware.malfind": "timed out after 120 s"},
    )

    memory = await step.run(analysis_of(), TASK_ID)

    assert memory is not None
    assert memory.findings is MemoryFindings.OK
    assert memory.error == "windows.malware.malfind: timed out after 120 s"


async def test_a_reingest_keeps_what_the_first_run_recorded_and_does_not_analyse_again(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    recorded = summary_of(dump_bytes=99, dump_deleted=True)
    analysis = analysis_of(summary={"memory": recorded.model_dump(mode="json")})

    assert await step.run(analysis, TASK_ID) == recorded
    assert control.calls == []


async def test_a_dump_is_deleted_after_the_ingest_unless_it_is_kept(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    released = await step.release(analysis_of(), TASK_ID, summary_of())

    assert control.calls == [("delete", TASK_ID)]
    assert released == summary_of(dump_deleted=True)


async def test_a_dump_the_analyst_keeps_is_not_deleted(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    released = await step.release(analysis_of(keep=True), TASK_ID, summary_of())

    assert control.calls == []
    assert released == summary_of(dump_deleted=None)


async def test_a_dump_that_is_already_gone_counts_as_deleted(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    control.deletion = GuestControlRejected("delete_memory_dump", 404, "no dump")

    released = await step.release(analysis_of(), TASK_ID, summary_of())

    assert released is not None
    assert released.dump_deleted is True


@pytest.mark.parametrize(
    "failure",
    [
        GuestControlRejected("delete_memory_dump", 409, "being analysed"),
        GuestControlUnreachable("delete_memory_dump", "ConnectError"),
        RuntimeError("a bug"),
    ],
)
async def test_a_dump_that_cannot_be_deleted_is_recorded_and_never_raised(
    step: MemoryStep, control: FakeMemoryControl, failure: Exception
) -> None:
    control.deletion = failure

    released = await step.release(analysis_of(), TASK_ID, summary_of())

    assert released is not None
    assert released.dump_deleted is False


async def test_there_is_nothing_to_delete_when_no_dump_was_taken(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    summary = summary_of(dump_taken=False, findings=MemoryFindings.UNAVAILABLE)

    assert await step.release(analysis_of(), TASK_ID, summary) == summary
    assert control.calls == []


async def test_nothing_is_released_for_an_analysis_without_a_memory_summary(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    assert await step.release(analysis_of(memory_dump=False), TASK_ID, None) is None
    assert control.calls == []


async def test_a_delete_that_failed_the_first_time_is_tried_again_on_a_reingest(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    released = await step.release(analysis_of(), TASK_ID, summary_of(dump_deleted=False))

    assert control.calls == [("delete", TASK_ID)]
    assert released == summary_of(dump_deleted=True)


async def test_a_dump_already_deleted_by_the_first_run_is_not_deleted_again(
    step: MemoryStep, control: FakeMemoryControl
) -> None:
    deleted = summary_of(dump_deleted=True)

    assert await step.release(analysis_of(), TASK_ID, deleted) == deleted
    assert control.calls == []
