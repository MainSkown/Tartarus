import asyncio
import hashlib
import io
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol, Self

import pyzipper

from app.config import Settings

CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_BYTES = 512 * CHUNK_SIZE
ZIP_PASSWORD = b"infected"
FALLBACK_NAME = "sample"
PRIVATE_FILE = 0o600
PRIVATE_DIRECTORY = 0o700
_SHA256 = re.compile(r"[0-9a-f]{64}")
_INCOMING = ".incoming"


class ByteSource(Protocol):
    """An upload stream; FastAPI's `UploadFile` is one."""

    async def read(self, size: int, /) -> bytes: ...


class BytesSource:
    """A `ByteSource` over a sample the backend already holds in memory."""

    def __init__(self, content: bytes) -> None:
        self._stream = io.BytesIO(content)

    async def read(self, size: int, /) -> bytes:
        return self._stream.read(size)


class EmptySampleError(Exception):
    """The upload had no content."""


class SampleTooLargeError(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"sample is larger than {max_bytes} bytes")
        self.max_bytes = max_bytes


@dataclass(frozen=True)
class StoredSample:
    sha256: str
    sha1: str
    md5: str
    size: int
    path: Path


class Digests:
    def __init__(self) -> None:
        self._sha256 = hashlib.sha256()
        self._sha1 = hashlib.sha1(usedforsecurity=False)
        self._md5 = hashlib.md5(usedforsecurity=False)
        self.size = 0

    def update(self, chunk: bytes) -> None:
        self._sha256.update(chunk)
        self._sha1.update(chunk)
        self._md5.update(chunk)
        self.size += len(chunk)

    def stored_in(self, root: Path) -> StoredSample:
        return self.kept_at(root / _zip_name(self._sha256.hexdigest()))

    def kept_at(self, path: Path) -> StoredSample:
        return StoredSample(
            sha256=self._sha256.hexdigest(),
            sha1=self._sha1.hexdigest(),
            md5=self._md5.hexdigest(),
            size=self.size,
            path=path,
        )


async def copy_capped(
    stream: ByteSource,
    destination: BinaryIO,
    max_bytes: int,
    observe: Callable[[bytes], None] | None = None,
) -> int:
    """Copies an upload to `destination` one chunk at a time and returns the byte count.

    `observe` sees each chunk in the worker thread that writes it, so a hash costs no second pass.
    Raises `SampleTooLargeError` past `max_bytes` and `EmptySampleError` when nothing arrives.
    """
    copied = 0
    while chunk := await stream.read(CHUNK_SIZE):
        if copied + len(chunk) > max_bytes:
            raise SampleTooLargeError(max_bytes)
        await asyncio.to_thread(_write_chunk, chunk, destination, observe)
        copied += len(chunk)
    if copied == 0:
        raise EmptySampleError
    return copied


def _write_chunk(
    chunk: bytes, destination: BinaryIO, observe: Callable[[bytes], None] | None
) -> None:
    if observe is not None:
        observe(chunk)
    destination.write(chunk)


class SampleStore:
    """Keeps samples as AES-encrypted zips (password `infected`) named after their SHA256."""

    def __init__(self, root: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.root = root
        self.max_bytes = max_bytes

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(settings.sample_store_path)

    async def save(self, stream: ByteSource, original_name: str) -> StoredSample:
        """Hash and store an upload without holding more than one chunk in memory."""
        incoming = await asyncio.to_thread(self._make_incoming_directory)
        try:
            plain = incoming / "plain"
            digests = await self._receive(stream, plain)
            stored = digests.stored_in(self.root)
            if not stored.path.exists():
                await asyncio.to_thread(self._encrypt, plain, original_name, incoming, stored.path)
            return stored
        finally:
            await asyncio.to_thread(shutil.rmtree, incoming, True)

    @asynccontextmanager
    async def open_plain(self, sha256: str) -> AsyncIterator[Path]:
        """A temporary plaintext copy of the sample, deleted when the block ends."""
        source = self._zip_path(sha256)
        directory = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="sample-"))
        try:
            plain = directory / FALLBACK_NAME
            await asyncio.to_thread(self._decrypt, source, plain)
            yield plain
        finally:
            await asyncio.to_thread(shutil.rmtree, directory, True)

    async def delete(self, sha256: str) -> None:
        await asyncio.to_thread(self._zip_path(sha256).unlink, True)

    def _make_incoming_directory(self) -> Path:
        self.root.mkdir(mode=PRIVATE_DIRECTORY, parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f"{_INCOMING}-", dir=self.root))

    async def _receive(self, stream: ByteSource, destination: Path) -> Digests:
        digests = Digests()
        with destination.open("xb") as plain:
            await copy_capped(stream, plain, self.max_bytes, digests.update)
        return digests

    def _zip_path(self, sha256: str) -> Path:
        if not _SHA256.fullmatch(sha256):
            raise ValueError(f"not a sha256 digest: {sha256!r}")
        return self.root / _zip_name(sha256)

    @staticmethod
    def _encrypt(plain: Path, original_name: str, incoming: Path, destination: Path) -> None:
        # Written under a temporary name and renamed, so a reader never sees a half-written zip.
        unfinished = incoming / "sample.zip"
        write_encrypted_zip(plain, safe_file_name(original_name), unfinished)
        os.replace(unfinished, destination)

    @staticmethod
    def _decrypt(source: Path, destination: Path) -> None:
        with pyzipper.AESZipFile(source) as archive:
            archive.setpassword(ZIP_PASSWORD)
            (member,) = archive.infolist()
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE)
            with archive.open(member) as packed, os.fdopen(fd, "wb") as plain:
                shutil.copyfileobj(packed, plain, CHUNK_SIZE)


def write_encrypted_zip(source: Path, arcname: str, destination: Path) -> None:
    """Packs `source` into a one-file AES zip (password `infected`), readable by its owner only."""
    with pyzipper.AESZipFile(
        destination, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as archive:
        archive.setpassword(ZIP_PASSWORD)
        archive.write(source, arcname=arcname)
    destination.chmod(PRIVATE_FILE)


def _zip_name(sha256: str) -> str:
    return f"{sha256}.zip"


def safe_file_name(original_name: str) -> str:
    name = PurePosixPath(original_name.replace("\\", "/")).name
    return name if name not in ("", ".", "..") else FALLBACK_NAME
