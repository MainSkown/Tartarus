"""Queues an analysis: the one path `POST /analyses` and the guest self-test both take."""

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.guest_choice import (
    AUTO_PACKAGE,
    GuestRefusedError,
    choose_guest,
    require_package_accepted,
)
from app.analyses.ports import RunnerControl
from app.annotations.validation import Target, normalise_tag_name
from app.db.analysis_repository import (
    add_sample_if_new,
    create_analysis,
    delete_sample_if_unreferenced,
    get_sample,
)
from app.db.annotation_repository import add_tag
from app.db.models import Analysis, Sample
from app.db.models.annotation import TargetType
from app.db.settings_repository import read_settings
from app.guest.schemas import Guest, GuestProfile
from app.samples.store import ByteSource, SampleStore, StoredSample, safe_file_name
from app.schemas.analysis_requests import AnalysisOptions


class GuestDirectory(Protocol):
    """The part of the guest control service that choosing a guest needs."""

    async def guests(self) -> list[Guest]: ...

    async def profiles(self) -> list[GuestProfile]: ...


class AnalysisSubmitter:
    """Validates the options against the guests, stores the sample and queues the analysis."""

    def __init__(self, store: SampleStore, guests: GuestDirectory, runner: RunnerControl) -> None:
        self._store = store
        self._guests = guests
        self._runner = runner

    async def submit(  # noqa: PLR0913 - what an analysis is made of, plus the two internal switches
        self,
        session: AsyncSession,
        stream: ByteSource,
        filename: str,
        options: AnalysisOptions,
        *,
        gate: bool = True,
        tags: Sequence[str] = (),
    ) -> Analysis:
        """Queues an analysis of the sample and returns it, with its guest written into `options`.

        This is what the route calls with the defaults. The self-test of a guest being built calls
        it with `gate=False`, which lets it run on a `testing` guest while others build or test
        (the named guest must still exist and be registered), and with `tags=["self-test"]`.

        Raises `GuestRefusedError` (the guest cannot run it), `PackageNotAcceptedError`,
        `ValueError` (a bad tag name), the sample store's `EmptySampleError` and
        `SampleTooLargeError`, and `GuestControlError` when the control service cannot be asked.
        Nothing is stored when any of them is raised.
        """
        tag_names = [normalise_tag_name(tag) for tag in tags]
        resolved = await self._with_guest(session, options, gate=gate)
        name = safe_file_name(filename)
        stored = await self._store.save(stream, name)
        try:
            analysis = await _queue_analysis(session, stored, name, resolved)
            for tag in tag_names:
                await add_tag(session, analysis.id, Target(TargetType.ANALYSIS), tag)
        except Exception:
            await session.rollback()
            await discard_unreferenced_sample(session, self._store, stored.sha256)
            raise
        self._runner.nudge()
        return analysis

    async def _with_guest(
        self, session: AsyncSession, options: AnalysisOptions, *, gate: bool
    ) -> AnalysisOptions:
        guests = await self._guests.guests()
        preferred = (await read_settings(session)).default_guest
        guest = choose_guest(guests, options.guest, preferred, gate=gate)
        if options.package != AUTO_PACKAGE:
            require_package_accepted(guest, await self._profile_of(guest), options.package)
        return options.model_copy(update={"guest": guest.name})

    async def _profile_of(self, guest: Guest) -> GuestProfile:
        profile = next(
            (profile for profile in await self._guests.profiles() if profile.id == guest.profile),
            None,
        )
        if profile is None:
            raise GuestRefusedError(f"The profile of {guest.name} ({guest.profile}) is not known")
        return profile


async def discard_unreferenced_sample(
    session: AsyncSession, store: SampleStore, sha256: str
) -> None:
    row_removed = await delete_sample_if_unreferenced(session, sha256)
    if row_removed or await get_sample(session, sha256) is None:
        await store.delete(sha256)


async def _queue_analysis(
    session: AsyncSession, stored: StoredSample, filename: str, options: AnalysisOptions
) -> Analysis:
    sample = Sample(
        sha256=stored.sha256,
        sha1=stored.sha1,
        md5=stored.md5,
        size=stored.size,
        original_name=filename,
        stored_path=str(stored.path),
    )
    try:
        await add_sample_if_new(session, sample)
    except IntegrityError:
        # `add_sample_if_new` is get-then-insert: another upload of the same file won the insert.
        await session.rollback()
    return await create_analysis(
        session,
        sample_sha256=stored.sha256,
        filename=filename,
        options=options.model_dump(),
    )
