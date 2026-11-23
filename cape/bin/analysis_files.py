"""What root may write into a folder the `cape` user owns, and how, without following a link.

`cape` owns every folder from `storage/analyses/` down and can swap any of them for a symlink at
any moment, while the services in this directory run as root. So everything root does there goes
through directory descriptors opened with O_NOFOLLOW, and each file it creates is handed to the
owner of the analysis folder, since CAPE (as `cape`) deletes the folder with its analysis and cannot
remove what root leaves in it. Used by `memory_logic` (Volatility's results), by the machine
broker (the memory dump of a guest) and by `lan_logic` (the fake local network's event log).
"""

import errno
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from guest_engine.lan_session import FileTooLargeError, open_regular_file

STORAGE_DIRECTORY = Path("/opt/CAPEv2/storage")
ANALYSIS_FILE_MODE = 0o644
ANALYSIS_DIRECTORY_MODE = 0o755
DUMP_NAME = "memory.dmp"
ANALYSES_FOLDER = "analyses"
COPY_CHUNK_BYTES = 1 << 30

READ_CHUNK_BYTES = 1 << 20

CREATE_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def open_directory(path: str | Path, parent: int | None = None) -> Iterator[int]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path, flags, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def hand_over(descriptor: int, owner: os.stat_result, mode: int) -> None:
    """The service runs as root; CAPE, as `cape`, deletes the whole task folder with the analysis
    and cannot remove what root leaves in it, so each result belongs to the folder's owner."""
    os.fchown(descriptor, owner.st_uid, owner.st_gid)
    os.fchmod(descriptor, mode)


@contextmanager
def _open_analysis_folder(storage: Path, task_id: int) -> Iterator[int]:
    """`storage` itself is a mount point of the image, which `cape` cannot rename or replace; every
    folder below it is opened from the one above."""
    with (
        open_directory(storage) as storage_descriptor,
        open_directory(ANALYSES_FOLDER, storage_descriptor) as analyses,
        open_directory(str(task_id), analyses) as analysis,
    ):
        yield analysis


def require_free_dump_slot(storage: Path, task_id: int) -> None:
    """Raises `OSError` unless `place_dump` could create the dump now, so a dump that would only be
    refused is not taken at all. `place_dump` still creates it exclusively: this can be raced."""
    with _open_analysis_folder(storage, task_id) as analysis:
        try:
            os.stat(DUMP_NAME, dir_fd=analysis, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise FileExistsError(errno.EEXIST, "the analysis already has a memory dump", DUMP_NAME)


def place_dump(staged: Path, storage: Path, task_id: int) -> None:
    """Copies `staged` to `<storage>/analyses/<task_id>/memory.dmp`, owned like the folder.

    The dump is created exclusively, so a file or a link `cape` put there first is an error rather
    than a redirect, and a copy that fails leaves no partial dump behind.
    """
    with _open_analysis_folder(storage, task_id) as analysis:
        owner = os.fstat(analysis)
        destination = os.open(DUMP_NAME, CREATE_NEW_FILE, ANALYSIS_FILE_MODE, dir_fd=analysis)
        try:
            _copy_into(destination, staged)
            hand_over(destination, owner, ANALYSIS_FILE_MODE)
        except BaseException:
            os.unlink(DUMP_NAME, dir_fd=analysis)
            raise
        finally:
            os.close(destination)


def _copy_into(destination: int, staged: Path) -> None:
    source = os.open(staged, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        while os.sendfile(destination, source, None, COPY_CHUNK_BYTES):
            pass
    finally:
        os.close(source)


@dataclass(frozen=True)
class Placement:
    """Where in an analysis folder a file goes, and the most it may hold."""

    folder: str
    name: str
    limit: int


def place_once(staged: Path, storage: Path, task_id: int, placement: Placement) -> bool:
    """Copies `staged` to `<storage>/analyses/<task_id>/<folder>/<name>`, owned like the analysis
    folder, and returns False, changing nothing, when `name` is already there: the first copy wins.

    The staged file belongs to another, less trusted service, so it is opened like the contract
    says (`open_regular_file`: no link, no pipe, a regular file under the limit) and is refused
    above the limit however it grows meanwhile.
    The folder is created when missing, but the analysis folder is not (`FileNotFoundError`: the
    analysis is gone). The copy goes to a temporary name and is linked into place, which fails
    rather than replaces, so a racing second copy cannot clobber the first.
    """
    source = open_regular_file(staged, placement.limit)
    try:
        with _open_analysis_folder(storage, task_id) as analysis:
            owner = os.fstat(analysis)
            _make_folder(analysis, placement.folder, owner)
            with open_directory(placement.folder, analysis) as target:
                return _link_copy(source, target, placement, owner)
    finally:
        os.close(source)


def _make_folder(analysis: int, name: str, owner: os.stat_result) -> None:
    try:
        os.mkdir(name, ANALYSIS_DIRECTORY_MODE, dir_fd=analysis)
    except FileExistsError:
        return
    with open_directory(name, analysis) as created:
        hand_over(created, owner, ANALYSIS_DIRECTORY_MODE)


def _link_copy(source: int, folder: int, placement: Placement, owner: os.stat_result) -> bool:
    name = placement.name
    temporary = f".{name}.{secrets.token_hex(4)}.tmp"
    destination = os.open(temporary, CREATE_NEW_FILE, ANALYSIS_FILE_MODE, dir_fd=folder)
    try:
        _copy_capped(source, destination, placement.limit)
        hand_over(destination, owner, ANALYSIS_FILE_MODE)
        try:
            os.link(temporary, name, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
        except FileExistsError:
            return False
        return True
    finally:
        os.close(destination)
        os.unlink(temporary, dir_fd=folder)


def _copy_capped(source: int, destination: int, limit: int) -> None:
    copied = 0
    while chunk := os.read(source, READ_CHUNK_BYTES):
        copied += len(chunk)
        if copied > limit:
            raise FileTooLargeError(errno.EFBIG, f"larger than {limit} bytes")
        view = memoryview(chunk)
        while view:
            view = view[os.write(destination, view) :]
