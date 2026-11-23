"""The small pure pieces of the SMB service: directory entries, the service table, kept state."""

import struct

import pytest

from lan_sim.services import smb_info as info
from lan_sim.services.smb_services import ServiceError, ServiceTable
from lan_sim.services.smb_state import SmbStates
from lan_sim.services.smb_store import Budget, Node


def entry(name: str, *, is_dir=False, size=0) -> info.DirectoryEntry:
    node = Node(name, is_dir, created=1, modified=2, data=bytearray(size))
    return info.DirectoryEntry(name, node)


@pytest.mark.parametrize(
    ("pattern", "name", "expected"),
    [
        ("*", "anything", True),
        ("", "anything", True),
        ("*.TXT", "readme.txt", True),
        ("read?e.txt", "README.txt", True),
        ("*.exe", "readme.txt", False),
        ("a" * 300, "a", False),
        ("<.txt", "x.txt", True),
    ],
)
def test_wildcards_match_like_dos(pattern, name, expected):
    assert info.matches(pattern, name) is expected


def test_directory_entries_are_chained_and_aligned():
    entries = [entry("a.txt"), entry("bb.txt", size=10), entry("c", is_dir=True)]
    packed, used = info.pack_directory_entries(info.DIR_BOTH, entries, 4096)
    assert used == 3
    offsets, position = [], 0
    while True:
        (step,) = struct.unpack_from("<I", packed, position)
        offsets.append(step)
        if not step:
            break
        position += step
        assert step % 8 == 0
    assert len(offsets) == 3


@pytest.mark.parametrize("info_class", sorted(info.NAME_ELEMENT_OFFSETS))
def test_the_name_sits_where_the_class_says_it_does(info_class):
    packed, _ = info.pack_directory_entries(info_class, [entry("probe.bin")], 4096)
    offset = info.NAME_ELEMENT_OFFSETS[info_class]
    assert packed[offset : offset + 18] == "probe.bin".encode("utf-16le")


def test_entries_stop_at_the_output_limit_and_report_how_many_fit():
    entries = [entry(f"file{n}.bin") for n in range(50)]
    packed, used = info.pack_directory_entries(info.DIR_DIRECTORY, entries, 500)
    assert 0 < used < 50
    assert len(packed) <= 500
    assert info.pack_directory_entries(info.DIR_DIRECTORY, entries, 10) == (b"", 0)


def test_unsupported_information_classes_are_reported_as_none():
    node = Node("x", False, created=1, modified=1)
    assert info.file_info(99, node, "x", 1) is None
    assert info.filesystem_info(99) is None


def test_the_service_table_starts_with_real_looking_services():
    names = [record.name for record in ServiceTable().listing()]
    assert {"Spooler", "EventLog"} <= set(names)


def test_services_are_created_once_and_found_without_case():
    table = ServiceTable()
    table.create("evil", "Evil", "C:\\evil.exe")
    assert table.get("EVIL").binary_path == "C:\\evil.exe"
    with pytest.raises(ServiceError) as duplicate:
        table.create("EVIL", "again", "x")
    assert duplicate.value.code == 1073
    table.delete("evil")
    with pytest.raises(ServiceError) as missing:
        table.get("evil")
    assert missing.value.code == 1060


@pytest.mark.parametrize("name", ["", "a\\b", "a/b", "x" * 300])
def test_service_names_that_could_mean_a_path_are_refused(name):
    with pytest.raises(ServiceError):
        ServiceTable().create(name, "d", "p")


def test_the_service_table_is_capped():
    table = ServiceTable()

    def fill():
        for number in range(1000):
            table.create(f"s{number}", "d", "p")

    with pytest.raises(ServiceError) as full:
        fill()
    assert full.value.code == 8


def test_state_is_kept_per_session_and_host_until_the_session_is_forgotten():
    states = SmbStates()
    first = states.host("one", "fs01.corp.local")
    assert states.host("one", "fs01.corp.local") is first
    assert states.host("one", "fs02.corp.local") is not first
    assert states.host("one", "fs01.corp.local").budget is first.budget
    other = states.host("two", "fs01.corp.local")
    states.forget("one")
    assert states.host("one", "fs01.corp.local") is not first
    assert states.host("two", "fs01.corp.local") is other
    states.forget("never-seen")


def test_every_session_gets_its_own_budget():
    states = SmbStates(budget_factory=lambda: Budget(byte_cap=10))
    assert states.host("a", "h").budget is not states.host("b", "h").budget
    assert states.host("a", "h").budget.byte_cap == 10
