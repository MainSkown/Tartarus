"""Root writes into folders `cape` owns: `analysis_files` never follows a link `cape` may plant.

`cape` owns every folder from `storage/analyses/` down and can swap any of them for a symlink at any
moment, so what root writes goes through directory descriptors opened without following links.
"""

import errno
import importlib
import os
import stat

import pytest
from test_control_http import BIN  # noqa: F401 - importing it puts bin/ on sys.path

analysis_files = importlib.import_module("analysis_files")

DUMP = b"MEMORY" * 1000


@pytest.fixture
def staged(tmp_path):
    root_only = tmp_path / "staging"
    root_only.mkdir()
    file = root_only / "7-abc.dmp"
    file.write_bytes(DUMP)
    return file


@pytest.fixture
def storage(tmp_path):
    analysis = tmp_path / "storage" / "analyses" / "7"
    analysis.mkdir(parents=True)
    return tmp_path / "storage"


@pytest.fixture
def victim(tmp_path):
    folder = tmp_path / "victim"
    folder.mkdir()
    (folder / "important").write_text("keep")
    return folder


def test_the_dump_lands_in_the_analysis_folder_readable_by_everyone(staged, storage):
    analysis_files.place_dump(staged, storage, 7)

    placed = storage / "analyses" / "7" / "memory.dmp"
    assert placed.read_bytes() == DUMP
    assert stat.S_IMODE(placed.stat().st_mode) == 0o644


def test_the_placed_file_is_handed_to_the_owner_of_the_analysis_folder(
    staged, storage, monkeypatch
):
    handed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "fchown", lambda _fd, uid, gid: handed.append((uid, gid)))
    folder = (storage / "analyses" / "7").stat()

    analysis_files.place_dump(staged, storage, 7)

    assert handed == [(folder.st_uid, folder.st_gid)]


def test_an_analysis_folder_that_is_a_symlink_is_refused_and_nothing_is_written(
    staged, storage, victim
):
    (storage / "analyses" / "7").rmdir()
    (storage / "analyses" / "7").symlink_to(victim)

    with pytest.raises(NotADirectoryError):
        analysis_files.place_dump(staged, storage, 7)

    assert sorted(path.name for path in victim.iterdir()) == ["important"]


def test_an_analyses_folder_that_is_a_symlink_is_refused(staged, storage, victim):
    (victim / "7").mkdir()
    analyses = storage / "analyses"
    (analyses / "7").rmdir()
    analyses.rmdir()
    analyses.symlink_to(victim)

    with pytest.raises(NotADirectoryError):
        analysis_files.place_dump(staged, storage, 7)

    assert sorted(path.name for path in (victim / "7").iterdir()) == []


def test_a_dump_name_that_is_a_symlink_is_not_followed(staged, storage, victim):
    (storage / "analyses" / "7" / "memory.dmp").symlink_to(victim / "important")

    with pytest.raises(FileExistsError):
        analysis_files.place_dump(staged, storage, 7)

    assert (victim / "important").read_text() == "keep"


def test_a_dump_that_is_already_there_is_not_overwritten(staged, storage):
    existing = storage / "analyses" / "7" / "memory.dmp"
    existing.write_bytes(b"first")

    with pytest.raises(FileExistsError):
        analysis_files.place_dump(staged, storage, 7)

    assert existing.read_bytes() == b"first"


def test_a_missing_analysis_folder_is_an_error_and_is_not_created(staged, storage):
    with pytest.raises(FileNotFoundError):
        analysis_files.place_dump(staged, storage, 8)

    assert not (storage / "analyses" / "8").exists()


def test_a_folder_swapped_for_a_symlink_while_copying_does_not_redirect_the_write(
    staged, storage, victim, monkeypatch
):
    real_sendfile = os.sendfile
    analyses = storage / "analyses"

    def swap_then_copy(*arguments):
        if not (analyses / "7.moved").exists():
            (analyses / "7").rename(analyses / "7.moved")
            (analyses / "7").symlink_to(victim)
        return real_sendfile(*arguments)

    monkeypatch.setattr(os, "sendfile", swap_then_copy)

    analysis_files.place_dump(staged, storage, 7)

    assert sorted(path.name for path in victim.iterdir()) == ["important"]
    assert (analyses / "7.moved" / "memory.dmp").read_bytes() == DUMP


def test_a_copy_that_fails_leaves_no_partial_dump_behind(staged, storage, monkeypatch):
    def disk_full(*_arguments):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "sendfile", disk_full)

    with pytest.raises(OSError, match="No space"):
        analysis_files.place_dump(staged, storage, 7)

    assert list((storage / "analyses" / "7").iterdir()) == []


def test_a_dump_larger_than_one_sendfile_call_copies_completely(staged, storage, monkeypatch):
    real_sendfile = os.sendfile
    monkeypatch.setattr(
        os, "sendfile", lambda out, source, offset, _count: real_sendfile(out, source, offset, 4096)
    )

    analysis_files.place_dump(staged, storage, 7)

    assert (storage / "analyses" / "7" / "memory.dmp").read_bytes() == DUMP


def test_a_free_slot_is_one_in_an_existing_folder_without_a_dump(storage):
    analysis_files.require_free_dump_slot(storage, 7)


def test_a_slot_is_not_free_when_the_dump_is_there_or_something_stands_in_its_place(
    storage, victim
):
    (storage / "analyses" / "7" / "memory.dmp").symlink_to(victim / "important")

    with pytest.raises(FileExistsError):
        analysis_files.require_free_dump_slot(storage, 7)


def test_a_slot_is_not_free_in_a_folder_that_is_missing_or_a_symlink(storage, victim):
    (storage / "analyses" / "8").symlink_to(victim)

    with pytest.raises(FileNotFoundError):
        analysis_files.require_free_dump_slot(storage, 9)
    with pytest.raises(NotADirectoryError):
        analysis_files.require_free_dump_slot(storage, 8)
