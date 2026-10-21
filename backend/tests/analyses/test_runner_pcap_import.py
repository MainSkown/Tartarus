import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import ReportOutcome
from app.analyses.runner import Runner, RunnerConfig
from app.cape.errors import CapeRejected, CapeUnreachable
from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisKind, AnalysisPhase, AnalysisStatus
from app.imports.upload import import_file
from tests.analyses.conftest import CAPE_STORAGE, GRACE_SECONDS
from tests.analyses.fakes import FakeCape, FakeIngester, FakeReports
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.analyses.helpers import adopt_by_cape, enqueue, load
from tests.test_analysis_repository import SHA_B, make_sample

type Factory = async_sessionmaker[AsyncSession]

FIXTURES = Path(__file__).resolve().parents[3] / "docs" / "plans" / "m9-spikes" / "fixtures"
FIXTURE_PCAP = FIXTURES / "p9-run-370-dump.pcap"
FIRST_PACKET = datetime(2026, 10, 21, 12, 52, 52, 871033, tzinfo=UTC)
OUTCOME = ReportOutcome(score=0.0, max_severity=None, detected_families=[], summary={})
IMPORT_OPTIONS = {"import": {"kind": "pcap", "filename": "dump.pcap", "size": 316427}}


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


async def queue_pcap_import(
    session_factory: Factory, imports_dir: Path, capture: Path | None = FIXTURE_PCAP
) -> int:
    async with session_factory() as session:
        await repository.add_sample_if_new(session, make_sample(SHA_B))
        created = await repository.create_analysis(
            session,
            sample_sha256=SHA_B,
            filename="dump.pcap",
            options=IMPORT_OPTIONS,
            kind=AnalysisKind.IMPORTED,
        )
    if capture is not None:
        stored = import_file(imports_dir, created.id)
        stored.parent.mkdir(parents=True)
        shutil.copy(capture, stored)
    return created.id


async def test_a_queued_pcap_goes_to_cape_as_a_pcap_task_with_its_first_packet_as_start(
    runner: Runner, session_factory: Factory, cape: FakeCape, imports_dir: Path
) -> None:
    analysis_id = await queue_pcap_import(session_factory, imports_dir)

    await runner.run_once()

    submitted = await load(session_factory, analysis_id)
    assert submitted.status is AnalysisStatus.STARTING
    assert submitted.cape_task_id == 100
    assert submitted.started_at is not None
    assert submitted.started_at.replace(tzinfo=UTC) == FIRST_PACKET
    assert cape.created == []
    assert [(task["task_id"], task["filename"]) for task in cape.pcap_tasks] == [(100, "dump.pcap")]
    assert cape.pcap_tasks[0]["bytes"] == FIXTURE_PCAP.read_bytes()


async def test_a_pcap_import_ends_done_and_is_ingested_from_its_first_packet(  # noqa: PLR0913, PLR0917 - the runner's fakes
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
    imports_dir: Path,
) -> None:
    reports.outcome = OUTCOME
    cape.script_for_new_tasks = ["pending", "running", "reported"]
    analysis_id = await queue_pcap_import(session_factory, imports_dir)

    for _ in range(5):
        await runner.run_once()

    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert done.phase is AnalysisPhase.FINAL
    assert ingester.requests == [
        (analysis_id, CAPE_STORAGE / "analyses" / "100" / "reports" / "report.json")
    ]
    assert ingester.started_at[analysis_id] == FIRST_PACKET
    assert ("view", 100) not in cape.calls


async def test_an_import_neither_looks_up_a_guest_nor_waits_for_one(  # noqa: PLR0913, PLR0917 - the runner's fakes
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
    imports_dir: Path,
) -> None:
    reports.outcome = OUTCOME
    cape.script_for_new_tasks = ["reported"]
    guests.guests_listed = []
    analysis_id = await queue_pcap_import(session_factory, imports_dir)

    await runner.run_once()
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    assert guests.calls == []


async def test_an_import_is_submitted_while_a_run_is_being_followed(
    runner: Runner, session_factory: Factory, cape: FakeCape, imports_dir: Path
) -> None:
    cape.scripts[7] = ["running"]
    run_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING)
    import_id = await queue_pcap_import(session_factory, imports_dir)

    await runner.run_once()

    assert (await load(session_factory, import_id)).status is AnalysisStatus.STARTING
    assert (await load(session_factory, run_id)).status is AnalysisStatus.RUNNING
    assert ("status", 7) in cape.calls


async def test_a_queued_run_is_submitted_while_an_import_is_being_followed(
    runner: Runner, session_factory: Factory, cape: FakeCape, imports_dir: Path
) -> None:
    import_id = await queue_pcap_import(session_factory, imports_dir)
    await runner.run_once()
    run_id = await enqueue(session_factory)

    await runner.run_once()

    assert (await load(session_factory, run_id)).status is AnalysisStatus.STARTING
    assert (await load(session_factory, import_id)).cape_task_id == 100
    assert [created["task_id"] for created in cape.created] == [101]


async def test_a_run_queued_before_an_import_is_not_held_back_by_it(
    runner: Runner, session_factory: Factory, cape: FakeCape, imports_dir: Path
) -> None:
    run_id = await enqueue(session_factory)
    import_id = await queue_pcap_import(session_factory, imports_dir)

    await runner.run_once()

    assert (await load(session_factory, run_id)).status is AnalysisStatus.STARTING
    assert (await load(session_factory, import_id)).status is AnalysisStatus.STARTING


async def test_cape_refusing_the_capture_fails_the_import_with_its_reason(
    runner: Runner, session_factory: Factory, cape: FakeCape, imports_dir: Path
) -> None:
    cape.create_errors = [
        CapeRejected("tasks/create/file", "Uploaded file exceeds the maximum allowed size")
    ]
    analysis_id = await queue_pcap_import(session_factory, imports_dir)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == "CAPE refused the task: Uploaded file exceeds the maximum allowed size"


async def test_an_unreachable_cape_puts_the_import_back_in_the_queue(
    runner: Runner, session_factory: Factory, cape: FakeCape, imports_dir: Path
) -> None:
    cape.create_errors = [CapeUnreachable("tasks/create/file", "ConnectError")]
    analysis_id = await queue_pcap_import(session_factory, imports_dir)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.QUEUED


async def test_a_missing_upload_fails_the_import_and_says_so(
    runner: Runner, session_factory: Factory, cape: FakeCape, imports_dir: Path
) -> None:
    analysis_id = await queue_pcap_import(session_factory, imports_dir, capture=None)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "uploaded file is missing" in failed.error
    assert cape.pcap_tasks == []


async def test_an_upload_without_packets_fails_the_import_before_cape_hears_of_it(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    imports_dir: Path,
    tmp_path: Path,
) -> None:
    header_only = tmp_path / "empty.pcap"
    header_only.write_bytes(FIXTURE_PCAP.read_bytes()[:24])
    analysis_id = await queue_pcap_import(session_factory, imports_dir, header_only)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == "The capture holds no packets"
    assert cape.pcap_tasks == []


async def test_an_import_of_a_kind_without_a_runner_path_fails_naming_the_kind(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    async with session_factory() as session:
        await repository.add_sample_if_new(session, make_sample(SHA_B))
        image = await repository.create_analysis(
            session,
            sample_sha256=SHA_B,
            filename="mem.raw",
            options={"import": {"kind": "memory_image", "filename": "mem.raw", "size": 1}},
            kind=AnalysisKind.IMPORTED,
        )

    await runner.run_once()

    assert cape.pcap_tasks == []
    failed = await load(session_factory, image.id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == "Importing a memory_image is not supported"
