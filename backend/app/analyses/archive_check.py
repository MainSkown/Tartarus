"""Checks, before an analysis is queued, that the zip it names can be run."""

import asyncio

from app.samples.archive import ArchiveError, ArchiveListing, ArchiveMember, read_archive
from app.samples.store import SampleStore

FILE_FIELD = "file"
ENTRY_FIELD = "options.archive_entry"
PASSWORD_FIELD = "options.archive_password"  # noqa: S105 - a field name, not a password


class ArchiveRefusedError(Exception):
    """The zip cannot be run as asked. `field` is the dotted request field to blame; the message
    is safe to show and never holds the password.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


async def require_runnable_archive(
    store: SampleStore, sha256: str, password: str, entry: str
) -> None:
    """Raises `ArchiveRefusedError` unless the stored sample is a zip holding `entry` as a member
    that can be chosen and the password opens it. A zip with nothing encrypted passes.
    """
    async with store.open_plain(sha256) as path:
        try:
            listing = await asyncio.to_thread(read_archive, path, password)
        except ArchiveError as invalid:
            raise ArchiveRefusedError(FILE_FIELD, str(invalid)) from None
    _require_choosable(_member_named(listing, entry))
    if listing.password_ok is False:
        raise ArchiveRefusedError(PASSWORD_FIELD, "the password does not open the archive")


def _member_named(listing: ArchiveListing, entry: str) -> ArchiveMember:
    found = next((member for member in listing.members if member.name == entry), None)
    if found is None:
        raise ArchiveRefusedError(ENTRY_FIELD, f"{entry!r} is not a file of the archive")
    return found


def _require_choosable(member: ArchiveMember) -> None:
    if member.unsafe:
        raise ArchiveRefusedError(ENTRY_FIELD, f"{member.name!r} cannot be run: its name is unsafe")
    if member.unsupported:
        raise ArchiveRefusedError(
            ENTRY_FIELD,
            f"{member.name!r} cannot be run: CAPE cannot be given a name with a comma "
            "or edge whitespace",
        )
