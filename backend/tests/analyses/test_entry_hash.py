from typing import Any

import pytest

from app.analyses.entry_hash import entry_sha256

TEMP = r"C:\Users\Megan\AppData\Local\Temp"
HASH = "4b322b00" * 8
OTHER_HASH = "ab" * 32


def started(
    executable: str, sha256: str | None = HASH, at: str = "2026-10-18T22:43:50.000Z"
) -> dict[str, Any]:
    process: dict[str, Any] = {"executable": executable}
    if sha256 is not None:
        process["hash"] = {"sha256": sha256}
    return {"@timestamp": at, "event": {"action": "process-created"}, "process": process}


def test_the_hash_of_the_process_started_from_the_entry_in_temp() -> None:
    assert entry_sha256([started(rf"{TEMP}\payload.exe")], "payload.exe") == HASH


def test_a_nested_entry_matches_the_nested_path_under_temp() -> None:
    assert entry_sha256([started(rf"{TEMP}\dir\x.exe")], "dir/x.exe") == HASH


def test_a_nested_entry_does_not_match_a_file_of_the_same_name_in_temp_itself() -> None:
    assert entry_sha256([started(rf"{TEMP}\x.exe")], "dir/x.exe") is None


def test_a_plain_entry_does_not_match_the_same_name_in_a_subdirectory() -> None:
    assert entry_sha256([started(rf"{TEMP}\dir\x.exe")], "x.exe") is None


def test_the_comparison_ignores_case() -> None:
    event = started(r"C:\Users\Megan\AppData\Local\TEMP\PAYLOAD.EXE")

    assert entry_sha256([event], "payload.exe") == HASH


def test_the_earliest_of_two_processes_from_the_entry_wins() -> None:
    later = started(rf"{TEMP}\payload.exe", OTHER_HASH, at="2026-10-18T22:44:00.000Z")
    earlier = started(rf"{TEMP}\payload.exe", HASH, at="2026-10-18T22:43:50.000Z")

    assert entry_sha256([later, earlier], "payload.exe") == HASH


def test_a_process_outside_temp_is_ignored() -> None:
    assert entry_sha256([started(r"C:\Windows\System32\payload.exe")], "payload.exe") is None


def test_a_decoy_of_the_same_base_name_elsewhere_does_not_hide_the_entry() -> None:
    decoy = started(r"C:\Windows\payload.exe", OTHER_HASH, at="2026-10-18T22:43:40.000Z")
    real = started(rf"{TEMP}\payload.exe", HASH, at="2026-10-18T22:43:50.000Z")

    assert entry_sha256([decoy, real], "payload.exe") == HASH


def test_a_directory_that_only_ends_in_temp_is_not_the_temp_directory() -> None:
    assert entry_sha256([started(r"C:\Users\Megan\Notemp\payload.exe")], "payload.exe") is None


def test_no_process_from_the_entry_is_none() -> None:
    assert entry_sha256([started(rf"{TEMP}\other.exe")], "payload.exe") is None


def test_no_events_is_none() -> None:
    assert entry_sha256([], "payload.exe") is None


def test_the_earliest_process_without_a_hash_is_none_and_not_a_later_hash() -> None:
    unhashed = started(rf"{TEMP}\payload.exe", None, at="2026-10-18T22:43:50.000Z")
    hashed = started(rf"{TEMP}\payload.exe", HASH, at="2026-10-18T22:44:00.000Z")

    assert entry_sha256([hashed, unhashed], "payload.exe") is None


@pytest.mark.parametrize("event", [{"@timestamp": "2026-10-18T22:43:50.000Z"}, {"process": {}}])
def test_an_event_without_an_executable_is_ignored(event: dict[str, Any]) -> None:
    assert entry_sha256([event], "payload.exe") is None
