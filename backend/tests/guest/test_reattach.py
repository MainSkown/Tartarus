import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.db.models.job import JobStatus, JobType
from app.guest.build_job import BuildTracking, guest_build_handler, reattach_guest_builds
from app.guest.errors import GuestControlUnreachable
from app.guest.schemas import Guest
from app.jobs.runner import JobRunner
from tests.guest.fakes import FakeGuestControl, Poll, a_build
from tests.guest.harness import Harness, jobs_of, wait_until_ended


@pytest.fixture
async def runner(harness: Harness, tmp_path: Path) -> AsyncIterator[JobRunner]:
    job_runner = JobRunner(harness.factory, tmp_path)
    await job_runner.start()
    yield job_runner
    await job_runner.stop()


@pytest.fixture
def tracking(runner: JobRunner) -> BuildTracking:
    return BuildTracking(runner)


def building(name: str = "lab1", build_id: str = "b1") -> Guest:
    return Guest(name=name, state="building", build_id=build_id)


async def test_a_running_build_is_followed_again_after_a_restart(
    harness: Harness, tracking: BuildTracking
) -> None:
    control = FakeGuestControl(guests=[building()])
    control.polls = [Poll(a_build("running", id="b1"))]

    await reattach_guest_builds(control, tracking)

    tracked = tracking.active()
    assert tracked is not None
    assert (tracked.guest, tracked.build_id) == ("lab1", "b1")
    [job] = await jobs_of(harness)
    assert (job.id, job.type) == (tracked.job_id, JobType.GUEST_BUILD)


async def test_a_paused_build_is_followed_again_after_a_restart(tracking: BuildTracking) -> None:
    control = FakeGuestControl(guests=[building()])
    control.polls = [Poll(a_build("paused", pause="Do it", id="b1"))]

    await reattach_guest_builds(control, tracking)

    assert tracking.active() is not None


async def test_a_testing_guest_whose_build_succeeded_is_followed_to_get_its_self_test(
    tracking: BuildTracking,
) -> None:
    control = FakeGuestControl(guests=[Guest(name="lab1", state="testing", build_id="b1")])
    control.polls = [Poll(a_build("succeeded", id="b1"))]

    await reattach_guest_builds(control, tracking)

    assert tracking.active() is not None


@pytest.mark.parametrize(
    ("guest", "build_status"),
    [
        (Guest(name="lab1", state="building", build_id="b1"), "failed"),
        (Guest(name="lab1", state="ready", build_id="b1"), "succeeded"),
        (Guest(name="lab1", state="failed", build_id="b1"), "failed"),
        (Guest(name="lab1", state="broken", error="unreadable"), "running"),
        (Guest(name="lab1", state="building"), "running"),
    ],
    ids=["failed build", "ready guest", "failed guest", "broken guest", "no build id"],
)
async def test_a_build_with_nothing_left_to_follow_gets_no_job(
    harness: Harness, tracking: BuildTracking, guest: Guest, build_status: str
) -> None:
    control = FakeGuestControl(guests=[guest])
    control.polls = [Poll(a_build(build_status, id="b1"))]  # type: ignore[arg-type]

    await reattach_guest_builds(control, tracking)

    assert tracking.active() is None
    assert await jobs_of(harness) == []


async def test_a_control_service_that_is_down_at_start_is_logged_and_nothing_more(
    harness: Harness, tracking: BuildTracking, caplog: pytest.LogCaptureFixture
) -> None:
    control = FakeGuestControl(error=GuestControlUnreachable("guests", "ConnectError"))

    with caplog.at_level(logging.WARNING):
        await reattach_guest_builds(control, tracking)

    assert tracking.active() is None
    assert await jobs_of(harness) == []
    assert "Not reattaching" in caplog.text


async def test_a_build_that_cannot_be_read_does_not_stop_the_others_being_followed(
    tracking: BuildTracking,
) -> None:
    control = FakeGuestControl(guests=[building("lab1", "b1"), building("lab2", "b2")])
    control.polls = [
        Poll(GuestControlUnreachable("build", "timeout")),
        Poll(a_build("running", guest="lab2", id="b2")),
    ]

    await reattach_guest_builds(control, tracking)

    tracked = tracking.active()
    assert tracked is not None
    assert tracked.guest == "lab2"


async def test_a_reattached_build_is_followed_to_the_end_by_the_registered_handler(
    harness: Harness, runner: JobRunner, tracking: BuildTracking
) -> None:
    control = FakeGuestControl(guests=[building()])
    control.polls = [
        Poll(a_build("running", percent=50, message="provision", id="b1")),
        Poll(a_build("running", percent=50, message="provision", id="b1")),
        Poll(a_build("succeeded", percent=100, id="b1")),
    ]
    runner.register(
        JobType.GUEST_BUILD, guest_build_handler(control, tracking, poll_interval_s=0.001)
    )

    await reattach_guest_builds(control, tracking)
    job = await wait_until_ended(harness)

    assert job.status is JobStatus.DONE
    assert job.result == {"guest": "lab1", "state": "testing", "selftest": "not run"}
    assert tracking.active() is None
