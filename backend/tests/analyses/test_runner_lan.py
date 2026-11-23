import logging
from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import ReportOutcome, ReportUnreadableError
from app.analyses.runner import Runner
from app.cape.errors import CapeRejected, CapeTaskNotFound, CapeUnreachable
from app.db.models.analysis import AnalysisStatus
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from tests.analyses.conftest import GRACE_SECONDS
from tests.analyses.fakes import FIRST_TASK_ID, FakeCape, FakeClock, FakeIngester, FakeReports
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.analyses.helpers import adopt_by_cape, app_log_text, enqueue, load
from tests.analyses.test_runner_memory import JournalIngester
from tests.test_analysis_repository import OPTIONS

type Factory = async_sessionmaker[AsyncSession]

PRESET = "small-office"
WITH_LAN = {**OPTIONS, "lan_preset": PRESET}
OUTCOME = ReportOutcome(score=1.0, max_severity=None, detected_families=[], summary={})
OPEN, CLOSE = "open_lan_session", "close_lan_session"
UNREACHABLE = GuestControlUnreachable(CLOSE, "ConnectError")


class OrderedCape(FakeCape):
    """Remembers which LAN sessions were open when each task was created."""

    def __init__(self, guests: ScriptedGuestControl) -> None:
        super().__init__()
        self._guests = guests
        self.open_at_creation: list[dict[str, tuple[str, str]]] = []

    async def create_file_task(self, *args: Any, **kwargs: Any) -> int:
        self.open_at_creation.append(dict(self._guests.lan_open))
        return await super().create_file_task(*args, **kwargs)


@pytest.fixture
def ingester(guests: ScriptedGuestControl) -> JournalIngester:
    return JournalIngester(guests)


@pytest.fixture
def cape(guests: ScriptedGuestControl) -> OrderedCape:
    return OrderedCape(guests)


def lan_names(guests: ScriptedGuestControl) -> list[str]:
    return [name for name, _ in guests.lan_calls()]


def closes(guests: ScriptedGuestControl) -> list[Any]:
    return guests.calls_named(CLOSE)


async def submitted_and_reported(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    options: Mapping[str, object] = WITH_LAN,
) -> int:
    reports.outcome = reports.outcome or OUTCOME
    cape.script_for_new_tasks = ["reported"]
    analysis_id = await enqueue(session_factory, options=options)
    await runner.run_once()
    await runner.run_once()
    return analysis_id


async def test_off_the_runner_opens_and_closes_nothing_and_asks_nothing_of_the_lan(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    analysis_id = await submitted_and_reported(runner, session_factory, cape, reports, OPTIONS)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    assert set(lan_names(guests)) <= {"lan_sessions"}


async def test_the_session_is_open_for_the_guest_before_the_task_is_created(
    runner: Runner, session_factory: Factory, cape: OrderedCape, guests: ScriptedGuestControl
) -> None:
    analysis_id = await enqueue(session_factory, options={**WITH_LAN, "guest": "lab1"})

    await runner.run_once()

    key = f"analysis-{analysis_id}"
    assert cape.open_at_creation == [{key: ("lab1", PRESET)}]
    assert guests.calls_named(OPEN) == [(key, "lab1", PRESET)]


async def test_a_session_that_cannot_open_fails_the_analysis_with_the_reason_and_submits_nothing(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    guests.error_by_call[OPEN] = GuestControlRejected(OPEN, 503, "the daemon did not answer")
    analysis_id = await enqueue(session_factory, options=WITH_LAN)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "fake local network could not start" in failed.error
    assert "the daemon did not answer" in failed.error
    assert cape.calls == []
    assert guests.lan_open == {}


async def test_a_control_service_that_cannot_be_reached_fails_the_analysis_instead_of_queueing_it(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    guests.error_by_call[OPEN] = GuestControlUnreachable(OPEN, "ConnectError")
    analysis_id = await enqueue(session_factory, options=WITH_LAN)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert "fake local network could not start" in (failed.error or "")
    assert cape.calls == []


async def test_a_session_whose_open_answer_is_lost_is_closed_in_case_it_was_opened(
    runner: Runner, session_factory: Factory, guests: ScriptedGuestControl
) -> None:
    guests.error_by_call[OPEN] = GuestControlUnreachable(OPEN, "ReadTimeout")
    analysis_id = await enqueue(session_factory, options=WITH_LAN)

    await runner.run_once()

    assert closes(guests) == [(f"analysis-{analysis_id}", None)]


async def test_a_refused_open_has_nothing_to_close(
    runner: Runner, session_factory: Factory, guests: ScriptedGuestControl
) -> None:
    guests.error_by_call[OPEN] = GuestControlRejected(OPEN, 409, "a session is already open")
    await enqueue(session_factory, options=WITH_LAN)

    await runner.run_once()

    assert closes(guests) == []


async def test_cape_refusing_the_task_closes_the_session_before_the_failure_is_reported(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    cape.create_errors = [CapeRejected("tasks/create", "no such machine")]
    analysis_id = await enqueue(session_factory, options=WITH_LAN)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert "no such machine" in (failed.error or "")
    assert guests.lan_open == {}
    assert closes(guests) == [(f"analysis-{analysis_id}", None)]


async def test_cape_being_unreachable_closes_the_session_and_the_retry_opens_it_again(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    cape.create_errors = [CapeUnreachable("tasks/create", "ConnectError")]
    analysis_id = await enqueue(session_factory, options=WITH_LAN)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.QUEUED
    assert guests.lan_open == {}

    await runner.run_once()

    assert list(guests.lan_open) == [f"analysis-{analysis_id}"]
    assert len(guests.calls_named(OPEN)) == 2


async def test_a_finished_analysis_closes_with_its_task_id_before_the_ingest_reads_the_folder(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    analysis_id = await submitted_and_reported(runner, session_factory, cape, reports)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    key = f"analysis-{analysis_id}"
    assert [
        (name, argument) for name, argument in guests.calls if name in {OPEN, CLOSE, "ingest"}
    ] == [
        (OPEN, (key, "win", PRESET)),
        (CLOSE, (key, FIRST_TASK_ID)),
        ("ingest", analysis_id),
    ]


async def test_a_session_closed_at_the_ingest_is_not_closed_again_when_the_analysis_ends(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    await submitted_and_reported(runner, session_factory, cape, reports)
    await runner.run_once()

    assert len(closes(guests)) == 1


async def test_an_ingest_that_fails_still_closes_the_session_once(  # noqa: PLR0913, PLR0917 - the runner's fakes
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    ingester: FakeIngester,
    guests: ScriptedGuestControl,
) -> None:
    ingester.result = RuntimeError("index is gone")
    analysis_id = await submitted_and_reported(runner, session_factory, cape, reports)

    assert (await load(session_factory, analysis_id)).status is not AnalysisStatus.DONE
    assert closes(guests) == [(f"analysis-{analysis_id}", FIRST_TASK_ID)]


async def test_a_task_capes_ends_as_failed_closes_the_session_with_the_task_id(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    cape.script_for_new_tasks = ["failed_analysis"]
    analysis_id = await enqueue(session_factory, options=WITH_LAN)
    await runner.run_once()
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.FAILED
    assert guests.lan_open == {}
    assert closes(guests) == [(f"analysis-{analysis_id}", FIRST_TASK_ID)]


async def test_an_unreadable_report_closes_the_session(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
) -> None:
    reports.outcome = ReportUnreadableError("report.json is missing")
    analysis_id = await submitted_and_reported(runner, session_factory, cape, reports)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.REPORT_FAILED
    assert closes(guests) == [(f"analysis-{analysis_id}", FIRST_TASK_ID)]


async def test_a_task_capes_forgot_closes_the_session(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    cape.scripts[7] = [CapeTaskNotFound("tasks/status", 7, "no task 7")]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING, options=WITH_LAN)
    guests.lan_open[f"analysis-{analysis_id}"] = ("win", PRESET)

    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.FAILED
    assert closes(guests) == [(f"analysis-{analysis_id}", 7)]


async def test_an_analysis_that_timed_out_on_a_cape_outage_closes_the_session(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    clock: FakeClock,
    guests: ScriptedGuestControl,
) -> None:
    cape.scripts[7] = [CapeUnreachable("tasks/status", "ConnectError")]
    analysis_id = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING, options=WITH_LAN)
    guests.lan_open[f"analysis-{analysis_id}"] = ("win", PRESET)

    await runner.run_once()
    assert closes(guests) == []
    clock.advance(GRACE_SECONDS + 1)
    await runner.run_once()

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.FAILED
    assert closes(guests) == [(f"analysis-{analysis_id}", 7)]


async def test_a_close_that_fails_does_not_fail_the_analysis_and_the_next_pass_retries_it(  # noqa: PLR0913, PLR0917 - the runner's fakes
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    reports: FakeReports,
    guests: ScriptedGuestControl,
    caplog: pytest.LogCaptureFixture,
) -> None:
    guests.error_by_call[CLOSE] = UNREACHABLE
    with caplog.at_level(logging.WARNING):
        analysis_id = await submitted_and_reported(runner, session_factory, cape, reports)

    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE
    key = f"analysis-{analysis_id}"
    assert list(guests.lan_open) == [key]
    assert key in app_log_text(caplog)

    del guests.error_by_call[CLOSE]
    await runner.run_once()

    assert guests.lan_open == {}
    assert closes(guests)[-1] == (key, FIRST_TASK_ID)
    assert (await load(session_factory, analysis_id)).status is AnalysisStatus.DONE


async def test_the_reconcile_closes_the_key_of_an_analysis_that_is_not_active_any_more(
    make_runner: Any, session_factory: Factory, guests: ScriptedGuestControl
) -> None:
    ended = await adopt_by_cape(
        session_factory, 7, AnalysisStatus.FAILED, options=WITH_LAN, finished_at=None
    )
    guests.lan_open[f"analysis-{ended}"] = ("win", PRESET)

    await make_runner().run_once()

    assert guests.lan_open == {}
    assert closes(guests) == [(f"analysis-{ended}", 7)]


async def test_the_reconcile_closes_the_key_of_an_analysis_that_no_longer_exists_without_a_task(
    runner: Runner, guests: ScriptedGuestControl
) -> None:
    guests.lan_open["analysis-999"] = ("win", PRESET)

    await runner.run_once()

    assert closes(guests) == [("analysis-999", None)]


async def test_the_reconcile_leaves_an_active_analysis_and_a_foreign_key_alone(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    cape.scripts[7] = ["running"]
    active = await adopt_by_cape(session_factory, 7, AnalysisStatus.RUNNING, options=WITH_LAN)
    guests.lan_open[f"analysis-{active}"] = ("win", PRESET)
    for foreign in ("someone-else", "analysis-", "analysis-7x", "analysis-07-extra"):
        guests.lan_open[foreign] = ("lab1", PRESET)

    await runner.run_once()

    assert closes(guests) == []
    assert len(guests.lan_open) == 5


async def test_the_sessions_are_listed_once_a_run_and_again_only_when_a_close_failed(
    runner: Runner, session_factory: Factory, guests: ScriptedGuestControl, cape: FakeCape
) -> None:
    cape.script_for_new_tasks = ["running"]
    await enqueue(session_factory, options=OPTIONS)

    await runner.run_once()
    await runner.run_once()
    await runner.run_once()

    assert lan_names(guests) == ["lan_sessions"]


async def test_a_listing_that_fails_is_tried_again_on_the_next_pass(
    runner: Runner, guests: ScriptedGuestControl
) -> None:
    guests.error_by_call["lan_sessions"] = GuestControlUnreachable("lan_sessions", "ConnectError")
    guests.lan_open["analysis-999"] = ("win", PRESET)

    await runner.run_once()
    assert closes(guests) == []
    del guests.error_by_call["lan_sessions"]
    await runner.run_once()

    assert closes(guests) == [("analysis-999", None)]


async def test_a_new_runner_after_a_restart_lists_the_sessions_again(
    make_runner: Any, guests: ScriptedGuestControl
) -> None:
    await make_runner().run_once()
    guests.lan_open["analysis-999"] = ("win", PRESET)

    await make_runner().run_once()

    assert closes(guests) == [("analysis-999", None)]
