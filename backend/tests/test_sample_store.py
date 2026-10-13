import hashlib
import os
import stat
from pathlib import Path

import pytest
import pyzipper

from app.config import Settings
from app.samples.store import (
    CHUNK_SIZE,
    EmptySampleError,
    SampleStore,
    SampleTooLargeError,
)

PASSWORD = b"infected"
CONTENT = os.urandom(CHUNK_SIZE * 2 + 1234)


class ChunkedUpload:
    """Serves bytes like an upload stream and fails if asked for more than one chunk at a time."""

    def __init__(self, content: bytes, fail_after: int | None = None) -> None:
        self._content = content
        self.offset = 0
        self._fail_after = fail_after
        self.largest_request = 0

    async def read(self, size: int) -> bytes:
        self.largest_request = max(self.largest_request, size)
        assert 0 < size <= CHUNK_SIZE, f"asked for {size} bytes at once"
        if self._fail_after is not None and self.offset >= self._fail_after:
            raise ConnectionResetError("client went away")
        chunk = self._content[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


@pytest.fixture
def store(tmp_path: Path) -> SampleStore:
    return SampleStore(tmp_path / "samples")


def everything_under(root: Path) -> list[Path]:
    return sorted(root.rglob("*")) if root.exists() else []


async def test_save_returns_the_hashes_and_size_of_the_content(store: SampleStore) -> None:
    stored = await store.save(ChunkedUpload(CONTENT), "evil.exe")

    assert stored.sha256 == hashlib.sha256(CONTENT).hexdigest()
    assert stored.sha1 == hashlib.sha1(CONTENT).hexdigest()  # noqa: S324
    assert stored.md5 == hashlib.md5(CONTENT).hexdigest()  # noqa: S324
    assert stored.size == len(CONTENT)


async def test_save_reads_the_stream_one_chunk_at_a_time(store: SampleStore) -> None:
    upload = ChunkedUpload(CONTENT)

    await store.save(upload, "evil.exe")

    assert upload.largest_request == CHUNK_SIZE


async def test_the_stored_file_is_named_after_the_hash_and_private(
    store: SampleStore, tmp_path: Path
) -> None:
    stored = await store.save(ChunkedUpload(CONTENT), "evil.exe")

    assert stored.path == tmp_path / "samples" / f"{stored.sha256}.zip"
    assert stat.S_IMODE(stored.path.stat().st_mode) == 0o600


async def test_the_stored_zip_needs_the_password_and_holds_the_original_name(
    store: SampleStore,
) -> None:
    stored = await store.save(ChunkedUpload(CONTENT), "evil.exe")

    with pyzipper.AESZipFile(stored.path) as archive:
        assert archive.namelist() == ["evil.exe"]
        with pytest.raises(RuntimeError):
            archive.read("evil.exe")
        archive.setpassword(PASSWORD)
        assert archive.read("evil.exe") == CONTENT


async def test_the_content_is_not_readable_from_the_stored_file(store: SampleStore) -> None:
    stored = await store.save(ChunkedUpload(CONTENT), "evil.exe")

    assert CONTENT[:64] not in stored.path.read_bytes()


@pytest.mark.parametrize(
    ("original_name", "stored_name"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\bob\\dropper.exe", "dropper.exe"),
        ("", "sample"),
        ("..", "sample"),
    ],
)
async def test_the_name_inside_the_zip_is_only_a_safe_file_name(
    store: SampleStore, original_name: str, stored_name: str
) -> None:
    stored = await store.save(ChunkedUpload(b"data"), original_name)

    with pyzipper.AESZipFile(stored.path) as archive:
        assert archive.namelist() == [stored_name]


async def test_saving_the_same_content_again_changes_nothing(store: SampleStore) -> None:
    first = await store.save(ChunkedUpload(CONTENT), "evil.exe")
    before = first.path.read_bytes()

    second = await store.save(ChunkedUpload(CONTENT), "renamed.exe")

    assert second == first
    assert first.path.read_bytes() == before
    assert [path.name for path in everything_under(first.path.parent)] == [first.path.name]


async def test_no_partial_file_is_left_when_the_upload_breaks_off(
    store: SampleStore, tmp_path: Path
) -> None:
    with pytest.raises(ConnectionResetError):
        await store.save(ChunkedUpload(CONTENT, fail_after=CHUNK_SIZE), "evil.exe")

    assert [path for path in everything_under(tmp_path / "samples") if path.is_file()] == []


async def test_no_partial_file_is_left_when_the_zip_cannot_be_written(
    store: SampleStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pyzipper.AESZipFile, "write", broken)

    with pytest.raises(OSError, match="disk full"):
        await store.save(ChunkedUpload(b"data"), "evil.exe")

    assert [path for path in everything_under(tmp_path / "samples") if path.is_file()] == []


async def test_an_empty_upload_is_refused_and_stores_nothing(
    store: SampleStore, tmp_path: Path
) -> None:
    with pytest.raises(EmptySampleError):
        await store.save(ChunkedUpload(b""), "empty.exe")

    assert [path for path in everything_under(tmp_path / "samples") if path.is_file()] == []


async def test_an_upload_over_the_limit_is_refused_and_stops_being_read(tmp_path: Path) -> None:
    store = SampleStore(tmp_path / "samples", max_bytes=CHUNK_SIZE)
    upload = ChunkedUpload(CONTENT)

    with pytest.raises(SampleTooLargeError):
        await store.save(upload, "huge.bin")

    assert upload.offset <= CHUNK_SIZE * 2
    assert [path for path in everything_under(tmp_path / "samples") if path.is_file()] == []


async def test_open_plain_yields_the_original_content(store: SampleStore) -> None:
    stored = await store.save(ChunkedUpload(CONTENT), "evil.exe")

    async with store.open_plain(stored.sha256) as plain:
        assert plain.read_bytes() == CONTENT


async def test_the_plain_copy_is_private_and_removed_on_exit(store: SampleStore) -> None:
    stored = await store.save(ChunkedUpload(b"data"), "evil.exe")

    async with store.open_plain(stored.sha256) as plain:
        assert stat.S_IMODE(plain.stat().st_mode) == 0o600
        assert stat.S_IMODE(plain.parent.stat().st_mode) == 0o700
    assert not plain.parent.exists()


async def test_the_plain_copy_is_removed_when_the_block_raises(store: SampleStore) -> None:
    stored = await store.save(ChunkedUpload(b"data"), "evil.exe")

    with pytest.raises(RuntimeError, match="upload to CAPE failed"):
        async with store.open_plain(stored.sha256) as plain:
            raise RuntimeError("upload to CAPE failed")

    assert not plain.parent.exists()


async def test_open_plain_of_an_unknown_sample_raises_file_not_found(store: SampleStore) -> None:
    with pytest.raises(FileNotFoundError):
        async with store.open_plain("0" * 64):
            pass


async def test_delete_removes_the_stored_file_and_tolerates_a_missing_one(
    store: SampleStore,
) -> None:
    stored = await store.save(ChunkedUpload(b"data"), "evil.exe")

    await store.delete(stored.sha256)
    await store.delete(stored.sha256)

    assert not stored.path.exists()


def test_a_store_is_built_from_the_sample_store_setting(settings: Settings) -> None:
    assert SampleStore.from_settings(settings).root == settings.sample_store_path


@pytest.mark.parametrize("not_a_hash", ["../escape", "abc", "G" * 64, ""])
async def test_a_name_that_is_not_a_sha256_never_reaches_the_file_system(
    store: SampleStore, not_a_hash: str
) -> None:
    with pytest.raises(ValueError, match="sha256"):
        await store.delete(not_a_hash)
    with pytest.raises(ValueError, match="sha256"):
        async with store.open_plain(not_a_hash):
            pass


async def test_opening_a_sample_that_is_not_stored_raises_file_not_found(
    store: SampleStore,
) -> None:
    # The runner treats exactly this exception as "the stored sample is missing" and fails the
    # analysis with a clear message; any other exception type would be reported as unexpected.
    with pytest.raises(FileNotFoundError):
        async with store.open_plain("a" * 64):
            pass
