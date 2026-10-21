import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.memory import MemoryFindings, MemorySummary
from app.analyses.memory_import import image_task_id
from app.analyses.ports import IngestFailedError, IngestResult
from app.analyses.runner import Runner, RunnerConfig
from app.db import analysis_repository as repository
from app.db.base import utc_now
from app.db.models.analysis import AnalysisKind, AnalysisPhase, AnalysisStatus, Severity
from app.guest.errors import GuestControlUnreachable
from app.guest.schemas import MemoryAnalysis, MissingSymbols
from app.imports.upload import import_file
from tests.analyses.conftest import CAPE_STORAGE, GRACE_SECONDS
from tests.analyses.fakes import FakeCape, FakeIngester
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.analyses.helpers import as_utc, enqueue, load
from tests.test_analysis_repository import SHA_B, make_sample

type Factory = async_sessionmaker[AsyncSession]

IMAGE_OPTIONS = {"import": {"kind": "memory_image", "filename": "memory.raw", "size": 2004}}
UPLOAD = b"\x7fELF" + bytes(2000)
INDEXED = IngestResult(event_count=26, lane_counts={"memory": 26})
NEEDED = MissingSymbols(guid="24DE61DB3A27C5B383DFF181CB51F7E1", age=1)
NO_SYMBOLS = "no symbols for this Windows build"
UNRESOLVED = MemoryAnalysis(
    plugins={"windows.pslist": 0},
    seconds=0.3,
    pids=[],
    errors={"windows.pslist": NO_SYMBOLS},
    missing_symbols=NEEDED,
)
SCANNED = MemoryAnalysis(plugins={"windows.pslist": 147}, seconds=66.0, pids=[])


@pytest.fixture
def imports_dir(tmp_path: Path) -> Path:
    return tmp_path / "imports"


@pytest.fixture
def config(imports_dir: Path) -> RunnerConfig:
    return RunnerConfig(
        cape_storage_path=CAPE_STORAGE,
        poll_interval=3600.0,
        unreachable_grace=GRACE_SECONDS,
        imports_dir=imports_dir,
    )


async def queue_image_import(
    session_factory: Factory, imports_dir: Path, *, upload: bytes | None = UPLOAD
) -> int:
    async with session_factory() as session:
        await repository.add_sample_if_new(session, make_sample(SHA_B))
        created = await repository.create_analysis(
            session,
            sample_sha256=SHA_B,
            filename="memory.raw",
            options=IMAGE_OPTIONS,
            kind=AnalysisKind.IMPORTED,
        )
    if upload is not None:
        stored = import_file(imports_dir, created.id)
        stored.parent.mkdir(parents=True)
        stored.write_bytes(upload)
    return created.id


async def imported(
    runner: Runner, session_factory: Factory, imports_dir: Path, **upload: bytes | None
) -> int:
    analysis_id = await queue_image_import(session_factory, imports_dir, **upload)
    await runner.run_once()
    await runner.wait_for_memory_imports()
    return analysis_id


async def test_an_imported_image_ends_done_with_its_events_and_its_memory_summary(
    runner: Runner,
    session_factory: Factory,
    ingester: FakeIngester,
    imports_dir: Path,
) -> None:
    ingester.result = INDEXED

    analysis_id = await imported(runner, session_factory, imports_dir)

    done = await load(session_factory, analysis_id)
    assert (done.status, done.phase) == (AnalysisStatus.DONE, AnalysisPhase.FINAL)
    assert done.event_count == 26
    assert done.started_at is not None
    assert done.summary is not None
    assert done.summary["lane_counts"] == {"memory": 26}
    assert MemorySummary.model_validate(done.summary["memory"]) == MemorySummary(
        dump_taken=True, findings=MemoryFindings.OK, dump_bytes=len(UPLOAD)
    )
    assert ingester.image_requests == [
        (
            analysis_id,
            CAPE_STORAGE / "analyses" / str(image_task_id(analysis_id)),
            as_utc(done.started_at),
        )
    ]


async def test_the_most_severe_finding_of_an_image_is_the_analysis_max_severity(
    runner: Runner,
    session_factory: Factory,
    ingester: FakeIngester,
    imports_dir: Path,
) -> None:
    ingester.result = IngestResult(
        event_count=26, lane_counts={"memory": 26}, max_alert_severity=Severity.HIGH
    )

    analysis_id = await imported(runner, session_factory, imports_dir)

    assert (await load(session_factory, analysis_id)).max_severity is Severity.HIGH


async def test_an_imported_image_needs_neither_a_guest_nor_a_cape_task(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    imports_dir: Path,
) -> None:
    analysis_id = await imported(runner, session_factory, imports_dir)

    assert (await load(session_factory, analysis_id)).cape_task_id is None
    assert cape.calls == []
    assert [name for name, _ in guests.calls] == ["analyse_memory"]
    assert guests.images_asked == [f"{analysis_id}/upload"]


async def test_the_uploaded_image_is_kept_once_the_analysis_is_done(
    runner: Runner, session_factory: Factory, imports_dir: Path, guests: ScriptedGuestControl
) -> None:
    analysis_id = await imported(runner, session_factory, imports_dir)

    assert import_file(imports_dir, analysis_id).read_bytes() == UPLOAD
    assert "delete_memory_dump" not in [name for name, _ in guests.calls]


async def test_missing_symbols_are_made_and_the_image_scanned_a_second_time(
    runner: Runner, session_factory: Factory, imports_dir: Path, guests: ScriptedGuestControl
) -> None:
    guests.memory_script = [UNRESOLVED, SCANNED]

    analysis_id = await imported(runner, session_factory, imports_dir)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    assert guests.symbols_made == [NEEDED]
    assert [name for name, _ in guests.calls] == [
        "analyse_memory",
        "make_symbols",
        "analyse_memory",
    ]


async def test_an_image_that_is_not_a_memory_image_fails_the_analysis_with_the_reason(
    runner: Runner, session_factory: Factory, imports_dir: Path, guests: ScriptedGuestControl
) -> None:
    reason = "not a memory image: volatility found no Windows kernel in the file"
    guests.memory_analysis = MemoryAnalysis(
        plugins={"windows.pslist": 0}, seconds=0.2, pids=[], errors={"windows.pslist": reason}
    )

    analysis_id = await imported(runner, session_factory, imports_dir)

    failed = await load(session_factory, analysis_id)
    assert (failed.status, failed.error) == (AnalysisStatus.FAILED, reason)
    assert failed.finished_at is not None


async def test_a_control_service_that_is_down_fails_the_analysis_with_the_reason(
    runner: Runner, session_factory: Factory, imports_dir: Path, guests: ScriptedGuestControl
) -> None:
    guests.memory_analysis = GuestControlUnreachable("analyse_memory", "ConnectError")

    analysis_id = await imported(runner, session_factory, imports_dir)

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "unreachable (ConnectError)" in failed.error


async def test_a_missing_upload_fails_the_analysis_and_says_so(
    runner: Runner, session_factory: Factory, imports_dir: Path, guests: ScriptedGuestControl
) -> None:
    analysis_id = await imported(runner, session_factory, imports_dir, upload=None)

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "uploaded file is missing" in failed.error
    assert guests.calls == []


async def test_events_that_cannot_be_indexed_end_the_analysis_as_report_failed(
    runner: Runner, session_factory: Factory, ingester: FakeIngester, imports_dir: Path
) -> None:
    ingester.result = IngestFailedError("Indexing the events failed: cluster is red")

    analysis_id = await imported(runner, session_factory, imports_dir)

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.REPORT_FAILED
    assert failed.error == "Indexing the events failed: cluster is red"
    assert failed.event_count == 0


async def test_a_run_is_submitted_while_an_image_is_being_analysed(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    imports_dir: Path,
) -> None:
    guests.memory_gate = asyncio.Event()
    image_id = await queue_image_import(session_factory, imports_dir)
    await runner.run_once()
    run_id = await enqueue(session_factory)

    await runner.run_once()

    assert (await load(session_factory, image_id)).status is AnalysisStatus.RUNNING
    assert (await load(session_factory, run_id)).status is AnalysisStatus.STARTING
    guests.memory_gate.set()
    await runner.wait_for_memory_imports()
    assert (await load(session_factory, image_id)).status is AnalysisStatus.DONE


async def test_an_image_is_scanned_once_however_often_the_runner_ticks(
    runner: Runner, session_factory: Factory, guests: ScriptedGuestControl, imports_dir: Path
) -> None:
    guests.memory_gate = asyncio.Event()
    await queue_image_import(session_factory, imports_dir)

    for _ in range(3):
        await runner.run_once()
    guests.memory_gate.set()
    await runner.wait_for_memory_imports()

    assert guests.images_asked == [guests.images_asked[0]]


async def test_a_restarted_runner_scans_the_image_the_dead_one_left_running(
    make_runner: Callable[[], Runner],
    session_factory: Factory,
    guests: ScriptedGuestControl,
    imports_dir: Path,
) -> None:
    analysis_id = await queue_image_import(session_factory, imports_dir)
    async with session_factory() as session:
        await repository.update_analysis(
            session, analysis_id, status=AnalysisStatus.RUNNING, started_at=utc_now()
        )
    survivor = make_runner()

    await survivor.run_once()
    await survivor.wait_for_memory_imports()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    assert guests.images_asked == [f"{analysis_id}/upload"]


async def test_stopping_the_runner_leaves_a_running_image_to_the_next_runner(
    runner: Runner, session_factory: Factory, guests: ScriptedGuestControl, imports_dir: Path
) -> None:
    guests.memory_gate = asyncio.Event()
    analysis_id = await queue_image_import(session_factory, imports_dir)
    await runner.run_once()

    await runner.stop()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.RUNNING
