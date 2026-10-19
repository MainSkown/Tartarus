import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analyses.submission import AnalysisSubmitter
from app.db.annotation_repository import analysis_level_tags
from app.db.base import Base
from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from app.guest.schemas import Guest, GuestIdentity, ProofResult, SelfTestSample
from app.guest.selftest import SelfTestVerdict
from app.guest.selftest_runner import GuestSelfTest, SelfTestTiming
from app.samples.store import SampleStore
from tests.analyses.fakes import FakeFreeSpace
from tests.analyses.guest_fakes import ScriptedGuestControl, guest_named
from tests.guest.fakes import clean_checks
from tests.guest.selftest_fakes import CannedIndex, FakePipeline, aggregations

TIMING = SelfTestTiming(poll_interval_s=0.002, analysis_wait_s=2.0)
PASSWORD = "Hunter2-not-for-the-card"  # noqa: S105


@dataclass
class Run:
    runner: GuestSelfTest
    submitter: AnalysisSubmitter
    control: ScriptedGuestControl
    pipeline: FakePipeline
    index: CannedIndex
    factory: async_sessionmaker[AsyncSession]
    progress: list[tuple[str, int]] = field(default_factory=list)

    async def run(self, guest: str = "lab1") -> SelfTestVerdict | None:
        return await self.runner.run(guest, "b1", self._note)

    def _note(self, step: str, percent: int) -> None:
        self.progress.append((step, percent))

    async def analyses(self) -> list[Analysis]:
        async with self.factory() as session:
            return list((await session.scalars(select(Analysis))).all())

    async def tags_of(self, analysis_id: int) -> list[str]:
        async with self.factory() as session:
            return (await analysis_level_tags(session, [analysis_id])).get(analysis_id, [])


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[Run]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'selftest.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    testing = Guest(
        name="lab1",
        state="testing",
        profile="windows",
        identity=GuestIdentity(account="jan", machine="DESKTOP-4F7Q", password=PASSWORD),
    )
    control = ScriptedGuestControl([guest_named("win"), testing, guest_named("lab2", "building")])
    pipeline = FakePipeline(factory)
    index = CannedIndex(aggregations())
    submitter = AnalysisSubmitter(
        SampleStore(tmp_path / "samples"), control, pipeline, FakeFreeSpace()
    )
    runner = GuestSelfTest(control, submitter, factory, index, TIMING)
    yield Run(runner, submitter, control, pipeline, index, factory)
    await pipeline.stop()
    await engine.dispose()


async def test_a_healthy_guest_passes_after_sample_submission_wait_evidence_and_checks(
    stack: Run,
) -> None:
    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is True, verdict.details["message"]
    names = [name for name, _ in stack.control.calls]
    assert names.index("selftest_sample") < names.index("selftest_checks")
    assert stack.control.calls_named("selftest_sample") == ["lab1"]
    assert stack.control.calls_named("selftest_checks") == ["lab1"]
    [searched] = stack.index.searched
    [analysis] = await stack.analyses()
    assert searched[0] == analysis.id
    assert analysis.status is AnalysisStatus.DONE
    assert verdict.details["analysis_id"] == analysis.id


async def test_the_sample_is_submitted_ungated_on_that_guest_with_the_self_test_tag(
    stack: Run,
) -> None:
    await stack.run()

    [analysis] = await stack.analyses()
    # lab2 is building: only an ungated submission is accepted, and lab1 is still `testing`.
    assert analysis.options == {
        "route": "inetsim",
        "timeout": 60,
        "package": "exe",
        "interactive": False,
        "memory_dump": False,
        "keep_memory_dump": False,
        "guest": "lab1",
    }
    assert analysis.filename == "benign.exe"
    assert await stack.tags_of(analysis.id) == ["self-test"]
    assert stack.pipeline.nudges == 1


async def test_a_sample_whose_extension_the_profile_does_not_list_is_submitted_as_auto(
    stack: Run,
) -> None:
    stack.control.selftest_sample_listed = SelfTestSample("sample.bin", b"\x7fELF")

    await stack.run()

    [analysis] = await stack.analyses()
    assert analysis.options["package"] == "auto"


async def test_a_missing_signal_fails_the_verdict_with_its_message(stack: Run) -> None:
    stack.index.response = aggregations(registry=0)

    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is False
    assert "registry" in verdict.details["message"]
    assert verdict.details["signals"]["events.registry"]["ok"] is False


async def test_the_profiles_signals_are_the_ones_judged(stack: Run) -> None:
    stack.control.profiles_listed[0].selftest.signals.pop(0)

    verdict = await stack.run()

    assert verdict is not None
    assert "events.process" not in verdict.details["signals"]


async def test_an_analysis_that_fails_is_a_failing_verdict_and_the_guest_is_not_checked(
    stack: Run,
) -> None:
    stack.pipeline.statuses = [AnalysisStatus.STARTING, AnalysisStatus.FAILED]
    stack.pipeline.error = "the guest agent did not answer"

    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is False
    assert "the guest agent did not answer" in verdict.details["message"]
    assert stack.control.calls_named("selftest_checks") == []
    assert stack.index.searched == []


async def test_an_analysis_that_never_finishes_is_a_failing_verdict_after_the_limit(
    stack: Run,
) -> None:
    stack.pipeline.statuses = [AnalysisStatus.STARTING, AnalysisStatus.RUNNING]
    stack.runner = GuestSelfTest(
        stack.control,
        stack.submitter,
        stack.factory,
        stack.index,
        SelfTestTiming(poll_interval_s=0.002, analysis_wait_s=0.1),
    )

    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is False
    assert "did not finish in time" in verdict.details["message"]
    assert "running" in verdict.details["message"]
    assert stack.control.calls_named("selftest_checks") == []


async def test_giveaways_and_a_failing_proof_fail_the_verdict(stack: Run) -> None:
    stack.control.selftest_checks_listed = clean_checks().model_copy(
        update={
            "giveaways": ["scheduled task: SandboxAgent"],
            "proofs": {"eicar": ProofResult(ok=False, message="Defender removed the file")},
        }
    )

    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is False
    assert verdict.details["giveaways"] == ["scheduled task: SandboxAgent"]
    assert "eicar: Defender removed the file" in verdict.details["message"]


async def test_checks_the_control_service_refuses_are_a_failing_verdict_with_its_reason(
    stack: Run,
) -> None:
    stack.control.error_by_call["selftest_checks"] = GuestControlRejected(
        "selftest_checks", 502, "the guest agent is unreachable (URLError)"
    )

    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is False
    assert "the guest agent is unreachable" in verdict.details["message"]


async def test_a_control_service_outage_during_the_checks_propagates(stack: Run) -> None:
    stack.control.error_by_call["selftest_checks"] = GuestControlUnreachable(
        "selftest_checks", "ReadTimeout"
    )

    with pytest.raises(GuestControlUnreachable):
        await stack.run()


async def test_a_control_service_outage_fetching_the_sample_propagates_and_queues_nothing(
    stack: Run,
) -> None:
    stack.control.error_by_call["selftest_sample"] = GuestControlUnreachable(
        "selftest_sample", "ConnectError"
    )

    with pytest.raises(GuestControlUnreachable):
        await stack.run()

    assert await stack.analyses() == []


async def test_a_profile_without_a_sample_is_a_failing_verdict_not_a_crash(stack: Run) -> None:
    stack.control.error_by_call["selftest_sample"] = GuestControlRejected(
        "selftest_sample", 409, "the profile windows defines no self-test sample"
    )

    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is False
    assert "defines no self-test sample" in verdict.details["message"]
    assert await stack.analyses() == []
    assert stack.control.calls_named("selftest_checks") == []


async def test_a_guest_the_submission_refuses_is_a_failing_verdict(stack: Run) -> None:
    verdict = await stack.run("lab2")

    assert verdict is not None
    assert verdict.passed is False
    assert "lab2 is building" in verdict.details["message"]
    assert await stack.analyses() == []


async def test_a_guest_whose_profile_is_not_known_is_a_failing_verdict(stack: Run) -> None:
    stack.control.profiles_listed.clear()

    verdict = await stack.run()

    assert verdict is not None
    assert verdict.passed is False
    assert "windows" in verdict.details["message"]
    assert stack.control.calls_named("selftest_sample") == []


async def test_a_database_failure_while_waiting_propagates(stack: Run) -> None:
    class BrokenFactory:
        def __call__(self) -> AsyncSession:
            raise RuntimeError("the database went away")

    stack.runner = GuestSelfTest(
        stack.control,
        stack.submitter,
        BrokenFactory(),  # type: ignore[arg-type]
        stack.index,
        TIMING,
    )

    with pytest.raises(RuntimeError, match="database went away"):
        await stack.run()


async def test_progress_only_goes_forward_inside_zero_to_ninety_five(stack: Run) -> None:
    await stack.run()

    percents = [percent for _, percent in stack.progress]
    assert percents == sorted(percents)
    assert percents[0] >= 0 and percents[-1] <= 95  # noqa: PT018
    assert max(percents) > 60
    assert all(step for step, _ in stack.progress)


async def test_progress_stays_below_sixty_until_the_analysis_is_done(stack: Run) -> None:
    stack.pipeline.statuses = [AnalysisStatus.STARTING, AnalysisStatus.FAILED]

    await stack.run()

    assert max(percent for _, percent in stack.progress) <= 60


async def test_the_password_is_nowhere_in_the_details(stack: Run) -> None:
    stack.control.selftest_checks_listed = clean_checks().model_copy(
        update={"facts": {"os.hostname": "DESKTOP-4F7Q", "os.password": PASSWORD}}
    )

    verdict = await stack.run()

    assert verdict is not None
    assert PASSWORD not in json.dumps(verdict.details)
