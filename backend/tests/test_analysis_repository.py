from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import analysis_repository as repository
from app.db.analysis_repository import AnalysisFilter
from app.db.base import Base
from app.db.models import Analysis, Sample
from app.db.models.analysis import AnalysisPhase, AnalysisStatus, Severity
from app.schemas.analysis import AnalysisRead

SHA_A = "a" * 64
SHA_B = "b" * 64
OPTIONS: dict[str, Any] = {"route": "inetsim", "timeout": 180, "package": "auto"}


def _enable_foreign_keys(dbapi_connection: Any, _record: object) -> None:
    # SQLite skips foreign keys unless each connection enables them; Postgres always enforces them.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'analysis.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db_session:
        yield db_session
    await engine.dispose()


def make_sample(sha256: str = SHA_A, original_name: str = "benign.exe") -> Sample:
    return Sample(
        sha256=sha256,
        sha1="c" * 40,
        md5="d" * 32,
        size=2048,
        original_name=original_name,
        stored_path=f"/data/samples/{sha256}.zip",
    )


async def seeded_analysis(
    session: AsyncSession, filename: str = "benign.exe", sha256: str = SHA_A
) -> Analysis:
    await repository.add_sample_if_new(session, make_sample(sha256))
    return await repository.create_analysis(
        session, sample_sha256=sha256, filename=filename, options=OPTIONS
    )


async def test_a_new_sample_is_stored_and_can_be_read_back(session: AsyncSession) -> None:
    stored = await repository.add_sample_if_new(session, make_sample())

    fetched = await repository.get_sample(session, SHA_A)

    assert stored.sha256 == SHA_A
    assert fetched is not None
    assert (fetched.sha1, fetched.md5, fetched.size) == ("c" * 40, "d" * 32, 2048)
    assert fetched.original_name == "benign.exe"
    assert fetched.file_type is None
    assert fetched.first_seen is not None


async def test_adding_a_known_sample_again_keeps_the_first_row(session: AsyncSession) -> None:
    await repository.add_sample_if_new(session, make_sample(original_name="first.exe"))

    returned = await repository.add_sample_if_new(session, make_sample(original_name="second.exe"))
    stored = await repository.get_sample(session, SHA_A)

    assert returned.original_name == "first.exe"
    assert stored is not None
    assert stored.original_name == "first.exe"


async def test_get_sample_returns_none_for_an_unknown_hash(session: AsyncSession) -> None:
    assert await repository.get_sample(session, SHA_B) is None


async def test_a_new_analysis_is_queued_live_with_its_options(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)

    assert analysis.id is not None
    assert analysis.sample_sha256 == SHA_A
    assert analysis.filename == "benign.exe"
    assert analysis.status is AnalysisStatus.QUEUED
    assert analysis.phase is AnalysisPhase.LIVE
    assert analysis.options == OPTIONS
    assert analysis.submitted_at is not None
    assert analysis.cape_task_id is None
    assert analysis.summary is None
    assert analysis.detected_families == []
    assert (analysis.event_count, analysis.disk_bytes) == (0, 0)


async def test_an_analysis_of_an_unknown_sample_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await repository.create_analysis(
            session, sample_sha256=SHA_B, filename="ghost.exe", options=OPTIONS
        )


async def test_get_analysis_returns_the_row_or_none(session: AsyncSession) -> None:
    created = await seeded_analysis(session)

    fetched = await repository.get_analysis(session, created.id)

    assert fetched is not None
    assert fetched.filename == "benign.exe"
    assert await repository.get_analysis(session, created.id + 1000) is None


async def test_list_returns_newest_first(session: AsyncSession) -> None:
    first = await seeded_analysis(session, "one.exe")
    second = await seeded_analysis(session, "two.exe")
    third = await seeded_analysis(session, "three.exe")

    listed = await repository.list_analyses(session)

    assert [row.id for row in listed] == [third.id, second.id, first.id]


async def test_list_matches_q_against_filename_and_hash_case_insensitively(
    session: AsyncSession,
) -> None:
    by_name = await seeded_analysis(session, "Invoice_2026.EXE", sha256=SHA_A)
    by_hash = await seeded_analysis(session, "other.exe", sha256=SHA_B)
    await seeded_analysis(session, "unrelated.exe", sha256="e" * 64)

    by_name_hits = await repository.list_analyses(session, AnalysisFilter(q="invoice"))
    by_hash_hits = await repository.list_analyses(session, AnalysisFilter(q="bbbb"))

    assert [row.id for row in by_name_hits] == [by_name.id]
    assert [row.id for row in by_hash_hits] == [by_hash.id]


async def test_q_treats_wildcard_characters_literally(session: AsyncSession) -> None:
    await seeded_analysis(session, "plain.exe")

    assert await repository.list_analyses(session, AnalysisFilter(q="%")) == []


async def test_list_filters_by_status(session: AsyncSession) -> None:
    queued = await seeded_analysis(session, "queued.exe")
    done = await seeded_analysis(session, "done.exe")
    await repository.update_analysis(session, done.id, status=AnalysisStatus.DONE)

    listed = await repository.list_analyses(session, AnalysisFilter(status=AnalysisStatus.DONE))

    assert [row.id for row in listed] == [done.id]
    assert queued.id not in {row.id for row in listed}


async def test_list_pages_with_limit_and_offset(session: AsyncSession) -> None:
    created = [await seeded_analysis(session, f"run-{index}.exe") for index in range(5)]
    newest_first = [row.id for row in reversed(created)]

    page = await repository.list_analyses(session, limit=2, offset=1)

    assert [row.id for row in page] == newest_first[1:3]


async def test_count_respects_the_same_filters_as_list(session: AsyncSession) -> None:
    await seeded_analysis(session, "invoice.exe", sha256=SHA_A)
    await seeded_analysis(session, "other.exe", sha256=SHA_B)

    assert await repository.count_analyses(session) == 2
    assert await repository.count_analyses(session, AnalysisFilter(q="invoice")) == 1
    assert await repository.count_analyses(session, AnalysisFilter(status=AnalysisStatus.DONE)) == 0


async def test_update_persists_every_mutable_field(session: AsyncSession) -> None:
    created = await seeded_analysis(session)
    summary = {"signatures": [{"name": "persistence", "severity": 3}]}

    await repository.update_analysis(
        session,
        created.id,
        status=AnalysisStatus.DONE,
        phase=AnalysisPhase.FINAL,
        cape_task_id=42,
        error=None,
        summary=summary,
        score=7.5,
        max_severity=Severity.HIGH,
        detected_families=["emotet"],
        event_count=1200,
        disk_bytes=4096,
    )
    session.expunge_all()
    reloaded = await repository.get_analysis(session, created.id)

    assert reloaded is not None
    assert reloaded.status is AnalysisStatus.DONE
    assert reloaded.phase is AnalysisPhase.FINAL
    assert reloaded.cape_task_id == 42
    assert reloaded.summary == summary
    assert reloaded.score == 7.5
    assert reloaded.max_severity is Severity.HIGH
    assert reloaded.detected_families == ["emotet"]
    assert (reloaded.event_count, reloaded.disk_bytes) == (1200, 4096)


async def test_update_records_failure_message_and_timestamps(session: AsyncSession) -> None:
    created = await seeded_analysis(session)

    await repository.update_analysis(
        session, created.id, status=AnalysisStatus.FAILED, error="CAPE went away"
    )
    session.expunge_all()
    reloaded = await repository.get_analysis(session, created.id)

    assert reloaded is not None
    assert reloaded.status is AnalysisStatus.FAILED
    assert reloaded.error == "CAPE went away"


async def test_update_rejects_a_misspelled_field_instead_of_ignoring_it(
    session: AsyncSession,
) -> None:
    created = await seeded_analysis(session)

    with pytest.raises(TypeError, match="statuss"):
        await repository.update_analysis(session, created.id, **{"statuss": AnalysisStatus.DONE})


async def test_update_of_an_unknown_analysis_returns_none(session: AsyncSession) -> None:
    assert await repository.update_analysis(session, 999, status=AnalysisStatus.DONE) is None


async def test_deleting_an_analysis_removes_only_its_row(session: AsyncSession) -> None:
    created = await seeded_analysis(session)

    deleted = await repository.delete_analysis(session, created.id)

    assert deleted is True
    assert await repository.get_analysis(session, created.id) is None
    assert await repository.get_sample(session, SHA_A) is not None


async def test_deleting_an_unknown_analysis_reports_false(session: AsyncSession) -> None:
    assert await repository.delete_analysis(session, 999) is False


async def test_deleting_an_analysis_keeps_the_sample_other_analyses_share(
    session: AsyncSession,
) -> None:
    first = await seeded_analysis(session, "one.exe")
    await repository.create_analysis(
        session, sample_sha256=SHA_A, filename="two.exe", options=OPTIONS
    )

    await repository.delete_analysis(session, first.id)

    assert await repository.count_analyses(session) == 1
    assert await repository.get_sample(session, SHA_A) is not None


async def test_a_sample_referenced_by_an_analysis_is_not_deleted(session: AsyncSession) -> None:
    await seeded_analysis(session)

    deleted = await repository.delete_sample_if_unreferenced(session, SHA_A)

    assert deleted is False
    assert await repository.get_sample(session, SHA_A) is not None


async def test_the_database_refuses_to_delete_a_sample_an_analysis_still_references(
    session: AsyncSession,
) -> None:
    await seeded_analysis(session)

    with pytest.raises(IntegrityError):
        await session.execute(text("DELETE FROM sample"))


async def test_an_unreferenced_sample_is_deleted(session: AsyncSession) -> None:
    created = await seeded_analysis(session)
    await repository.delete_analysis(session, created.id)

    deleted = await repository.delete_sample_if_unreferenced(session, SHA_A)

    assert deleted is True
    assert await repository.get_sample(session, SHA_A) is None


async def test_deleting_an_unknown_sample_reports_false(session: AsyncSession) -> None:
    assert await repository.delete_sample_if_unreferenced(session, SHA_B) is False


@pytest.mark.parametrize(
    "active",
    [
        AnalysisStatus.STARTING,
        AnalysisStatus.RUNNING,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.INGESTING,
    ],
)
async def test_the_active_analysis_is_found_in_every_active_state(
    session: AsyncSession, active: AnalysisStatus
) -> None:
    created = await seeded_analysis(session)
    await repository.update_analysis(session, created.id, status=active)

    found = await repository.get_active_analysis(session)

    assert found is not None
    assert found.id == created.id


@pytest.mark.parametrize(
    "inactive",
    [
        AnalysisStatus.QUEUED,
        AnalysisStatus.DONE,
        AnalysisStatus.FAILED,
        AnalysisStatus.REPORT_FAILED,
        AnalysisStatus.CANCELLED,
    ],
)
async def test_no_analysis_is_active_when_none_is_in_an_active_state(
    session: AsyncSession, inactive: AnalysisStatus
) -> None:
    created = await seeded_analysis(session)
    await repository.update_analysis(session, created.id, status=inactive)

    assert await repository.get_active_analysis(session) is None


async def test_the_oldest_queued_analysis_is_returned_first(session: AsyncSession) -> None:
    first = await seeded_analysis(session, "first.exe")
    await seeded_analysis(session, "second.exe")

    oldest = await repository.get_oldest_queued_analysis(session)

    assert oldest is not None
    assert oldest.id == first.id


async def test_running_analyses_are_skipped_when_looking_for_the_next_queued_one(
    session: AsyncSession,
) -> None:
    first = await seeded_analysis(session, "first.exe")
    second = await seeded_analysis(session, "second.exe")
    await repository.update_analysis(session, first.id, status=AnalysisStatus.RUNNING)

    oldest = await repository.get_oldest_queued_analysis(session)

    assert oldest is not None
    assert oldest.id == second.id


async def test_no_queued_analysis_when_the_queue_is_empty(session: AsyncSession) -> None:
    assert await repository.get_oldest_queued_analysis(session) is None


async def queue_of_three_with_a_running_and_a_done_one(
    session: AsyncSession,
) -> tuple[list[Analysis], Analysis, Analysis]:
    queued = [await seeded_analysis(session, f"queued{n}.exe") for n in range(3)]
    running = await seeded_analysis(session, "running.exe")
    done = await seeded_analysis(session, "done.exe")
    await repository.update_analysis(session, running.id, status=AnalysisStatus.RUNNING)
    await repository.update_analysis(session, done.id, status=AnalysisStatus.DONE)
    return queued, running, done


async def test_queued_analyses_are_numbered_from_one_in_the_order_the_runner_serves_them(
    session: AsyncSession,
) -> None:
    queued, running, done = await queue_of_three_with_a_running_and_a_done_one(session)

    positions = await repository.queue_positions(
        session, [done.id, queued[2].id, running.id, queued[0].id, queued[1].id]
    )

    assert positions == {queued[0].id: 1, queued[1].id: 2, queued[2].id: 3}


async def test_a_position_counts_queued_analyses_outside_the_requested_ids(
    session: AsyncSession,
) -> None:
    queued, _, _ = await queue_of_three_with_a_running_and_a_done_one(session)

    assert await repository.queue_positions(session, [queued[2].id]) == {queued[2].id: 3}


async def test_no_ids_means_no_positions_and_no_query(session: AsyncSession) -> None:
    await seeded_analysis(session)

    assert await repository.queue_positions(session, []) == {}


async def test_a_position_moves_up_when_an_earlier_queued_analysis_is_cancelled(
    session: AsyncSession,
) -> None:
    queued, _, _ = await queue_of_three_with_a_running_and_a_done_one(session)

    await repository.cancel_if_queued(session, queued[0].id)
    positions = await repository.queue_positions(session, [row.id for row in queued])

    assert positions == {queued[1].id: 1, queued[2].id: 2}


async def test_positions_for_a_whole_page_cost_one_statement(session: AsyncSession) -> None:
    queued, _, _ = await queue_of_three_with_a_running_and_a_done_one(session)
    statements: list[str] = []
    engine = session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    await repository.queue_positions(session, [row.id for row in queued])

    assert len(statements) == 1


async def test_the_analysis_at_position_one_is_the_one_the_runner_takes_next(
    session: AsyncSession,
) -> None:
    queued, _, _ = await queue_of_three_with_a_running_and_a_done_one(session)
    same_moment = datetime(2026, 10, 13, tzinfo=UTC)
    await session.execute(update(Analysis).values(submitted_at=same_moment))
    await session.commit()

    positions = await repository.queue_positions(session, [row.id for row in queued])
    next_up = await repository.get_oldest_queued_analysis(session)

    assert next_up is not None
    assert positions[next_up.id] == 1


async def test_status_is_stored_as_its_plain_value(session: AsyncSession) -> None:
    await seeded_analysis(session)

    stored = await session.scalar(text("SELECT status FROM analysis"))

    assert stored == "queued"


async def test_a_status_outside_the_allowed_set_is_rejected_by_the_database(
    session: AsyncSession,
) -> None:
    await seeded_analysis(session)

    with pytest.raises(IntegrityError):
        await session.execute(text("UPDATE analysis SET status = 'bogus'"))


async def test_a_phase_outside_the_allowed_set_is_rejected_by_the_database(
    session: AsyncSession,
) -> None:
    await seeded_analysis(session)

    with pytest.raises(IntegrityError):
        await session.execute(text("UPDATE analysis SET phase = 'bogus'"))


async def test_a_severity_outside_the_allowed_set_is_rejected_by_the_database(
    session: AsyncSession,
) -> None:
    await seeded_analysis(session)

    with pytest.raises(IntegrityError):
        await session.execute(text("UPDATE analysis SET max_severity = 'bogus'"))


def test_analysis_read_is_built_from_an_orm_row() -> None:
    analysis = Analysis(
        id=7,
        sample_sha256=SHA_A,
        filename="benign.exe",
        status=AnalysisStatus.RUNNING,
        phase=AnalysisPhase.LIVE,
        options=OPTIONS,
        detected_families=[],
        event_count=0,
        disk_bytes=0,
        submitted_at=datetime(2026, 10, 13, tzinfo=UTC),
    )

    read = AnalysisRead.model_validate(analysis)

    assert read.id == 7
    assert read.status is AnalysisStatus.RUNNING
    assert read.summary is None


async def test_claiming_a_queued_analysis_moves_it_to_starting_exactly_once(
    session: AsyncSession,
) -> None:
    analysis = await seeded_analysis(session)

    first = await repository.claim_queued(session, analysis.id)
    second = await repository.claim_queued(session, analysis.id)

    await session.refresh(analysis)
    stored: Analysis | None = analysis
    assert (first, second) == (True, False)
    assert stored is not None
    assert stored.status is AnalysisStatus.STARTING


async def test_a_cancelled_analysis_can_no_longer_be_claimed(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    await repository.cancel_if_queued(session, analysis.id)

    assert await repository.claim_queued(session, analysis.id) is False


async def test_cancelling_a_queued_analysis_ends_it_as_cancelled_with_a_finish_time(
    session: AsyncSession,
) -> None:
    analysis = await seeded_analysis(session)

    cancelled = await repository.cancel_if_queued(session, analysis.id)

    await session.refresh(analysis)
    stored: Analysis | None = analysis
    assert cancelled is True
    assert stored is not None
    assert stored.status is AnalysisStatus.CANCELLED
    assert stored.finished_at is not None


async def test_an_analysis_that_has_started_cannot_be_cancelled(session: AsyncSession) -> None:
    analysis = await seeded_analysis(session)
    await repository.claim_queued(session, analysis.id)

    assert await repository.cancel_if_queued(session, analysis.id) is False

    await session.refresh(analysis)
    stored: Analysis | None = analysis
    assert stored is not None
    assert stored.status is AnalysisStatus.STARTING
    assert stored.finished_at is None


async def test_claiming_or_cancelling_an_unknown_analysis_changes_nothing(
    session: AsyncSession,
) -> None:
    assert await repository.claim_queued(session, 999) is False
    assert await repository.cancel_if_queued(session, 999) is False


async def finished_as(session: AsyncSession, analysis: Analysis, status: AnalysisStatus) -> None:
    await repository.update_analysis(
        session, analysis.id, status=status, error="old failure", finished_at=datetime.now(UTC)
    )


@pytest.mark.parametrize("earlier", [AnalysisStatus.DONE, AnalysisStatus.REPORT_FAILED])
async def test_a_finished_analysis_goes_back_to_ingesting_without_its_error_or_end_time(
    session: AsyncSession, earlier: AnalysisStatus
) -> None:
    analysis = await seeded_analysis(session)
    await finished_as(session, analysis, earlier)

    started = await repository.begin_reingest(session, analysis.id)

    await session.refresh(analysis)
    stored: Analysis | None = analysis
    assert started is True
    assert stored is not None
    assert stored.status is AnalysisStatus.INGESTING
    assert stored.error is None
    assert stored.finished_at is None


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.QUEUED,
        AnalysisStatus.STARTING,
        AnalysisStatus.RUNNING,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.INGESTING,
        AnalysisStatus.FAILED,
        AnalysisStatus.CANCELLED,
    ],
)
async def test_an_analysis_that_is_neither_done_nor_report_failed_is_not_reingested(
    session: AsyncSession, status: AnalysisStatus
) -> None:
    analysis = await seeded_analysis(session)
    await finished_as(session, analysis, status)

    assert await repository.begin_reingest(session, analysis.id) is False

    await session.refresh(analysis)
    stored: Analysis | None = analysis
    assert stored is not None
    assert stored.status is status
    assert stored.error == "old failure"


async def test_an_analysis_is_not_reingested_while_another_one_is_active(
    session: AsyncSession,
) -> None:
    finished = await seeded_analysis(session)
    await finished_as(session, finished, AnalysisStatus.DONE)
    busy = await seeded_analysis(session, filename="busy.exe")
    await repository.update_analysis(session, busy.id, status=AnalysisStatus.RUNNING)

    assert await repository.begin_reingest(session, finished.id) is False

    await session.refresh(finished)
    stored: Analysis | None = finished
    assert stored is not None
    assert stored.status is AnalysisStatus.DONE


async def test_reingesting_an_unknown_analysis_changes_nothing(session: AsyncSession) -> None:
    assert await repository.begin_reingest(session, 999) is False


@pytest.mark.parametrize(
    "status", [AnalysisStatus.QUEUED, AnalysisStatus.STARTING, AnalysisStatus.RUNNING]
)
async def test_an_analysis_that_is_waiting_for_or_using_the_guest_needs_it(
    session: AsyncSession, status: AnalysisStatus
) -> None:
    created = await seeded_analysis(session)
    await repository.update_analysis(session, created.id, status=status)

    assert await repository.has_analysis_needing_a_guest(session) is True


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.PROCESSING,
        AnalysisStatus.INGESTING,
        AnalysisStatus.DONE,
        AnalysisStatus.FAILED,
        AnalysisStatus.REPORT_FAILED,
        AnalysisStatus.CANCELLED,
    ],
)
async def test_an_analysis_the_guest_is_done_with_does_not_need_it(
    session: AsyncSession, status: AnalysisStatus
) -> None:
    created = await seeded_analysis(session)
    await repository.update_analysis(session, created.id, status=status)

    assert await repository.has_analysis_needing_a_guest(session) is False


async def test_no_analysis_at_all_needs_no_guest(session: AsyncSession) -> None:
    assert await repository.has_analysis_needing_a_guest(session) is False
