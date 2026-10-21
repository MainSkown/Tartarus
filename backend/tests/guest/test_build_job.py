import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from app.db.models.job import JobStatus, JobType
from app.guest.build_job import (
    BUILD_SHARE_PERCENT,
    LOG_WINDOW,
    SELFTEST_KIND,
    BuildTracking,
    GuestBuildError,
    guest_build_handler,
)
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from app.guest.selftest import NoSelfTest, SelfTestVerdict
from app.jobs.runner import JobContext, JobRunner, ProgressReporter
from tests.guest.fakes import BUILD_ID, FakeGuestControl, Poll, a_build
from tests.guest.harness import Harness, wait_until_ended

type Event = tuple[Any, ...]

JOB_ID = 7
FAST = {"poll_interval_s": 0.0, "unreachable_grace_s": 5.0}


class Rig:
    """A handler under test with a job context that records what the handler reports."""

    def __init__(self, control: FakeGuestControl, runner: JobRunner, kind: str = "build") -> None:
        self.control = control
        self.tracking = BuildTracking(runner)
        self.events: list[Event] = []
        self.context = JobContext(
            job_id=JOB_ID,
            analysis_id=None,
            params={"guest": "lab1", "build_id": BUILD_ID, "kind": kind},
            exports_dir=Path("unused"),
            report_progress=lambda step, percent: self.events.append(("progress", step, percent)),
            append_log=lambda text: self.events.append(("log", text)),
            pause=lambda instructions: self.events.append(("pause", instructions)),
            resume=lambda: self.events.append(("resume",)),
        )

    def handler(
        self, selftest: Any = None, **timing: float
    ) -> Callable[[JobContext], Awaitable[dict[str, Any]]]:
        return guest_build_handler(
            self.control, self.tracking, selftest or NoSelfTest(), **{**FAST, **timing}
        )

    async def run(self, selftest: Any = None, **timing: float) -> dict[str, Any]:
        return await self.handler(selftest, **timing)(self.context)

    def of_kind(self, kind: str) -> list[Event]:
        return [event for event in self.events if event[0] == kind]


@pytest.fixture
def rig(harness: Harness, tmp_path: Path) -> Rig:
    return Rig(FakeGuestControl(), JobRunner(harness.factory, tmp_path))


class VerdictRunner:
    def __init__(self, verdict: SelfTestVerdict | None, *, progress: list[int] | None = None):
        self.verdict = verdict
        self.progress = progress or []
        self.calls: list[tuple[str, str]] = []

    async def run(
        self, guest_name: str, build_id: str, report_progress: ProgressReporter
    ) -> SelfTestVerdict | None:
        self.calls.append((guest_name, build_id))
        for percent in self.progress:
            report_progress("Running the sample", percent)
        return self.verdict


@pytest.fixture
def retest_rig(harness: Harness, tmp_path: Path) -> Rig:
    return Rig(FakeGuestControl(), JobRunner(harness.factory, tmp_path), kind=SELFTEST_KIND)


# --- following a running build ---------------------------------------------------------------


async def test_the_jobs_progress_follows_the_builds_step_and_percent(rig: Rig) -> None:
    rig.control.polls = [
        Poll(a_build("running", percent=10, message="install")),
        Poll(a_build("running", percent=10, message="install")),
        Poll(a_build("running", percent=60, message="provision")),
        Poll(a_build("succeeded", percent=100)),
    ]

    await rig.run()

    assert rig.of_kind("progress") == [
        ("progress", "install", 10 * BUILD_SHARE_PERCENT // 100),
        ("progress", "provision", 60 * BUILD_SHARE_PERCENT // 100),
        ("progress", "register", BUILD_SHARE_PERCENT),
    ]


async def test_a_build_without_a_message_is_described_by_its_current_step(rig: Rig) -> None:
    rig.control.polls = [Poll(a_build("running", percent=5)), Poll(a_build("succeeded"))]

    await rig.run()

    assert rig.of_kind("progress")[0][1] == "register"


async def test_only_the_lines_added_since_the_last_poll_are_appended_to_the_log(rig: Rig) -> None:
    rig.control.polls = [
        Poll(a_build("running", percent=1), log=["== step one", "STEP a"]),
        Poll(a_build("running", percent=2), log=["== step one", "STEP a"]),
        Poll(a_build("running", percent=3), log=["== step one", "STEP a", "PROGRESS 5", "STEP a"]),
        Poll(a_build("succeeded"), log=["STEP a", "PROGRESS 5", "STEP a", "== step two"]),
    ]

    await rig.run()

    assert rig.of_kind("log") == [
        ("log", "== step one\nSTEP a"),
        ("log", "PROGRESS 5\nSTEP a"),
        ("log", "== step two"),
    ]


async def test_the_log_is_asked_for_with_a_window_that_covers_a_poll_interval(rig: Rig) -> None:
    rig.control.polls = [Poll(a_build("succeeded"))]

    await rig.run()

    assert rig.control.calls_named("build_log")[0] == (BUILD_ID, LOG_WINDOW)


# --- pause ------------------------------------------------------------------------------------


async def test_a_paused_build_pauses_the_job_with_its_instructions_until_it_runs_again(
    rig: Rig,
) -> None:
    rig.control.polls = [
        Poll(a_build("running", percent=20, message="tamper-off")),
        Poll(a_build("paused", percent=22, message="tamper-off", pause="Switch it off")),
        Poll(a_build("paused", percent=22, message="tamper-off", pause="Switch it off")),
        Poll(a_build("running", percent=22, message="tamper-off")),
        Poll(a_build("succeeded")),
    ]

    await rig.run()

    pauses = [event for event in rig.events if event[0] in ("pause", "resume")]
    assert pauses == [("pause", "Switch it off"), ("resume",)]
    assert rig.control.polled == 5


async def test_a_pause_with_new_instructions_is_reported_again(rig: Rig) -> None:
    rig.control.polls = [
        Poll(a_build("paused", pause="first")),
        Poll(a_build("paused", pause="second")),
        Poll(a_build("succeeded")),
    ]

    await rig.run()

    assert [event for event in rig.events if event[0] == "pause"] == [
        ("pause", "first"),
        ("pause", "second"),
    ]


# --- a build that fails -----------------------------------------------------------------------


async def test_a_failed_build_fails_the_job_with_the_builds_message(rig: Rig) -> None:
    rig.control.polls = [
        Poll(a_build("running", percent=30, message="provision")),
        Poll(a_build("failed", percent=30, message="provision exited with 1; resume it")),
    ]

    with pytest.raises(GuestBuildError, match="provision exited with 1; resume it"):
        await rig.run()

    assert rig.control.calls_named("complete") == []


async def test_a_failed_build_without_a_message_still_gives_a_reason(rig: Rig) -> None:
    rig.control.polls = [Poll(a_build("failed", guest="lab1", kind="clone"))]

    with pytest.raises(GuestBuildError, match="clone of lab1 failed"):
        await rig.run()


# --- the self-test ----------------------------------------------------------------------------


async def test_without_a_self_test_the_guest_stays_testing_and_the_job_ends_done(rig: Rig) -> None:
    rig.control.polls = [Poll(a_build("succeeded", percent=100))]

    result = await rig.run()

    assert result == {"guest": "lab1", "state": "testing", "selftest": "not run"}
    assert rig.control.calls_named("complete") == []


async def test_a_passing_verdict_is_handed_to_the_control_service_and_the_guest_is_ready(
    rig: Rig,
) -> None:
    runner = VerdictRunner(SelfTestVerdict(True, {"signals": ["process", "file"]}))
    rig.control.polls = [Poll(a_build("succeeded"))]

    result = await rig.run(runner)

    assert runner.calls == [("lab1", BUILD_ID)]
    assert rig.control.calls_named("complete") == [
        (BUILD_ID, True, {"signals": ["process", "file"]})
    ]
    assert result == {
        "guest": "lab1",
        "state": "ready",
        "selftest": {"signals": ["process", "file"]},
    }


async def test_a_failing_verdict_is_recorded_and_fails_the_job_with_its_message(rig: Rig) -> None:
    runner = VerdictRunner(SelfTestVerdict(False, {"message": "no registry event was seen"}))
    rig.control.polls = [Poll(a_build("succeeded"))]

    with pytest.raises(GuestBuildError, match="self-test of lab1 failed: no registry event"):
        await rig.run(runner)

    assert rig.control.calls_named("complete") == [
        (BUILD_ID, False, {"message": "no registry event was seen"})
    ]


# --- running the self-test again for a failed guest -----------------------------------------------


async def test_a_retest_runs_the_same_self_test_and_hands_its_verdict_to_the_control_service(
    retest_rig: Rig,
) -> None:
    runner = VerdictRunner(SelfTestVerdict(True, {"signals": ["process"]}))

    result = await retest_rig.run(runner)

    assert runner.calls == [("lab1", BUILD_ID)]
    assert retest_rig.control.calls_named("complete") == [
        (BUILD_ID, True, {"signals": ["process"]})
    ]
    assert result == {"guest": "lab1", "state": "ready", "selftest": {"signals": ["process"]}}


async def test_a_retest_that_fails_again_fails_the_job_with_the_same_message_as_a_build(
    retest_rig: Rig,
) -> None:
    runner = VerdictRunner(SelfTestVerdict(False, {"message": "no registry event was seen"}))

    with pytest.raises(GuestBuildError, match="self-test of lab1 failed: no registry event"):
        await retest_rig.run(runner)

    assert retest_rig.control.calls_named("complete") == [
        (BUILD_ID, False, {"message": "no registry event was seen"})
    ]


async def test_a_retest_does_not_replay_the_finished_builds_log_or_poll_it(
    retest_rig: Rig,
) -> None:
    retest_rig.control.polls = [Poll(a_build("succeeded"), log=["== step one", "STEP a"])]

    await retest_rig.run(VerdictRunner(SelfTestVerdict(True)))

    assert retest_rig.of_kind("log") == []
    assert retest_rig.control.calls_named("build") == []
    assert retest_rig.control.calls_named("build_log") == []


async def test_a_retests_progress_is_the_self_tests_share_of_the_bar(retest_rig: Rig) -> None:
    await retest_rig.run(VerdictRunner(SelfTestVerdict(True), progress=[0, 100]))

    assert [event[2] for event in retest_rig.of_kind("progress")] == [BUILD_SHARE_PERCENT, 99]


async def test_a_retest_without_a_self_test_leaves_the_guest_testing(retest_rig: Rig) -> None:
    result = await retest_rig.run()

    assert result["state"] == "testing"
    assert retest_rig.control.calls_named("complete") == []


async def test_a_failing_verdict_without_a_message_describes_its_details(rig: Rig) -> None:
    runner = VerdictRunner(SelfTestVerdict(False, {"eicar": "removed"}))
    rig.control.polls = [Poll(a_build("succeeded"))]

    with pytest.raises(GuestBuildError, match='"eicar": "removed"'):
        await rig.run(runner)


async def test_a_self_test_without_a_verdict_leaves_the_guest_testing(rig: Rig) -> None:
    rig.control.polls = [Poll(a_build("succeeded"))]

    result = await rig.run(VerdictRunner(None))

    assert result["state"] == "testing"
    assert rig.control.calls_named("complete") == []


async def test_the_self_tests_progress_fills_the_end_of_the_bar(rig: Rig) -> None:
    runner = VerdictRunner(SelfTestVerdict(True), progress=[0, 50, 100])
    rig.control.polls = [Poll(a_build("succeeded"))]

    await rig.run(runner)

    percents = [event[2] for event in rig.of_kind("progress")]
    assert percents[-3:] == [BUILD_SHARE_PERCENT, 94, 99]


async def test_a_self_test_that_crashes_fails_the_job_and_gives_no_verdict(rig: Rig) -> None:
    class Crashing:
        async def run(self, *_: Any) -> SelfTestVerdict:
            raise RuntimeError("the sample never started")

    rig.control.polls = [Poll(a_build("succeeded"))]

    with pytest.raises(RuntimeError, match="never started"):
        await rig.run(Crashing())

    assert rig.control.calls_named("complete") == []


async def test_a_verdict_the_control_service_refuses_fails_the_job_readably(rig: Rig) -> None:
    refusal = GuestControlRejected("complete", 409, "lab1 is failed; a passed self-test no")
    rig.control.error_by_call["complete"] = refusal
    rig.control.polls = [Poll(a_build("succeeded"))]

    with pytest.raises(GuestControlRejected, match="lab1 is failed"):
        await rig.run(VerdictRunner(SelfTestVerdict(True)))


# --- the control service goes away ------------------------------------------------------------


async def test_an_outage_shorter_than_the_grace_is_ridden_out_and_noted_once(rig: Rig) -> None:
    down = GuestControlUnreachable("build", "ConnectError")
    rig.control.polls = [
        Poll(a_build("running", percent=10, message="install")),
        Poll(down),
        Poll(down),
        Poll(down),
        Poll(a_build("running", percent=20, message="install")),
        Poll(a_build("succeeded")),
    ]

    result = await rig.run()

    assert result["state"] == "testing"
    notes = [event for event in rig.of_kind("log") if "not answering" in event[1]]
    assert len(notes) == 1
    assert rig.of_kind("progress")[-2][2] == 20 * BUILD_SHARE_PERCENT // 100


async def test_an_outage_longer_than_the_grace_fails_the_job_but_not_the_build(rig: Rig) -> None:
    rig.control.polls = [Poll(a_build("running")), Poll(GuestControlUnreachable("build", "x"))]

    with pytest.raises(GuestBuildError, match=r"not answered for .* the build goes on"):
        await rig.run(unreachable_grace_s=0.05, poll_interval_s=0.01)

    forbidden = {"resume", "restart", "continue", "complete", "delete_guest"}
    assert forbidden.isdisjoint(name for name, _ in rig.control.calls)


async def test_a_refusal_that_is_not_an_outage_fails_the_job_at_once(rig: Rig) -> None:
    gone = GuestControlRejected("build", 404, "no build called b2f48f9dcd08a")
    rig.control.polls = [Poll(gone)]

    with pytest.raises(GuestControlRejected):
        await rig.run()

    assert rig.control.polled == 1


@pytest.fixture
async def started_runner(harness: Harness, tmp_path: Path) -> AsyncIterator[JobRunner]:
    runner = JobRunner(harness.factory, tmp_path)
    await runner.start()
    yield runner
    await runner.stop()


async def test_a_build_removed_after_the_job_read_it_ends_the_job_failed_without_a_traceback(
    harness: Harness,
    started_runner: JobRunner,
    rig: Rig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig.control.polls = [
        Poll(a_build("running", percent=10, message="install")),
        Poll(GuestControlRejected("build", 404, "no build called b2f48f9dcd08a")),
    ]
    rig.tracking = BuildTracking(started_runner)
    started_runner.register(JobType.GUEST_BUILD, rig.handler(poll_interval_s=0.001))
    with caplog.at_level(logging.INFO):
        tracked = await rig.tracking.track("lab1", BUILD_ID, "build")
        job = await wait_until_ended(harness)

    assert job.id == tracked.job_id
    assert job.status is JobStatus.FAILED
    assert job.result == {"error": "the build was removed before it finished"}
    assert rig.tracking.active() is None
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


# --- cancellation and the registry ------------------------------------------------------------


async def test_cancelling_the_job_leaves_the_build_alone(rig: Rig) -> None:
    rig.control.polls = [Poll(a_build("running", percent=10))]
    task = asyncio.create_task(rig.run(poll_interval_s=60.0))
    await asyncio.sleep(0.02)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    forbidden = {"resume", "restart", "continue", "complete", "delete_guest"}
    assert forbidden.isdisjoint(name for name, _ in rig.control.calls)


@pytest.mark.parametrize("ending", ["done", "failed", "cancelled"])
async def test_the_build_is_no_longer_tracked_once_its_job_has_ended(rig: Rig, ending: str) -> None:
    tracked = await rig.tracking.track("lab1", BUILD_ID, "build")
    rig.context = dataclasses.replace(rig.context, job_id=tracked.job_id)
    assert rig.tracking.active() == tracked
    if ending == "done":
        rig.control.polls = [Poll(a_build("succeeded"))]
    elif ending == "failed":
        rig.control.polls = [Poll(a_build("failed", message="no"))]
    else:
        rig.control.polls = [Poll(a_build("running"))]

    task = asyncio.create_task(rig.run(poll_interval_s=60.0 if ending == "cancelled" else 0.0))
    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert rig.tracking.active() is None
