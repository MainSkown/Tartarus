from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analyses.guest_choice import GuestRefusedError, PackageNotAcceptedError
from app.analyses.submission import AnalysisSubmitter
from app.db.annotation_repository import analysis_level_tags
from app.db.base import Base
from app.db.models import Analysis, Sample, Setting
from app.guest.errors import GuestControlUnreachable
from app.samples.store import BytesSource, EmptySampleError, SampleStore
from app.schemas.analysis_requests import AnalysisOptions
from tests.analyses.guest_fakes import ScriptedGuestControl, guest_named


class FakeRunner:
    def __init__(self) -> None:
        self.nudges = 0

    def nudge(self) -> None:
        self.nudges += 1


@dataclass
class Submission:
    session: AsyncSession
    store: SampleStore
    runner: FakeRunner
    control: ScriptedGuestControl
    submitter: AnalysisSubmitter

    async def submit(
        self,
        options: AnalysisOptions | None = None,
        *,
        gate: bool = True,
        tags: Sequence[str] = (),
    ) -> Analysis:
        return await self.submitter.submit(
            self.session,
            BytesSource(b"MZ pretend"),
            "benign.exe",
            options or AnalysisOptions(),
            gate=gate,
            tags=tags,
        )

    async def rows(self, model: type[Base]) -> list[object]:
        return list((await self.session.scalars(select(model))).all())


@pytest.fixture
async def submission(tmp_path: Path) -> AsyncIterator[Submission]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'submission.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    store, runner = SampleStore(tmp_path / "samples"), FakeRunner()
    control = ScriptedGuestControl([guest_named("win"), guest_named("lab1")])
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield Submission(session, store, runner, control, AnalysisSubmitter(store, control, runner))
    await engine.dispose()


async def test_the_chosen_guest_is_stored_in_the_options_and_the_runner_woken(
    submission: Submission,
) -> None:
    analysis = await submission.submit(AnalysisOptions(guest="lab1"))

    assert analysis.options["guest"] == "lab1"
    assert submission.runner.nudges == 1


async def test_an_omitted_guest_is_stored_resolved_to_the_first_ready_one(
    submission: Submission,
) -> None:
    analysis = await submission.submit()

    assert analysis.options["guest"] == "win"


async def test_the_default_guest_setting_decides_when_that_guest_is_ready(
    submission: Submission,
) -> None:
    submission.session.add(Setting(key="default_guest", value="lab1"))
    await submission.session.commit()

    assert (await submission.submit()).options["guest"] == "lab1"


async def test_a_default_guest_setting_that_names_no_guest_is_ignored(
    submission: Submission,
) -> None:
    submission.session.add(Setting(key="default_guest", value="deleted-since"))
    await submission.session.commit()

    assert (await submission.submit()).options["guest"] == "win"


async def test_a_refused_guest_stores_nothing_and_wakes_nobody(submission: Submission) -> None:
    with pytest.raises(GuestRefusedError):
        await submission.submit(AnalysisOptions(guest="nope"))

    assert await submission.rows(Sample) == []
    assert await submission.rows(Analysis) == []
    assert submission.runner.nudges == 0
    assert list((submission.store.root).glob("*")) == []


async def test_a_package_the_guest_does_not_accept_stores_nothing(submission: Submission) -> None:
    with pytest.raises(PackageNotAcceptedError, match="elf"):
        await submission.submit(AnalysisOptions(package="elf"))

    assert await submission.rows(Sample) == []


async def test_the_profile_is_only_asked_for_when_a_package_is_named(
    submission: Submission,
) -> None:
    await submission.submit()
    assert ("profiles", None) not in submission.control.calls

    await submission.submit(AnalysisOptions(package="dll"))
    assert ("profiles", None) in submission.control.calls


async def test_a_control_service_that_cannot_be_asked_refuses_with_its_own_error(
    submission: Submission,
) -> None:
    submission.control.error = GuestControlUnreachable("guests", "ConnectError")

    with pytest.raises(GuestControlUnreachable):
        await submission.submit()

    assert await submission.rows(Analysis) == []


async def test_an_empty_upload_is_the_samples_own_error_and_stores_nothing(
    submission: Submission,
) -> None:
    with pytest.raises(EmptySampleError):
        await submission.submitter.submit(
            submission.session, BytesSource(b""), "empty.exe", AnalysisOptions()
        )

    assert await submission.rows(Analysis) == []


async def test_the_gate_refuses_while_a_guest_is_being_built(submission: Submission) -> None:
    submission.control.guests_listed = [guest_named("win"), guest_named("lab2", "building")]

    with pytest.raises(GuestRefusedError, match="being built"):
        await submission.submit()


async def test_the_gate_off_runs_on_the_guest_being_tested_with_the_tag(
    submission: Submission,
) -> None:
    submission.control.guests_listed = [guest_named("win"), guest_named("lab2", "testing")]

    analysis = await submission.submit(
        AnalysisOptions(guest="lab2"), gate=False, tags=["self-test"]
    )

    assert analysis.options["guest"] == "lab2"
    assert await analysis_level_tags(submission.session, [analysis.id]) == {
        analysis.id: ["self-test"]
    }
    assert submission.runner.nudges == 1


async def test_the_gate_off_still_refuses_a_guest_that_does_not_exist(
    submission: Submission,
) -> None:
    with pytest.raises(GuestRefusedError, match="no guest named lab9"):
        await submission.submit(AnalysisOptions(guest="lab9"), gate=False)


async def test_a_tag_that_is_not_a_tag_name_is_refused_before_anything_is_stored(
    submission: Submission,
) -> None:
    with pytest.raises(ValueError, match="tag name"):
        await submission.submit(tags=["Not A Tag!"])

    assert await submission.rows(Sample) == []
