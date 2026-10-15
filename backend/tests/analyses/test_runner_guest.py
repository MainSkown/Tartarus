import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.runner import Runner
from app.cape.errors import CapeRejected
from app.db.models.analysis import AnalysisStatus
from app.guest.errors import (
    GuestControlBadResponse,
    GuestControlNotConfigured,
    GuestControlUnreachable,
)
from tests.analyses.fakes import FakeCape
from tests.analyses.guest_fakes import (
    ScriptedGuestControl,
    guest_named,
    profile_needing_enforced_timeout,
    windows_profile,
)
from tests.analyses.helpers import enqueue, load
from tests.test_analysis_repository import OPTIONS

type Factory = async_sessionmaker[AsyncSession]

WINDOWS_INTERACTIVE = "interactive=1,nohuman=yes"


async def queue(session_factory: Factory, filename: str = "benign.exe", **options: object) -> int:
    return await enqueue(session_factory, filename, options={**OPTIONS, **options})


async def test_each_analysis_is_submitted_to_the_machine_its_options_name(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    cape.script_for_new_tasks = ["failed_analysis"]
    await queue(session_factory, "first.exe", guest="lab1")
    await queue(session_factory, "second.exe", guest="win")

    await runner.run_once()
    await runner.run_once()
    await runner.run_once()

    assert [(task["filename"], task["machine"]) for task in cape.created] == [
        ("first.exe", "lab1"),
        ("second.exe", "win"),
    ]


async def test_an_analysis_that_names_no_guest_fails_without_a_machine_being_guessed(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    analysis_id = await queue(session_factory, guest=None)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "no guest" in failed.error.lower()
    assert cape.calls == []


async def test_a_plain_analysis_sends_no_options_even_though_the_profile_has_some(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await queue(session_factory, interactive=False)

    await runner.run_once()

    assert (cape.created[0]["options"], cape.created[0]["task_fields"]) == ("", {})


async def test_an_interactive_analysis_gets_the_options_of_the_guests_profile(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await queue(session_factory, interactive=True)

    await runner.run_once()

    assert cape.created[0]["options"] == WINDOWS_INTERACTIVE
    assert cape.created[0]["task_fields"] == {}


async def test_an_interactive_analysis_on_a_profile_with_task_fields_sends_them(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    guests.guests_listed = [guest_named("lin1", profile="ubuntu")]
    guests.profiles_listed = [windows_profile(), profile_needing_enforced_timeout("ubuntu")]
    await queue(session_factory, interactive=True, guest="lin1")

    await runner.run_once()

    assert cape.created[0]["machine"] == "lin1"
    assert cape.created[0]["options"] == ""
    assert cape.created[0]["task_fields"] == {"enforce_timeout": True}


async def test_the_options_come_from_the_profile_of_the_guest_not_of_another(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    guests.guests_listed = [guest_named("win"), guest_named("lin1", profile="ubuntu")]
    guests.profiles_listed = [windows_profile(), profile_needing_enforced_timeout("ubuntu")]
    await queue(session_factory, interactive=True, guest="win")

    await runner.run_once()

    assert cape.created[0]["options"] == WINDOWS_INTERACTIVE
    assert cape.created[0]["task_fields"] == {}


async def test_a_profile_the_control_service_does_not_list_fails_an_interactive_analysis(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    guests.guests_listed = [guest_named("win", profile="gone")]
    analysis_id = await queue(session_factory, interactive=True)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error is not None
    assert "profile gone" in failed.error
    assert cape.calls == []


async def test_a_guest_deleted_after_the_analysis_was_queued_fails_it_readably(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    analysis_id = await queue(session_factory, guest="lab2")

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == "Guest lab2 no longer exists"
    assert failed.cape_task_id is None
    assert cape.calls == []


async def test_the_next_analysis_runs_after_one_whose_guest_is_gone(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    await queue(session_factory, "orphan.exe", guest="lab2")
    await queue(session_factory, "fine.exe")

    await runner.run_once()
    await runner.run_once()

    assert [task["filename"] for task in cape.created] == ["fine.exe"]


async def test_cape_refusing_the_machine_fails_the_analysis_and_stores_no_task_id(
    runner: Runner, session_factory: Factory, cape: FakeCape
) -> None:
    message = "Machine 'win' does not exist. Available: lab1"
    cape.create_errors = [CapeRejected("tasks/create/file", message)]
    analysis_id = await queue(session_factory)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == f"CAPE refused the task: {message}"
    assert failed.cape_task_id is None


async def test_a_control_service_that_cannot_be_reached_puts_the_analysis_back_in_the_queue(
    runner: Runner, session_factory: Factory, cape: FakeCape, guests: ScriptedGuestControl
) -> None:
    guests.error = GuestControlUnreachable("guest", "ConnectError")
    analysis_id = await queue(session_factory)

    await runner.run_once()

    waiting = await load(session_factory, analysis_id)
    assert waiting.status is AnalysisStatus.QUEUED
    assert waiting.error is None
    assert cape.calls == []

    guests.error = None
    await runner.run_once()
    assert (await load(session_factory, analysis_id)).cape_task_id == 100


@pytest.mark.parametrize(
    "failure",
    [GuestControlNotConfigured("guest"), GuestControlBadResponse("guest", "wrong shape")],
    ids=["not-configured", "bad-response"],
)
async def test_a_control_service_that_will_not_do_better_fails_the_analysis(
    runner: Runner,
    session_factory: Factory,
    cape: FakeCape,
    guests: ScriptedGuestControl,
    failure: Exception,
) -> None:
    guests.error = failure
    analysis_id = await queue(session_factory)

    await runner.run_once()

    failed = await load(session_factory, analysis_id)
    assert failed.status is AnalysisStatus.FAILED
    assert failed.error == str(failure)
    assert cape.calls == []
