"""The job that follows a guest build or clone for the analyst.

The control service owns the build (decision 14 of the M6 plan): it runs on without this job, which
only relays what it reports, hands the guest to the self-test once it is built, and carries the
self-test's verdict back. A job that ends, is cancelled or is lost with the backend therefore never
stops or undoes a build; `reattach_guest_builds` follows the build again after a restart.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.db.models.job import JobType
from app.guest.client import GuestControl
from app.guest.errors import GuestControlError, GuestControlRejected, GuestControlUnreachable
from app.guest.log_tail import lines_after
from app.guest.schemas import BuildStatus
from app.guest.selftest import NoSelfTest, SelfTestRunner, SelfTestVerdict
from app.jobs.runner import AsyncJobHandler, ExpectedJobError, JobContext, JobResult, JobRunner

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
UNREACHABLE_GRACE_S = 60.0
# The control service answers with the last lines of the log and no offset, so the window must be
# longer than the burst a poll interval can add.
LOG_WINDOW = 300
# The build's own steps fill the bar up to here, the self-test the rest, so the bar does not sit at
# 100% while the guest is still being tested.
BUILD_SHARE_PERCENT = 90
SELFTEST_END_PERCENT = 99
DETAILS_LIMIT = 500
NOT_FOUND = 404
# The job kind of a self-test run again for a guest whose build had already succeeded.
SELFTEST_KIND = "selftest"
BUILD_REMOVED_MESSAGE = "the build was removed before it finished"


class GuestBuildError(Exception):
    """The job ended badly; the message is shown to the analyst as it is."""


@dataclass(frozen=True)
class _Timing:
    poll_interval_s: float
    unreachable_grace_s: float


class _Params(BaseModel):
    guest: str
    build_id: str
    kind: str


@dataclass(frozen=True)
class TrackedBuild:
    guest: str
    build_id: str
    job_id: int


class BuildTracking:
    """Submits the jobs that follow builds and knows which build each active job follows.

    A build has at most one such job at a time: asking again while one is active returns it, so
    that `continue` on a paused build resumes the paused job instead of starting a second.
    """

    def __init__(self, runner: JobRunner) -> None:
        self._runner = runner
        self._tracked: dict[str, TrackedBuild] = {}
        self._lock = asyncio.Lock()

    async def track(self, guest: str, build_id: str, kind: str) -> TrackedBuild:
        async with self._lock:
            if (existing := self._tracked.get(build_id)) is not None:
                return existing
            params = _Params(guest=guest, build_id=build_id, kind=kind)
            job = await self._runner.submit(JobType.GUEST_BUILD, None, params.model_dump())
            tracked = TrackedBuild(guest, build_id, job.id)
            self._tracked[build_id] = tracked
            return tracked

    def release(self, build_id: str, job_id: int) -> None:
        """Forgets the build if `job_id` is the job that follows it: a newer job is kept."""
        if (tracked := self._tracked.get(build_id)) is not None and tracked.job_id == job_id:
            del self._tracked[build_id]

    def active(self) -> TrackedBuild | None:
        return next(iter(self._tracked.values()), None)


def guest_build_handler(
    control: GuestControl,
    tracking: BuildTracking,
    selftest: SelfTestRunner | None = None,
    *,
    poll_interval_s: float = POLL_INTERVAL_S,
    unreachable_grace_s: float = UNREACHABLE_GRACE_S,
) -> AsyncJobHandler:
    """The `GUEST_BUILD` handler. Without a `selftest` a built guest stays `testing`."""
    runner = selftest or NoSelfTest()

    async def guest_build(context: JobContext) -> JobResult:
        params = _Params.model_validate(context.params)
        timing = _Timing(poll_interval_s, unreachable_grace_s)
        follower = _BuildFollower(control, context, params, runner, timing)
        try:
            if params.kind == SELFTEST_KIND:
                return await follower.hand_to_self_test(params.build_id)
            built = await follower.follow()
            return await follower.hand_to_self_test(built.id)
        finally:
            tracking.release(params.build_id, context.job_id)

    return guest_build


class _BuildFollower:
    def __init__(
        self,
        control: GuestControl,
        context: JobContext,
        params: _Params,
        selftest: SelfTestRunner,
        timing: _Timing,
    ) -> None:
        self._control = control
        self._context = context
        self._params = params
        self._selftest = selftest
        self._timing = timing
        self._seen_log: list[str] = []
        self._last_progress: tuple[str, int] | None = None
        self._paused_with: str | None = None
        self._outage_began: float | None = None
        self._read_once = False

    async def follow(self) -> BuildStatus:
        while True:
            status = await self._ask_build(lambda: self._control.build(self._params.build_id))
            self._read_once = True
            await self._relay(status)
            if status.status == "failed":
                raise GuestBuildError(_failure_of(status))
            if status.status == "succeeded":
                return status
            await asyncio.sleep(self._timing.poll_interval_s)

    async def hand_to_self_test(self, build_id: str) -> JobResult:
        guest = self._params.guest
        verdict = await self._selftest.run(guest, build_id, self._report_self_test_progress)
        if verdict is None:
            return {"guest": guest, "state": "testing", "selftest": "not run"}
        await self._ask(
            lambda: self._control.complete(
                build_id, passed=verdict.passed, selftest=verdict.details
            )
        )
        if not verdict.passed:
            raise GuestBuildError(f"The self-test of {guest} failed: {_describe(verdict)}")
        return {"guest": guest, "state": "ready", "selftest": verdict.details}

    async def _relay(self, status: BuildStatus) -> None:
        await self._relay_log()
        if status.status == "failed":
            return
        self._relay_progress(status)
        self._relay_pause(status)

    async def _relay_log(self) -> None:
        build_id = self._params.build_id
        fetched = await self._ask_build(lambda: self._control.build_log(build_id, LOG_WINDOW))
        if new_lines := lines_after(self._seen_log, fetched):
            self._context.append_log("\n".join(new_lines))
        self._seen_log = fetched

    def _relay_progress(self, status: BuildStatus) -> None:
        progress = (_step_label(status), status.percent * BUILD_SHARE_PERCENT // 100)
        if progress != self._last_progress:
            self._context.report_progress(*progress)
            self._last_progress = progress

    def _relay_pause(self, status: BuildStatus) -> None:
        instructions = _pause_instructions(status)
        if instructions == self._paused_with:
            return
        if instructions is None:
            self._context.resume()
        else:
            self._context.pause(instructions)
        self._paused_with = instructions

    def _report_self_test_progress(self, step: str, percent: int) -> None:
        share = SELFTEST_END_PERCENT - BUILD_SHARE_PERCENT
        clamped = max(0, min(100, percent))
        self._context.report_progress(step, BUILD_SHARE_PERCENT + share * clamped // 100)

    async def _ask_build[T](self, call: Callable[[], Awaitable[T]]) -> T:
        """A build that was read and is then answered 404 has been deleted, which ends the job."""
        try:
            return await self._ask(call)
        except GuestControlRejected as error:
            if error.status == NOT_FOUND and self._read_once:
                raise ExpectedJobError(BUILD_REMOVED_MESSAGE) from error
            raise

    async def _ask[T](self, call: Callable[[], Awaitable[T]]) -> T:
        """Retries `call` while the control service does not answer, for up to the grace period."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                answer = await call()
            except GuestControlUnreachable:
                if self._outage_began is None:
                    self._outage_began = loop.time()
                    self._context.append_log(
                        "The guest control service is not answering; the build goes on, retrying"
                    )
                if loop.time() - self._outage_began >= self._timing.unreachable_grace_s:
                    raise GuestBuildError(
                        _outage_message(self._timing.unreachable_grace_s)
                    ) from None
                await asyncio.sleep(self._timing.poll_interval_s)
            else:
                self._outage_began = None
                return answer


def _step_label(status: BuildStatus) -> str:
    if status.message:
        return status.message
    in_range = 0 <= status.step < len(status.steps)
    return status.steps[status.step].name if in_range else status.kind


def _pause_instructions(status: BuildStatus) -> str | None:
    if status.status != "paused":
        return None
    return status.pause.instructions if status.pause else ""


def _failure_of(status: BuildStatus) -> str:
    return status.message or f"The {status.kind} of {status.guest} failed"


def _describe(verdict: SelfTestVerdict) -> str:
    message = verdict.details.get("message")
    described = message if isinstance(message, str) else json.dumps(verdict.details, sort_keys=True)
    return described[:DETAILS_LIMIT]


def _outage_message(grace_s: float) -> str:
    return (
        f"The guest control service has not answered for {grace_s:.0f} s; "
        "the build goes on inside it and can be followed again once it is back"
    )


async def reattach_guest_builds(control: GuestControl, tracking: BuildTracking) -> None:
    """Follows again the builds a previous backend process was following.

    A `building` guest whose build still runs or is paused, and a `testing` guest whose build
    succeeded but whose verdict never came, get a job; anything else has nothing to follow.
    Called once the job runner has started. A control service that is down is only logged: the
    health dot shows it.
    """
    try:
        guests = await control.guests()
    except GuestControlError as error:
        logger.warning("Not reattaching guest builds: %s", error)
        return
    for guest in guests:
        if guest.state not in ("building", "testing") or guest.build_id is None:
            continue
        try:
            build = await control.build(guest.build_id)
        except GuestControlError as error:
            logger.warning("Not reattaching the build of %s: %s", guest.name, error)
            continue
        if _needs_following(guest.state, build):
            await tracking.track(guest.name, build.id, build.kind)


def _needs_following(guest_state: str, build: BuildStatus) -> bool:
    if build.status in ("running", "paused"):
        return True
    return build.status == "succeeded" and guest_state == "testing"
