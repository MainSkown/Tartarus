from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.memory import MemoryFindings, MemorySummary
from app.analyses.ports import IngestFailedError, IngestResult, ReportOutcome, ReportUnreadableError
from app.analyses.runner import Runner
from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from tests.analyses.fakes import FakeCape, FakeIngester, FakeReports
from tests.analyses.guest_fakes import ScriptedGuestControl, profile_needing_enforced_timeout
from tests.analyses.helpers import adopt_by_cape, enqueue, load
from tests.test_analysis_repository import OPTIONS

type Factory = async_sessionmaker[AsyncSession]

TASK_ID = 7
OUTCOME = ReportOutcome(score=1.0, max_severity=None, detected_families=[], summary={})
WITH_DUMP = {**OPTIONS, "memory_dump": True}
KEEPING_THE_DUMP = {**WITH_DUMP, "keep_memory_dump": True}
TAKEN_AND_READ = MemorySummary(dump_taken=True, findings=MemoryFindings.OK)


class JournalIngester(FakeIngester):
    """Writes its ingest into the control service's call list, so the order shows."""

    def __init__(self, guests: ScriptedGuestControl) -> None:
        super().__init__()
        self._guests = guests

    async def ingest(self, analysis_id: int, report_path: Path) -> IngestResult:
        self._guests.calls.append(("ingest", analysis_id))
        return await super().ingest(analysis_id, report_path)


@pytest.fixture
def ingester(guests: ScriptedGuestControl) -> JournalIngester:
    return JournalIngester(guests)


def memory_calls(guests: ScriptedGuestControl) -> list[str]:
    wanted = {"analyse_memory", "delete_memory_dump", "ingest"}
    return [name for name, _ in guests.calls if name in wanted]


async def reported(
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    options: dict[str, object],
    **changes: object,
) -> int:
    reports.outcome = OUTCOME
    cape.scripts[TASK_ID] = ["reported"]
    return await adopt_by_cape(session_factory, TASK_ID, options=options, **changes)


def memory_of(analysis: Analysis) -> MemorySummary:
    assert analysis.summary is not None
    return MemorySummary.model_validate(analysis.summary["memory"])


async def test_a_memory_dump_is_asked_of_cape_as_the_form_field_not_an_option(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await enqueue(session_factory, options=WITH_DUMP)

    await runner.run_once()

    assert cape.created[0]["task_fields"] == {"memory": True}
    assert "memory" not in cape.created[0]["options"]


async def test_a_memory_dump_goes_with_the_task_fields_of_an_interactive_run(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    guests.profiles_listed = [profile_needing_enforced_timeout("windows")]
    await enqueue(session_factory, options={**WITH_DUMP, "interactive": True})

    await runner.run_once()

    assert cape.created[0]["task_fields"] == {"enforce_timeout": True, "memory": True}


async def test_an_analysis_without_a_dump_sends_no_memory_field(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await enqueue(session_factory, options={**OPTIONS, "memory_dump": False})

    await runner.run_once()

    assert cape.created[0]["task_fields"] == {}


async def test_the_dump_is_read_before_the_ingest_and_deleted_after_it(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    analysis_id = await reported(session_factory, cape, reports, WITH_DUMP)

    await runner.run_once()

    assert memory_calls(guests) == ["analyse_memory", "ingest", "delete_memory_dump"]
    assert ("analyse_memory", TASK_ID) in guests.calls
    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert memory_of(done) == TAKEN_AND_READ.model_copy(update={"dump_deleted": True})


async def test_a_dump_the_analyst_keeps_stays_after_the_ingest(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    analysis_id = await reported(session_factory, cape, reports, KEEPING_THE_DUMP)

    await runner.run_once()

    assert memory_calls(guests) == ["analyse_memory", "ingest"]
    assert memory_of(await load(session_factory, analysis_id)) == TAKEN_AND_READ


async def test_an_analysis_without_a_dump_has_no_memory_summary_and_no_memory_calls(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    analysis_id = await reported(session_factory, cape, reports, OPTIONS)

    await runner.run_once()

    assert memory_calls(guests) == ["ingest"]
    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert done.summary is not None
    assert "memory" not in done.summary


@pytest.mark.parametrize(
    "failure",
    [
        GuestControlUnreachable("analyse_memory", "ReadTimeout"),
        GuestControlRejected("analyse_memory", 502, "volatility3 could not be started"),
        RuntimeError("a bug"),
    ],
)
async def test_a_memory_step_that_fails_does_not_fail_the_analysis(  # noqa: PLR0913, PLR0917
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
    failure: Exception,
) -> None:
    guests.memory_analysis = failure
    analysis_id = await reported(session_factory, cape, reports, WITH_DUMP)

    await runner.run_once()

    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert memory_of(done).findings is MemoryFindings.FAILED
    assert memory_calls(guests) == ["analyse_memory", "ingest"]


async def test_a_dump_cape_skipped_is_unavailable_and_nothing_is_deleted(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    guests.memory_analysis = GuestControlRejected("analyse_memory", 404, "no memory dump")
    analysis_id = await reported(session_factory, cape, reports, WITH_DUMP)

    await runner.run_once()

    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert memory_of(done).findings is MemoryFindings.UNAVAILABLE
    assert memory_calls(guests) == ["analyse_memory", "ingest"]


async def test_a_dump_that_cannot_be_deleted_is_recorded_and_the_analysis_is_still_done(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    guests.memory_deletion = GuestControlUnreachable("delete_memory_dump", "ConnectError")
    analysis_id = await reported(session_factory, cape, reports, WITH_DUMP)

    await runner.run_once()

    done = await load(session_factory, analysis_id)
    assert done.status is AnalysisStatus.DONE
    assert memory_of(done).dump_deleted is False


async def test_an_unreadable_report_leaves_the_dump_alone(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    analysis_id = await reported(session_factory, cape, reports, WITH_DUMP)
    reports.outcome = ReportUnreadableError("report is missing: report.json")

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.REPORT_FAILED
    assert memory_calls(guests) == []


async def test_a_failed_ingest_keeps_the_dump_for_the_reingest(  # noqa: PLR0913, PLR0917
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
    ingester: JournalIngester,
) -> None:
    ingester.result = IngestFailedError("OpenSearch is down")
    analysis_id = await reported(session_factory, cape, reports, WITH_DUMP)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.REPORT_FAILED
    assert memory_calls(guests) == ["analyse_memory", "ingest"]


async def test_a_reingest_keeps_the_memory_summary_and_touches_the_dump_no_more(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    recorded = TAKEN_AND_READ.model_copy(update={"dump_bytes": 99, "dump_deleted": True})
    analysis_id = await reported(
        session_factory,
        cape,
        reports,
        WITH_DUMP,
        status=AnalysisStatus.INGESTING,
        summary={"memory": recorded.model_dump(mode="json")},
    )

    await runner.run_once()

    assert memory_calls(guests) == ["ingest"]
    assert memory_of(await load(session_factory, analysis_id)) == recorded
