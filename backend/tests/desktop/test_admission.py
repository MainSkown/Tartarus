import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import analysis_repository as repository
from app.db.models.analysis import AnalysisStatus
from app.desktop.admission import (
    CLOSE_CONFLICT,
    CLOSE_NOT_AVAILABLE_YET,
    CLOSE_NOT_FOUND,
    CloseRequest,
    DbAnalysisLookup,
    check_admission,
    wait_for_vnc_port,
)
from tests.analyses.helpers import enqueue
from tests.desktop.stubs import (
    TASK_ID,
    StubLookup,
    StubViewer,
    cape_unreachable,
    interactive_snapshot,
)

ANALYSIS_ID = 7
POLL_S = 0.005
PATIENCE_S = 0.15


def test_an_unknown_analysis_is_not_found() -> None:
    assert check_admission(None) == CloseRequest(CLOSE_NOT_FOUND, "analysis not found")


@pytest.mark.parametrize("status", [AnalysisStatus.STARTING, AnalysisStatus.RUNNING])
def test_a_starting_or_running_interactive_analysis_is_admitted(status: AnalysisStatus) -> None:
    assert check_admission(interactive_snapshot(status)) is None


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.QUEUED,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.INGESTING,
        AnalysisStatus.DONE,
        AnalysisStatus.FAILED,
        AnalysisStatus.REPORT_FAILED,
        AnalysisStatus.CANCELLED,
    ],
)
def test_an_analysis_that_is_not_running_is_a_conflict(status: AnalysisStatus) -> None:
    refusal = check_admission(interactive_snapshot(status))

    assert refusal == CloseRequest(CLOSE_CONFLICT, f"analysis is {status.value}, not running")


def test_an_analysis_not_submitted_interactive_is_a_conflict() -> None:
    refusal = check_admission(interactive_snapshot(interactive=False))

    assert refusal == CloseRequest(CLOSE_CONFLICT, "analysis was not submitted as interactive")


async def wait(
    lookup: StubLookup, viewer: StubViewer, *, patience_s: float = PATIENCE_S
) -> int | CloseRequest:
    return await wait_for_vnc_port(
        lookup, viewer, ANALYSIS_ID, poll_interval_s=POLL_S, patience_s=patience_s
    )


async def test_the_port_is_read_from_the_options_cape_recorded() -> None:
    lookup = StubLookup({ANALYSIS_ID: interactive_snapshot()})
    viewer = StubViewer({TASK_ID: "interactive=1,nohuman=yes,vnc_port=5902"})

    assert await wait(lookup, viewer) == 5902
    assert viewer.viewed == [TASK_ID]


async def test_it_waits_until_cape_has_recorded_the_port() -> None:
    lookup = StubLookup({ANALYSIS_ID: interactive_snapshot()})
    viewer = StubViewer(
        {TASK_ID: "interactive=1"}, options_once_viewed=(3, "interactive=1,vnc_port=5900")
    )

    assert await wait(lookup, viewer, patience_s=2) == 5900
    assert len(viewer.viewed) == 3


async def test_it_waits_for_the_task_to_be_submitted_without_asking_cape() -> None:
    lookup = StubLookup(
        {ANALYSIS_ID: interactive_snapshot(AnalysisStatus.STARTING, cape_task_id=None)}
    )
    viewer = StubViewer({TASK_ID: "vnc_port=5900"})

    assert await wait(lookup, viewer) == CloseRequest(
        CLOSE_NOT_AVAILABLE_YET, "desktop not available yet"
    )
    assert viewer.viewed == []


async def test_a_port_outside_the_display_range_is_never_used() -> None:
    lookup = StubLookup({ANALYSIS_ID: interactive_snapshot()})
    viewer = StubViewer({TASK_ID: "vnc_port=22"})

    assert await wait(lookup, viewer) == CloseRequest(
        CLOSE_NOT_AVAILABLE_YET, "desktop not available yet"
    )


async def test_it_gives_up_when_the_port_never_appears() -> None:
    lookup = StubLookup({ANALYSIS_ID: interactive_snapshot()})
    viewer = StubViewer({TASK_ID: "interactive=1"})

    assert await wait(lookup, viewer) == CloseRequest(
        CLOSE_NOT_AVAILABLE_YET, "desktop not available yet"
    )


async def test_a_cape_that_fails_for_a_moment_is_asked_again() -> None:
    lookup = StubLookup({ANALYSIS_ID: interactive_snapshot()})
    viewer = StubViewer({TASK_ID: "vnc_port=5900"}, errors=[cape_unreachable(), cape_unreachable()])

    assert await wait(lookup, viewer, patience_s=2) == 5900
    assert len(viewer.viewed) == 3


async def test_it_stops_waiting_when_the_analysis_stops_running() -> None:
    lookup = StubLookup({ANALYSIS_ID: interactive_snapshot(AnalysisStatus.PROCESSING)})
    viewer = StubViewer({TASK_ID: "vnc_port=5900"})

    assert await wait(lookup, viewer) == CloseRequest(
        CLOSE_CONFLICT, "analysis is processing, not running"
    )
    assert viewer.viewed == []


async def test_it_stops_waiting_when_the_analysis_is_deleted() -> None:
    assert await wait(StubLookup(), StubViewer()) == CloseRequest(
        CLOSE_NOT_FOUND, "analysis not found"
    )


async def test_the_database_lookup_reads_status_task_and_the_interactive_option(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis_id = await enqueue(
        session_factory, options={"route": "none", "timeout": 60, "interactive": True}
    )
    async with session_factory() as session:
        await repository.update_analysis(
            session, analysis_id, status=AnalysisStatus.RUNNING, cape_task_id=TASK_ID
        )

    snapshot = await DbAnalysisLookup(session_factory).snapshot(analysis_id)

    assert snapshot == interactive_snapshot(AnalysisStatus.RUNNING)


async def test_the_database_lookup_treats_a_missing_option_as_not_interactive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    analysis_id = await enqueue(session_factory, options={"route": "none", "timeout": 60})

    snapshot = await DbAnalysisLookup(session_factory).snapshot(analysis_id)

    assert snapshot is not None
    assert snapshot.interactive is False


async def test_the_database_lookup_returns_none_for_an_unknown_analysis(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await DbAnalysisLookup(session_factory).snapshot(999) is None
