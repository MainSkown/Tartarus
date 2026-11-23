"""The in-memory file store behind the shares: strict names, caps, and nothing on the host."""

import os

import pytest
from impacket import nt_errors

from lan_sim.services.smb_store import (
    FILE_CAP,
    Budget,
    StoreError,
    VirtualShare,
    new_share,
    normalize_path,
)

MIB = 1024 * 1024
CREATE, OPEN, OPEN_IF, OVERWRITE_IF, SUPERSEDE = 2, 1, 3, 5, 0


def share(budget=None) -> VirtualShare:
    return new_share("C$", budget or Budget(), now=1)


def status_of(call) -> int:
    with pytest.raises(StoreError) as caught:
        call()
    return caught.value.status


@pytest.mark.parametrize(
    ("raw", "parts"),
    [
        ("", ()),
        ("\\", ()),
        ("Windows", ("Windows",)),
        ("\\Windows\\System32\\", ("Windows", "System32")),
        ("a b\\c.txt", ("a b", "c.txt")),
        ("Ünï\\ファイル", ("Ünï", "ファイル")),
    ],
)
def test_normalize_path_splits_on_backslashes(raw, parts):
    assert normalize_path(raw) == parts


@pytest.mark.parametrize(
    "raw",
    [
        "..",
        "..\\..\\Windows",
        "Windows\\..\\..",
        "a\\..\\b",
        ".",
        "a\\.\\b",
        "C:\\Windows",
        "C:",
        "evil.txt:stream",
        "evil.txt::$DATA",
        "a\x00b",
        "a\\\\b",
        "a/b",
        "a*b",
        "a?b",
        "a<b",
        'a"b',
        "a|b",
        "a\x01b",
        "x" * 300,
        "\\".join(["a"] * 100),
        "x" * 5000,
    ],
)
def test_normalize_path_refuses_what_must_never_reach_the_store(raw):
    assert status_of(lambda: normalize_path(raw)) == nt_errors.STATUS_OBJECT_NAME_INVALID


def test_a_new_share_looks_alive():
    tree = share()
    assert tree.resolve(("Windows", "System32")).is_dir
    assert tree.resolve(("README.txt",)).data
    assert [n.name for n in tree.children(tree.root)][:1]


def test_lookup_ignores_case_and_keeps_the_stored_spelling():
    tree = share()
    assert tree.resolve(("wINDOWS",)).name == "Windows"


def test_create_then_open_returns_the_same_node():
    tree = share()
    node, action = tree.open(("evil.exe",), CREATE, now=2)
    assert action == "created"
    same, action = tree.open(("EVIL.EXE",), OPEN, now=3)
    assert same is node
    assert action == "opened"


def test_create_of_an_existing_name_collides():
    tree = share()
    tree.open(("a.txt",), CREATE, now=2)
    assert status_of(lambda: tree.open(("a.txt",), CREATE, now=3)) == (
        nt_errors.STATUS_OBJECT_NAME_COLLISION
    )


def test_open_missing_name_and_missing_parent_differ():
    tree = share()
    assert status_of(lambda: tree.open(("nope.txt",), OPEN, now=1)) == (
        nt_errors.STATUS_OBJECT_NAME_NOT_FOUND
    )
    assert status_of(lambda: tree.open(("nodir", "x.txt"), CREATE, now=1)) == (
        nt_errors.STATUS_OBJECT_PATH_NOT_FOUND
    )
    assert status_of(lambda: tree.open(("nodir", "x.txt"), OPEN, now=1)) == (
        nt_errors.STATUS_OBJECT_PATH_NOT_FOUND
    )


def test_a_file_cannot_be_a_parent():
    tree = share()
    tree.open(("f",), CREATE, now=1)
    assert status_of(lambda: tree.open(("f", "g"), CREATE, now=1)) == (
        nt_errors.STATUS_OBJECT_PATH_NOT_FOUND
    )


def test_overwrite_if_empties_an_existing_file():
    tree = share()
    node, _ = tree.open(("a",), CREATE, now=1)
    tree.write(node, 0, b"hello", now=1)
    node, action = tree.open(("a",), OVERWRITE_IF, now=2)
    assert action == "overwritten"
    assert len(node.data) == 0


def test_directories_are_created_and_listed():
    tree = share()
    tree.make_directory(("drop",), now=1)
    tree.open(("drop", "b.txt"), CREATE, now=1)
    tree.open(("drop", "a.txt"), CREATE, now=1)
    names = [n.name for n in tree.children(tree.resolve(("drop",)))]
    assert names == ["a.txt", "b.txt"]


def test_write_then_read_round_trips_and_extends_with_zeroes():
    tree = share()
    node, _ = tree.open(("a",), CREATE, now=1)
    assert tree.write(node, 0, b"abc", now=1) == 3
    assert tree.write(node, 6, b"xyz", now=1) == 3
    assert tree.read(node, 0, 100) == b"abc\x00\x00\x00xyz"
    assert tree.read(node, 7, 100) == b"yz"
    assert tree.read(node, 100, 5) == b""


def test_a_file_stops_storing_at_the_per_file_cap():
    tree = share()
    node, _ = tree.open(("big",), CREATE, now=1)
    assert tree.write(node, 0, b"x" * (FILE_CAP - 10), now=1) == FILE_CAP - 10
    assert tree.write(node, FILE_CAP - 10, b"y" * 100, now=1) == 10
    assert tree.write(node, FILE_CAP, b"z", now=1) == 0
    assert len(node.data) == FILE_CAP


def test_a_far_offset_does_not_allocate():
    tree = share()
    node, _ = tree.open(("sparse",), CREATE, now=1)
    assert tree.write(node, 2**40, b"x", now=1) == 0
    assert len(node.data) == 0


def test_the_session_budget_is_shared_between_shares_and_given_back_on_delete():
    budget = Budget(byte_cap=3 * MIB)
    first, second = share(budget), new_share("ADMIN$", budget, now=1)
    a, _ = first.open(("a",), CREATE, now=1)
    b, _ = second.open(("b",), CREATE, now=1)
    assert first.write(a, 0, b"x" * (2 * MIB), now=1) == 2 * MIB
    assert second.write(b, 0, b"y" * (2 * MIB), now=1) == MIB
    first.remove(("a",))
    assert second.write(b, MIB, b"y" * MIB, now=1) == MIB


def test_the_node_count_is_capped():
    tree = share(Budget(node_cap=20))

    def fill():
        for number in range(100):
            tree.open((f"f{number}",), CREATE, now=1)

    assert status_of(fill) == nt_errors.STATUS_DISK_FULL


def test_remove_refuses_a_directory_that_is_not_empty():
    tree = share()
    assert status_of(lambda: tree.remove(("Windows",))) == nt_errors.STATUS_DIRECTORY_NOT_EMPTY
    assert status_of(lambda: tree.remove(("ghost",))) == nt_errors.STATUS_OBJECT_NAME_NOT_FOUND
    assert status_of(lambda: tree.remove(())) == nt_errors.STATUS_ACCESS_DENIED


def test_rename_moves_a_node_and_refuses_collisions():
    tree = share()
    node, _ = tree.open(("a",), CREATE, now=1)
    tree.open(("b",), CREATE, now=1)
    assert status_of(lambda: tree.rename(("a",), ("b",), replace=False, now=2)) == (
        nt_errors.STATUS_OBJECT_NAME_COLLISION
    )
    tree.rename(("a",), ("Windows", "c"), replace=False, now=2)
    assert tree.resolve(("Windows", "c")) is node
    assert tree.resolve(("a",)) is None
    assert node.name == "c"


def test_a_directory_cannot_move_into_itself():
    tree = share()
    assert (
        status_of(
            lambda: tree.rename(("Windows",), ("Windows", "System32", "x"), replace=False, now=1)
        )
        == nt_errors.STATUS_ACCESS_DENIED
    )


def test_nothing_is_ever_created_on_the_host(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tree = share()
    node, _ = tree.open(("evil.exe",), CREATE, now=1)
    tree.write(node, 0, b"MZ" * 100, now=1)
    tree.make_directory(("dir",), now=1)
    assert os.listdir(tmp_path) == []
