from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analyses.guest_choice import GuestRefusedError, PackageNotAcceptedError
from app.analyses.memory_disk import MemoryDumpRefusedError
from app.analyses.submission import AnalysisSubmitter
from app.db.annotation_repository import analysis_level_tags
from app.db.base import Base
from app.db.models import Analysis, Sample, Setting
from app.guest.errors import GuestControlUnreachable
from app.samples.store import BytesSource, EmptySampleError, SampleStore
from app.schemas.analysis_requests import AnalysisOptions
from tests.analyses.fakes import FakeFreeSpace
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
    free_space: FakeFreeSpace

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
    free_space = FakeFreeSpace()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        submitter = AnalysisSubmitter(store, control, runner, free_space)
        yield Submission(session, store, runner, control, submitter, free_space)
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


async def test_a_busy_default_guest_gives_way_to_an_idle_one(submission: Submission) -> None:
    submission.session.add(Setting(key="default_guest", value="lab1"))
    await submission.session.commit()
    assert (await submission.submit()).options["guest"] == "lab1"

    assert (await submission.submit()).options["guest"] == "win"


async def test_a_requested_guest_is_kept_though_it_is_busy(submission: Submission) -> None:
    await submission.submit(AnalysisOptions(guest="lab1"))

    assert (await submission.submit(AnalysisOptions(guest="lab1"))).options["guest"] == "lab1"


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


async def test_a_memory_dump_without_room_stores_nothing_and_wakes_nobody(
    submission: Submission,
) -> None:
    submission.free_space.free = 10 * 1024

    with pytest.raises(MemoryDumpRefusedError):
        await submission.submit(AnalysisOptions(memory_dump=True))

    assert await submission.rows(Sample) == []
    assert await submission.rows(Analysis) == []
    assert submission.runner.nudges == 0
    assert list(submission.store.root.glob("*")) == []


async def test_the_room_a_memory_dump_needs_follows_the_stored_disk_thresholds(
    submission: Submission,
) -> None:
    submission.session.add(Setting(key="disk_block_gb", value=80))
    submission.session.add(Setting(key="disk_warn_gb", value=100))
    await submission.session.commit()
    submission.free_space.free = 83 * 1024

    with pytest.raises(MemoryDumpRefusedError, match=r"needs 84\.0 GB free and 83\.0 GB"):
        await submission.submit(AnalysisOptions(memory_dump=True))


async def test_a_submission_with_little_room_left_carries_the_warning(
    submission: Submission,
) -> None:
    submission.free_space.free = 52 * 1024

    submitted = await submission.submitter.submit_with_warnings(
        submission.session, BytesSource(b"MZ pretend"), "a.exe", AnalysisOptions(memory_dump=True)
    )

    assert len(submitted.warnings) == 1
    assert submitted.analysis.options["memory_dump"] is True


async def test_two_memory_dumps_that_fit_alone_but_not_together_refuse_the_second(
    submission: Submission,
) -> None:
    submission.free_space.free = 52 * 1024
    await submission.submit(AnalysisOptions(guest="win", memory_dump=True))

    with pytest.raises(MemoryDumpRefusedError) as refused:
        await submission.submit(AnalysisOptions(guest="lab1", memory_dump=True))

    assert "needs 52.8 GB free and 52.0 GB is available" in str(refused.value)
    assert len(await submission.rows(Analysis)) == 1


async def test_an_analysis_without_a_dump_does_not_count_against_the_room(
    submission: Submission,
) -> None:
    submission.free_space.free = 52 * 1024
    await submission.submit(AnalysisOptions(guest="win"))

    await submission.submit(AnalysisOptions(guest="lab1", memory_dump=True))
