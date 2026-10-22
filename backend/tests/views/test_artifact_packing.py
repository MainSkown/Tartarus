import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.views import artifacts
from app.views.artifacts import ArtifactFile, TemporarySpaceError, pack_for_download


@pytest.fixture
def artifact(tmp_path: Path) -> ArtifactFile:
    path = tmp_path / "memory.dmp"
    path.write_bytes(b"\x00" * 4096)
    return ArtifactFile(path, "memory.dmp")


async def test_a_file_that_fits_the_temporary_space_is_packed_into_a_zip(
    artifact: ArtifactFile,
) -> None:
    packed = await pack_for_download(artifact)

    try:
        assert packed.stat().st_size > 0
    finally:
        packed.unlink()


async def test_a_file_larger_than_the_free_temporary_space_is_refused_and_nothing_is_written(
    artifact: ArtifactFile, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(artifacts.tempfile, "tempdir", str(tmp_path / "scratch"))
    (tmp_path / "scratch").mkdir()
    free = artifact.path.stat().st_size - 1
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=free))

    with pytest.raises(TemporarySpaceError):
        await pack_for_download(artifact)

    assert list((tmp_path / "scratch").iterdir()) == []
