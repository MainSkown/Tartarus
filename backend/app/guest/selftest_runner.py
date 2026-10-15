"""The self-test of a built guest: its bundled sample is analysed on it like any analysis.

The analysis is queued through the same submitter as `POST /analyses` (ungated, tagged
`self-test`, so it shows on the Dashboard), the signals the guest's profile declares are read
from the analysis' own data, and the control service then looks inside the guest. The verdict
itself is `selftest_verdict.judge`; this module only gathers what it judges.

An expected failure (a signal missing, an analysis that fails or hangs, a profile without a
sample) is a failing verdict. A control service that cannot be reached and a database error
propagate: the build job turns them into a failed job.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.guest_choice import AUTO_PACKAGE, GuestRefusedError, PackageNotAcceptedError
from app.analyses.submission import AnalysisSubmitter
from app.db.analysis_repository import get_analysis
from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus
from app.guest.client import GuestControl
from app.guest.errors import GuestControlRejected
from app.guest.schemas import GuestProfile, SelfTestChecks
from app.guest.selftest import SelfTestVerdict
from app.guest.selftest_evidence import EventSearch, read_evidence
from app.guest.selftest_verdict import AnalysisOutcome, ChecksRefused, judge, not_run
from app.jobs.runner import ProgressReporter
from app.samples.store import BytesSource, EmptySampleError, SampleTooLargeError
from app.schemas.analysis_requests import AnalysisOptions

SELF_TEST_TAG = "self-test"
# One minute is enough for the sample, which exits at once; the minimum the options accept.
SAMPLE_TIMEOUT_S = 60
# The share of the self-test's own progress: the analysis fills up to here, the checks the rest.
ANALYSIS_END_PERCENT = 60
CHECKS_END_PERCENT = 95
FINAL_STATUSES = frozenset(
    {
        AnalysisStatus.DONE,
        AnalysisStatus.FAILED,
        AnalysisStatus.REPORT_FAILED,
        AnalysisStatus.CANCELLED,
    }
)
STATUS_PERCENT = {
    AnalysisStatus.QUEUED: 5,
    AnalysisStatus.STARTING: 15,
    AnalysisStatus.RUNNING: 30,
    AnalysisStatus.PROCESSING: 45,
    AnalysisStatus.INGESTING: 55,
    AnalysisStatus.DONE: ANALYSIS_END_PERCENT,
}
REFUSED_TO_QUEUE = (
    GuestRefusedError,
    PackageNotAcceptedError,
    EmptySampleError,
    SampleTooLargeError,
)


@dataclass(frozen=True)
class SelfTestTiming:
    poll_interval_s: float = 2.0
    analysis_wait_s: float = 300.0


class _CannotRunError(Exception):
    """The self-test cannot go on, and the message says why to the analyst."""


class _ForwardOnlyProgress:
    """Reports each step once and never steps the bar back."""

    def __init__(self, report: ProgressReporter) -> None:
        self._report = report
        self._last: tuple[str, int] | None = None

    def __call__(self, step: str, percent: int) -> None:
        floor = self._last[1] if self._last else 0
        reported = (step, max(floor, percent))
        if reported != self._last:
            self._report(*reported)
            self._last = reported


class GuestSelfTest:
    """The `SelfTestRunner` of the build job."""

    def __init__(
        self,
        control: GuestControl,
        submitter: AnalysisSubmitter,
        session_factory: async_sessionmaker[AsyncSession],
        index: EventSearch,
        timing: SelfTestTiming = SelfTestTiming(),  # noqa: B008 - frozen
    ) -> None:
        self._control = control
        self._submitter = submitter
        self._session_factory = session_factory
        self._index = index
        self._timing = timing

    async def run(
        self,
        guest_name: str,
        build_id: str,  # noqa: ARG002 - the protocol's signature
        report_progress: ProgressReporter,
    ) -> SelfTestVerdict:
        progress = _ForwardOnlyProgress(report_progress)
        try:
            return await self._test(guest_name, progress)
        except _CannotRunError as cannot:
            return not_run(str(cannot))

    async def _test(self, guest_name: str, progress: _ForwardOnlyProgress) -> SelfTestVerdict:
        profile = await self._profile_of(guest_name)
        analysis_id = await self._submit_sample(guest_name, profile)
        progress("Self-test: analysis queued", STATUS_PERCENT[AnalysisStatus.QUEUED])
        analysis, outcome = await self._wait_for(analysis_id, progress)
        if not outcome.done:
            return judge([], outcome, evidence=None, checks=None)
        evidence = await read_evidence(self._index, analysis)
        progress("Self-test: checking inside the guest", ANALYSIS_END_PERCENT)
        checks = await self._checks(guest_name)
        progress("Self-test: judging", CHECKS_END_PERCENT)
        return judge([signal.id for signal in profile.selftest.signals], outcome, evidence, checks)

    async def _profile_of(self, guest_name: str) -> GuestProfile:
        with _refusals_stop_the_test():
            guest = await self._control.guest(guest_name)
            profiles = await self._control.profiles()
        profile = next((profile for profile in profiles if profile.id == guest.profile), None)
        if profile is None:
            raise _CannotRunError(f"the profile {guest.profile} of {guest_name} is not known")
        return profile

    async def _submit_sample(self, guest_name: str, profile: GuestProfile) -> int:
        with _refusals_stop_the_test():
            sample = await self._control.selftest_sample(guest_name)
        options = AnalysisOptions(
            guest=guest_name,
            route="inetsim",
            timeout=SAMPLE_TIMEOUT_S,
            package=_package_of(sample.filename, profile),
            interactive=False,
        )
        try:
            async with self._session_factory() as session:
                queued = await self._submitter.submit(
                    session,
                    BytesSource(sample.content),
                    sample.filename,
                    options,
                    gate=False,
                    tags=[SELF_TEST_TAG],
                )
        except REFUSED_TO_QUEUE as refused:
            raise _CannotRunError(
                f"the self-test analysis could not be queued: {refused or type(refused).__name__}"
            ) from None
        return queued.id

    async def _wait_for(
        self, analysis_id: int, progress: _ForwardOnlyProgress
    ) -> tuple[Analysis, AnalysisOutcome]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timing.analysis_wait_s
        while True:
            async with self._session_factory() as session:
                analysis = await get_analysis(session, analysis_id)
            if analysis is None:
                raise _CannotRunError(f"the self-test analysis {analysis_id} was deleted")
            if analysis.status in STATUS_PERCENT:
                progress(
                    f"Self-test: analysis {analysis.status.value}", STATUS_PERCENT[analysis.status]
                )
            if analysis.status in FINAL_STATUSES:
                return analysis, AnalysisOutcome(
                    analysis_id, analysis.status.value, finished=True, error=analysis.error
                )
            if loop.time() >= deadline:
                return analysis, AnalysisOutcome(analysis_id, analysis.status.value, finished=False)
            await asyncio.sleep(self._timing.poll_interval_s)

    async def _checks(self, guest_name: str) -> SelfTestChecks | ChecksRefused:
        try:
            return await self._control.selftest_checks(guest_name)
        except GuestControlRejected as refused:
            return ChecksRefused(refused.message)


def _package_of(filename: str, profile: GuestProfile) -> str:
    extension = PurePath(filename).suffix.removeprefix(".").lower()
    return extension if extension in profile.packages else AUTO_PACKAGE


@contextmanager
def _refusals_stop_the_test() -> Iterator[None]:
    """Turns the control service's own refusal (it understood and said no) into a verdict."""
    try:
        yield
    except GuestControlRejected as refused:
        raise _CannotRunError(refused.message) from None
