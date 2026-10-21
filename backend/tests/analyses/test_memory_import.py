from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.analyses.memory import MemoryFindings
from app.analyses.memory_import import MemoryImport, MemoryImportFailedError, image_task_id
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from app.guest.schemas import MemoryAnalysis, MissingSymbols
from app.imports.upload import import_file
from app.ingest.ingester import ReportIngester
from tests.ingest.fake_index import FakeIndex
from tests.ingest.volatility_cases import P9_INJECTED_PID, write_p9_image_memory

ANALYSIS_ID = 12
STARTED_AT = datetime(2026, 10, 22, 8, 0, 0, tzinfo=UTC)
UPLOAD = b"\x7fELF" + bytes(2000)
NEEDED = MissingSymbols(guid="24DE61DB3A27C5B383DFF181CB51F7E1", age=1)
SCANNED = MemoryAnalysis(
    plugins={"windows.pslist": 147, "windows.malware.malfind": 16},
    seconds=66.0,
    pids=[],
)
NO_SYMBOLS = "no symbols for this Windows build"
NOT_A_MEMORY_IMAGE = "not a memory image: volatility found no Windows kernel in the file"

type Answer = MemoryAnalysis | Exception


class FakeImageControl:
    """The control service for an image: answers as scripted, leaves the P2 findings in the task's
    `memory/` folder whenever an answer reports plugins that ran.
    """

    def __init__(self, storage: Path, answers: list[Answer]) -> None:
        self.storage = storage
        self.answers = answers
        self.calls: list[tuple[str, object]] = []
        self.symbols_error: Exception | None = None

    async def analyse_memory(self, task_id: int, image: str | None = None) -> MemoryAnalysis:
        self.calls.append(("analyse", (task_id, image)))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if not answer.errors:
            write_p9_image_memory(self.storage / "analyses" / str(task_id))
        return answer

    async def make_symbols(self, missing: MissingSymbols) -> None:
        self.calls.append(("symbols", missing))
        if self.symbols_error is not None:
            raise self.symbols_error

    async def delete_memory_dump(self, task_id: int) -> None:
        self.calls.append(("delete", task_id))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def prepared(imports: Path, *, upload: bytes | None = UPLOAD) -> int:
    stored = import_file(imports, ANALYSIS_ID)
    if upload is not None:
        stored.parent.mkdir(parents=True)
        stored.write_bytes(upload)
    return ANALYSIS_ID


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    return tmp_path / "cape-storage"


@pytest.fixture
def imports(tmp_path: Path) -> Path:
    return tmp_path / "imports"


@pytest.fixture
def index() -> FakeIndex:
    return FakeIndex()


def importing(
    storage: Path, imports: Path, index: FakeIndex, *answers: Answer
) -> tuple[MemoryImport, FakeImageControl]:
    control = FakeImageControl(storage, list(answers))
    return MemoryImport(control, ReportIngester(index), storage, imports), control


async def test_an_image_is_scanned_by_name_under_the_imports_folder(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    step, control = importing(storage, imports, index, SCANNED)

    await step.run(prepared(imports), STARTED_AT)

    assert control.calls == [("analyse", (image_task_id(ANALYSIS_ID), f"{ANALYSIS_ID}/upload"))]


async def test_the_injected_process_of_the_image_is_a_memory_detection(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    step, _ = importing(storage, imports, index, SCANNED)

    imported = await step.run(prepared(imports), STARTED_AT)

    injected = [
        event
        for event in index.events
        if event["event"]["kind"] == "alert" and event["process"]["pid"] == P9_INJECTED_PID
    ]
    assert [(alert["process"]["name"], alert["event"]["severity"]) for alert in injected] == [
        ("PING.EXE", 3)
    ]
    assert imported.indexed.lane_counts == {"memory": 26}


async def test_the_memory_summary_reads_the_scan_as_a_runs_does(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    step, _ = importing(storage, imports, index, SCANNED)

    imported = await step.run(prepared(imports), STARTED_AT)

    memory = imported.memory
    assert (memory.dump_taken, memory.findings, memory.error) == (True, MemoryFindings.OK, None)
    assert (memory.dump_bytes, memory.dump_deleted) == (len(UPLOAD), None)


async def test_the_uploaded_image_stays_after_the_analysis(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    step, control = importing(storage, imports, index, SCANNED)

    await step.run(prepared(imports), STARTED_AT)

    assert import_file(imports, ANALYSIS_ID).read_bytes() == UPLOAD
    assert "delete" not in control.names()


async def test_missing_symbols_are_made_once_and_the_image_scanned_again(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    unresolved = MemoryAnalysis(
        plugins={"windows.pslist": 0},
        seconds=0.3,
        pids=[],
        errors={"windows.pslist": NO_SYMBOLS},
        missing_symbols=NEEDED,
    )
    step, control = importing(storage, imports, index, unresolved, SCANNED)

    imported = await step.run(prepared(imports), STARTED_AT)

    assert control.calls[1] == ("symbols", NEEDED)
    assert control.names() == ["analyse", "symbols", "analyse"]
    assert imported.memory.findings is MemoryFindings.OK
    assert imported.indexed.event_count == 26


async def test_symbols_that_are_still_missing_after_making_them_fail_the_import(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    unresolved = MemoryAnalysis(
        plugins={"windows.pslist": 0},
        seconds=0.3,
        pids=[],
        errors={"windows.pslist": NO_SYMBOLS},
        missing_symbols=NEEDED,
    )
    step, control = importing(storage, imports, index, unresolved, unresolved)

    with pytest.raises(MemoryImportFailedError, match=NO_SYMBOLS):
        await step.run(prepared(imports), STARTED_AT)

    assert control.names() == ["analyse", "symbols", "analyse"]
    assert index.events == []


async def test_symbols_the_service_cannot_fetch_fail_the_import_with_its_reason(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    unresolved = MemoryAnalysis(
        plugins={},
        seconds=0.3,
        pids=[],
        errors={"windows.info": NO_SYMBOLS},
        missing_symbols=NEEDED,
    )
    step, control = importing(storage, imports, index, unresolved)
    control.symbols_error = GuestControlRejected(
        "make_symbols", 502, "the symbol server could not be reached"
    )

    with pytest.raises(MemoryImportFailedError) as failure:
        await step.run(prepared(imports), STARTED_AT)

    assert "the symbol server could not be reached" in str(failure.value)
    assert NEEDED.guid in str(failure.value)
    assert control.names() == ["analyse", "symbols"]


async def test_a_file_that_is_not_a_memory_image_fails_the_import_saying_so_once(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    plugins = ["windows.pslist", "windows.cmdline", "windows.malware.malfind"]
    garbage = MemoryAnalysis(
        plugins=dict.fromkeys(plugins, 0),
        seconds=0.2,
        pids=[],
        errors=dict.fromkeys(plugins, NOT_A_MEMORY_IMAGE),
    )
    step, _ = importing(storage, imports, index, garbage)

    with pytest.raises(MemoryImportFailedError) as failure:
        await step.run(prepared(imports), STARTED_AT)

    assert str(failure.value) == NOT_A_MEMORY_IMAGE
    assert index.events == []


async def test_an_unreachable_control_service_fails_the_import_with_the_reason(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    down = GuestControlUnreachable("analyse_memory", "ConnectError")
    step, _ = importing(storage, imports, index, down)

    with pytest.raises(MemoryImportFailedError) as failure:
        await step.run(prepared(imports), STARTED_AT)

    assert "unreachable (ConnectError)" in str(failure.value)


async def test_a_refusal_of_the_control_service_fails_the_import_with_its_message(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    refused = GuestControlRejected("analyse_memory", 404, "no such image under /imports")
    step, _ = importing(storage, imports, index, refused)

    with pytest.raises(MemoryImportFailedError, match="no such image under /imports"):
        await step.run(prepared(imports), STARTED_AT)


async def test_a_missing_upload_fails_the_import_before_the_service_hears_of_it(
    storage: Path, imports: Path, index: FakeIndex
) -> None:
    step, control = importing(storage, imports, index, SCANNED)

    with pytest.raises(MemoryImportFailedError, match="uploaded file is missing"):
        await step.run(prepared(imports, upload=None), STARTED_AT)

    assert control.calls == []
