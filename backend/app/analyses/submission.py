"""Queues an analysis: the one path `POST /analyses` and the guest self-test both take."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.archive_check import require_runnable_archive
from app.analyses.guest_choice import (
    AUTO_PACKAGE,
    GuestRefusedError,
    choose_guest,
    recorded_guest,
    require_package_accepted,
)
from app.analyses.memory_disk import (
    FreeSpaceProbe,
    MemoryDumpRefusedError,
    check_room_for_dump,
    pending_dump_mb,
)
from app.analyses.ports import RunnerControl
from app.annotations.validation import Target, normalise_tag_name
from app.db.analysis_repository import (
    add_sample_if_new,
    create_analysis,
    delete_sample_if_unreferenced,
    get_options_of_waiting_and_active_runs,
    get_sample,
)
from app.db.annotation_repository import add_tag
from app.db.models import Analysis, Sample
from app.db.models.analysis import AnalysisKind
from app.db.models.annotation import TargetType
from app.db.settings_repository import read_settings
from app.guest.schemas import Guest, GuestProfile
from app.samples.store import ByteSource, SampleStore, StoredSample, safe_file_name
from app.schemas.analysis_requests import AnalysisOptions
from app.schemas.settings import SettingsBody


class GuestDirectory(Protocol):
    """The part of the guest control service that choosing a guest needs."""

    async def guests(self) -> list[Guest]: ...

    async def profiles(self) -> list[GuestProfile]: ...


@dataclass(frozen=True)
class Submitted:
    analysis: Analysis
    warnings: list[str]


@dataclass(frozen=True)
class _Resolved:
    options: AnalysisOptions
    guest: Guest
    settings: SettingsBody
    dump_mb_ahead: int


class AnalysisSubmitter:
    """Validates the options against the guests, stores the sample and queues the analysis."""

    def __init__(
        self,
        store: SampleStore,
        guests: GuestDirectory,
        runner: RunnerControl,
        free_space: FreeSpaceProbe,
    ) -> None:
        self._store = store
        self._guests = guests
        self._runner = runner
        self._free_space = free_space

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
        """`submit_with_warnings` for the callers that have no use for the warnings."""
        submitted = await self.submit_with_warnings(
            session, stream, filename, options, gate=gate, tags=tags
        )
        return submitted.analysis

    async def submit_with_warnings(  # noqa: PLR0913 - see `submit`
        self,
        session: AsyncSession,
        stream: ByteSource,
        filename: str,
        options: AnalysisOptions,
        *,
        gate: bool = True,
        tags: Sequence[str] = (),
    ) -> Submitted:
        """Queues an analysis of the sample; its guest is written into the analysis's `options`.

        `warnings` are what the analyst should read though the analysis was accepted. The route
        calls this with the defaults. The self-test of a guest being built calls
        it with `gate=False`, which lets it run on a `testing` guest while others build or test
        (the named guest must still exist and be registered), and with `tags=["self-test"]`.

        Raises `GuestRefusedError` (the guest cannot run it), `PackageNotAcceptedError`,
        `MemoryDumpRefusedError` (too little free disk for the dump), `ArchiveRefusedError` (the
        archive fields name a zip that cannot be run: not a zip, no such member, a member that
        cannot be chosen, or a password that does not open it), `ValueError` (a bad tag name),
        the sample store's `EmptySampleError` and `SampleTooLargeError`, and `GuestControlError`
        when the control service cannot be asked.
        Nothing is stored when any of them is raised.
        """
        tag_names = [normalise_tag_name(tag) for tag in tags]
        resolved = await self._resolve(session, options, gate=gate)
        warnings = self._room_for_memory_dump(resolved)
        name = safe_file_name(filename)
        stored = await self._store.save(stream, name)
        try:
            await self._require_runnable_archive(stored, resolved.options)
            analysis = await queue_analysis(
                session, stored, name, resolved.options.model_dump(exclude_none=True)
            )
            for tag in tag_names:
                await add_tag(session, analysis.id, Target(TargetType.ANALYSIS), tag)
        except Exception:
            await session.rollback()
            await discard_unreferenced_sample(session, self._store, stored.sha256)
            raise
        self._runner.nudge()
        return Submitted(analysis, warnings)

    async def _require_runnable_archive(
        self, stored: StoredSample, options: AnalysisOptions
    ) -> None:
        if options.archive_password is None or options.archive_entry is None:
            return
        await require_runnable_archive(
            self._store, stored.sha256, options.archive_password, options.archive_entry
        )

    async def _resolve(
        self, session: AsyncSession, options: AnalysisOptions, *, gate: bool
    ) -> _Resolved:
        guests = await self._guests.guests()
        settings = await read_settings(session)
        ahead = await get_options_of_waiting_and_active_runs(session)
        busy = {name for name in map(recorded_guest, ahead) if name}
        guest = choose_guest(guests, options.guest, settings.default_guest, gate=gate, busy=busy)
        if options.package != AUTO_PACKAGE:
            require_package_accepted(guest, await self._profile_of(guest), options.package)
        dumping = [recorded_guest(each) or "" for each in ahead if each.get("memory_dump")]
        return _Resolved(
            options.model_copy(update={"guest": guest.name}),
            guest,
            settings,
            pending_dump_mb(guests, dumping),
        )

    def _room_for_memory_dump(self, resolved: _Resolved) -> list[str]:
        if not resolved.options.memory_dump:
            return []
        guest = resolved.guest
        if guest.resources is None:
            raise MemoryDumpRefusedError(
                f"The RAM of {guest.name} is not known, so the room for its memory dump "
                "cannot be worked out"
            )
        return check_room_for_dump(
            self._free_space.free_mb(),
            ram_mb=guest.resources.ram_mb,
            disk_block_gb=resolved.settings.disk_block_gb,
            disk_warn_gb=resolved.settings.disk_warn_gb,
            pending_dump_mb=resolved.dump_mb_ahead,
        )

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


async def queue_analysis(
    session: AsyncSession,
    stored: StoredSample,
    filename: str,
    options: dict[str, Any],
    kind: AnalysisKind = AnalysisKind.RUN,
) -> Analysis:
    """Records the sample (once per hash) and a queued analysis of it."""
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
        session, sample_sha256=stored.sha256, filename=filename, options=options, kind=kind
    )
