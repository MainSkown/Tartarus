"""Root writes into folders `cape` owns: `analysis_files` never follows a link `cape` may plant.

`cape` owns every folder from `storage/analyses/` down and can swap any of them for a symlink at any
moment, so what root writes goes through directory descriptors opened without following links.
"""

import errno
import importlib
import os
import stat

import pytest
from hostile_files import KINDS, bounded, plant
from test_control_http import BIN  # noqa: F401 - importing it puts bin/ on sys.path

from guest_engine.lan_session import NotARegularFileError

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


# --- place_once: a file in a folder of the analysis, the first copy wins -----------------------

LIMIT = 1 << 20


def place_once(staged, storage, task_id=7, limit=LIMIT):
    placement = analysis_files.Placement("lansim", "events.jsonl", limit)
    return analysis_files.place_once(staged, storage, task_id, placement)


@pytest.fixture
def events(tmp_path):
    file = tmp_path / "staging" / "task-1.jsonl"
    file.parent.mkdir()
    file.write_bytes(b'{"type":"session-end"}\n')
    return file


def test_the_file_lands_in_a_new_folder_of_the_analysis_readable_by_everyone(events, storage):
    assert place_once(events, storage) is True

    folder = storage / "analyses" / "7" / "lansim"
    assert (folder / "events.jsonl").read_bytes() == b'{"type":"session-end"}\n'
    assert stat.S_IMODE((folder / "events.jsonl").stat().st_mode) == 0o644
    assert stat.S_IMODE(folder.stat().st_mode) == 0o755
    assert [path.name for path in folder.iterdir()] == ["events.jsonl"]


def test_the_folder_and_the_file_are_handed_to_the_owner_of_the_analysis_folder(
    events, storage, monkeypatch
):
    handed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "fchown", lambda _fd, uid, gid: handed.append((uid, gid)))
    owner = (storage / "analyses" / "7").stat()

    place_once(events, storage)

    assert handed == [(owner.st_uid, owner.st_gid)] * 2


def test_an_existing_file_is_never_overwritten_and_nothing_is_left_beside_it(events, storage):
    folder = storage / "analyses" / "7" / "lansim"
    folder.mkdir()
    (folder / "events.jsonl").write_bytes(b"first")

    assert place_once(events, storage) is False

    assert [(path.name, path.read_bytes()) for path in folder.iterdir()] == [
        ("events.jsonl", b"first")
    ]


def test_a_second_placement_after_the_first_changes_nothing(events, storage):
    place_once(events, storage)
    events.write_bytes(b"second")

    assert place_once(events, storage) is False

    assert (storage / "analyses" / "7" / "lansim" / "events.jsonl").read_bytes() != b"second"


def test_a_name_that_is_a_symlink_is_not_followed_and_counts_as_taken(events, storage, victim):
    folder = storage / "analyses" / "7" / "lansim"
    folder.mkdir()
    (folder / "events.jsonl").symlink_to(victim / "important")

    assert place_once(events, storage) is False

    assert (victim / "important").read_text() == "keep"


def test_a_missing_analysis_folder_is_an_error_and_is_not_created_for_a_placed_file(
    events, storage
):
    with pytest.raises(FileNotFoundError):
        place_once(events, storage, task_id=8)

    assert not (storage / "analyses" / "8").exists()


def test_an_analysis_folder_that_is_a_symlink_is_refused_and_nothing_is_written_for_a_placed_file(
    events, storage, victim
):
    (storage / "analyses" / "8").symlink_to(victim)

    with pytest.raises(NotADirectoryError):
        place_once(events, storage, task_id=8)

    assert sorted(path.name for path in victim.iterdir()) == ["important"]


def test_a_target_folder_that_is_a_symlink_is_refused_and_nothing_is_written(
    events, storage, victim
):
    (storage / "analyses" / "7" / "lansim").symlink_to(victim)

    with pytest.raises(OSError):  # noqa: PT011 - ELOOP or ENOTDIR, whichever the kernel says
        place_once(events, storage)

    assert sorted(path.name for path in victim.iterdir()) == ["important"]


def test_a_folder_swapped_for_a_symlink_while_copying_does_not_redirect_the_write_for_a_placed_file(
    events, storage, victim, monkeypatch
):
    real_read = os.read
    analyses = storage / "analyses"

    def swap_then_read(*arguments):
        if not (analyses / "7.moved").exists():
            (analyses / "7").rename(analyses / "7.moved")
            (analyses / "7").symlink_to(victim)
        return real_read(*arguments)

    monkeypatch.setattr(os, "read", swap_then_read)

    place_once(events, storage)

    assert sorted(path.name for path in victim.iterdir()) == ["important"]
    assert (analyses / "7.moved" / "lansim" / "events.jsonl").exists()


def test_a_staged_file_over_the_limit_is_refused_and_leaves_nothing(events, storage):
    events.write_bytes(b"x" * 101)

    with pytest.raises(analysis_files.FileTooLargeError):
        place_once(events, storage, limit=100)

    assert not (storage / "analyses" / "7" / "lansim").exists()


def test_a_staged_file_of_exactly_the_limit_is_placed(events, storage):
    events.write_bytes(b"x" * 100)

    assert place_once(events, storage, limit=100) is True


def test_a_staged_file_that_grows_past_the_limit_while_it_is_copied_is_refused(
    events, storage, monkeypatch
):
    real_read = os.read
    monkeypatch.setattr(os, "read", lambda descriptor, count: real_read(descriptor, count) * 50)
    events.write_bytes(b"x" * 10)

    with pytest.raises(analysis_files.FileTooLargeError):
        place_once(events, storage, limit=100)

    assert list((storage / "analyses" / "7" / "lansim").iterdir()) == []


def test_a_staged_symlink_is_not_followed(storage, tmp_path, victim):
    link = tmp_path / "staging-link.jsonl"
    link.symlink_to(victim / "important")

    with pytest.raises(OSError):  # noqa: PT011 - ELOOP
        place_once(link, storage)

    assert not (storage / "analyses" / "7" / "lansim" / "events.jsonl").exists()


def test_a_staged_path_that_is_not_a_regular_file_is_refused_without_blocking(storage, tmp_path):
    pipe = tmp_path / "pipe.jsonl"
    os.mkfifo(pipe)

    with pytest.raises(NotARegularFileError):
        place_once(pipe, storage)
    with pytest.raises(NotARegularFileError):
        place_once(tmp_path, storage)


@pytest.mark.parametrize("kind", KINDS)
def test_anything_planted_in_the_staged_files_place_ends_in_an_error_within_a_bound(
    storage, tmp_path, kind
):
    staged = tmp_path / "planted.jsonl"
    plant(kind, staged, tmp_path / "secret")

    with pytest.raises(OSError):  # noqa: PT011 - which one depends on the kind
        bounded(place_once, staged, storage)

    assert not (storage / "analyses" / "7" / "lansim").exists()


def test_a_staged_file_that_really_grows_while_the_folder_is_prepared_is_cut_at_the_limit(
    events, storage, monkeypatch
):
    original = analysis_files._make_folder

    def grow_then_make(*arguments):
        with events.open("ab") as handle:
            handle.write(b"x" * 500)
        original(*arguments)

    monkeypatch.setattr(analysis_files, "_make_folder", grow_then_make)

    with pytest.raises(analysis_files.FileTooLargeError):
        place_once(events, storage, limit=100)

    assert list((storage / "analyses" / "7" / "lansim").iterdir()) == []


def test_the_name_swapped_for_a_link_after_the_open_still_copies_what_was_opened(
    events, storage, tmp_path, monkeypatch
):
    secret = tmp_path / "secret"
    secret.write_bytes(b"not for an analysis")
    original = analysis_files._make_folder

    def swap_then_make(*arguments):
        events.unlink()
        events.symlink_to(secret)
        original(*arguments)

    monkeypatch.setattr(analysis_files, "_make_folder", swap_then_make)

    place_once(events, storage)

    placed = storage / "analyses" / "7" / "lansim" / "events.jsonl"
    assert placed.read_bytes() == b'{"type":"session-end"}\n'


def test_a_folder_name_taken_by_a_file_is_an_error_not_an_exception_of_another_kind(
    events, storage
):
    (storage / "analyses" / "7" / "lansim").write_text("in the way")

    with pytest.raises(OSError):  # noqa: PT011 - NotADirectoryError
        place_once(events, storage)


def test_a_missing_staged_file_is_a_file_not_found_and_creates_no_folder(storage, tmp_path):
    with pytest.raises(FileNotFoundError):
        place_once(tmp_path / "absent.jsonl", storage)

    assert not (storage / "analyses" / "7" / "lansim").exists()


def test_a_write_that_fails_leaves_no_file_and_no_temporary(events, storage, monkeypatch):
    def disk_full(*_arguments):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "write", disk_full)

    with pytest.raises(OSError, match="No space"):
        place_once(events, storage)

    assert list((storage / "analyses" / "7" / "lansim").iterdir()) == []
