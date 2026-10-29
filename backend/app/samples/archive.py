import errno
import os
import re
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pyzipper

MAX_MEMBERS = 1000
MAX_DECLARED_BYTES = 2 * 1024**3
MAX_CENTRAL_DIRECTORY_BYTES = 4 * 1024**2

_EOCD = struct.Struct("<4sHHHHIIH")
_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_LOCATOR = struct.Struct("<4sIQI")
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_EOCD = struct.Struct("<4sQHHIIQQQQ")
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_MAX_EOCD_COMMENT = 0xFFFF
_ENCRYPTED_FLAG = 0x1
_DRIVE_LETTER = re.compile(r"[A-Za-z]:")
# pyzipper indexes and looks up header fields without validating them first.
_MALFORMED_ARCHIVE = (
    pyzipper.BadZipFile,
    UnicodeDecodeError,
    NotImplementedError,
    EOFError,
    struct.error,
    KeyError,
    IndexError,
    OverflowError,
)
_NOT_A_ZIP = "the file is not a valid zip archive"


class ArchiveError(Exception):
    """The message is safe to show to the analyst."""


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    size: int
    encrypted: bool
    unsafe: bool
    unsupported: bool


@dataclass(frozen=True)
class ArchiveListing:
    members: list[ArchiveMember]
    password_ok: bool | None


def read_archive(
    path: Path,
    password: str,
    *,
    max_members: int = MAX_MEMBERS,
    max_declared_bytes: int = MAX_DECLARED_BYTES,
    max_central_directory_bytes: int = MAX_CENTRAL_DIRECTORY_BYTES,
) -> ArchiveListing:
    """Lists the files of an untrusted zip and checks the password, without extracting anything.

    Raises `ArchiveError` when the zip is malformed, empty, or over a limit.
    """
    _require_small_central_directory(path, max_central_directory_bytes)
    with _translated_errors(), pyzipper.AESZipFile(path) as opened:
        infos = [info for info in opened.infolist() if not info.is_dir()]
        _require_within_limits(infos, max_members, max_declared_bytes)
        members = [_member(info) for info in infos]
        return ArchiveListing(members, _password_verdict(opened, infos, members, password))


@contextmanager
def _translated_errors() -> Iterator[None]:
    try:
        yield
    except _MALFORMED_ARCHIVE:
        raise ArchiveError(_NOT_A_ZIP) from None
    except OSError as error:
        # A forged offset makes the stdlib seek to a negative position; other I/O errors are ours.
        if error.errno != errno.EINVAL:
            raise
        raise ArchiveError(_NOT_A_ZIP) from None


def _require_small_central_directory(path: Path, limit: int) -> None:
    # zipfile reads the whole central directory into memory, so its size is judged first.
    if _central_directory_size(path) > limit:
        raise ArchiveError("the zip's central directory is too large to read safely")


def _central_directory_size(path: Path) -> int:
    """Mirrors where `zipfile` looks for the end records, so both agree on which size is real."""
    with path.open("rb") as file:
        file_size = file.seek(0, os.SEEK_END)
        tail_start = max(0, file_size - _EOCD.size - _MAX_EOCD_COMMENT)
        file.seek(tail_start)
        tail = file.read()
        eocd_offset = tail.rfind(_EOCD_SIGNATURE)
        if eocd_offset < 0 or len(tail) - eocd_offset < _EOCD.size:
            raise ArchiveError(_NOT_A_ZIP)
        size: int = _EOCD.unpack_from(tail, eocd_offset)[5]
        zip64_size = _zip64_central_directory_size(file, tail_start + eocd_offset)
        return size if zip64_size is None else zip64_size


def _zip64_central_directory_size(file: BinaryIO, eocd_position: int) -> int | None:
    """The zip64 record sits right before its locator, which sits right before the end record."""
    records_length = _ZIP64_EOCD.size + _ZIP64_LOCATOR.size
    if eocd_position < records_length:
        return None
    file.seek(eocd_position - records_length)
    records = file.read(records_length)
    if not records.startswith(_ZIP64_EOCD_SIGNATURE):
        return None
    if records[_ZIP64_EOCD.size :].startswith(_ZIP64_LOCATOR_SIGNATURE):
        size: int = _ZIP64_EOCD.unpack_from(records)[8]
        return size
    return None


def _require_within_limits(
    infos: list[pyzipper.ZipInfo], max_members: int, max_declared_bytes: int
) -> None:
    if not infos:
        raise ArchiveError("the zip contains no files")
    if len(infos) > max_members:
        raise ArchiveError(f"the zip contains more than {max_members} files")
    if sum(info.file_size for info in infos) > max_declared_bytes:
        raise ArchiveError(f"the zip's files are larger than {max_declared_bytes} bytes in total")
    names = [info.filename for info in infos]
    if len(set(names)) != len(names):
        raise ArchiveError("the zip contains a file name more than once")


def _member(info: pyzipper.ZipInfo) -> ArchiveMember:
    return ArchiveMember(
        name=info.filename,
        size=info.file_size,
        encrypted=bool(info.flag_bits & _ENCRYPTED_FLAG),
        unsafe=_escapes_the_directory(info),
        unsupported=_cannot_be_an_option_value(info.filename),
    )


def _escapes_the_directory(info: pyzipper.ZipInfo) -> bool:
    # zipfile cuts `filename` at the first NUL; `orig_filename` keeps the whole name.
    if "\x00" in info.orig_filename:
        return True
    name = info.filename.replace("\\", "/")
    return name.startswith("/") or bool(_DRIVE_LETTER.match(name)) or ".." in name.split("/")


def _cannot_be_an_option_value(name: str) -> bool:
    return "," in name or name != name.strip()


def _password_verdict(
    opened: pyzipper.AESZipFile,
    infos: list[pyzipper.ZipInfo],
    members: list[ArchiveMember],
    password: str,
) -> bool | None:
    candidates = [
        info
        for info, member in zip(infos, members, strict=True)
        if member.encrypted and not member.unsafe
    ]
    return _password_accepted(opened, candidates[0], password) if candidates else None


def _password_accepted(opened: pyzipper.AESZipFile, info: pyzipper.ZipInfo, password: str) -> bool:
    opened.setpassword(password.encode(errors="replace"))
    try:
        # Opening checks the AES password verifier or the ZipCrypto check byte and reads nothing
        # more. The check byte is one byte, so a wrong ZipCrypto password passes 1 time in 256.
        opened.open(info).close()
    except RuntimeError:
        return False
    return True
