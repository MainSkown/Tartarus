from typing import Any

from app.search.oversize import MAX_RAW_BYTES, with_capped_raw


def event_with_raw(raw: Any) -> dict[str, Any]:
    return {"event": {"id": "a"}, "tartarus": {"lane": "api", "raw": raw}}


def test_an_event_with_a_small_raw_record_is_returned_as_it_is() -> None:
    event = event_with_raw({"api": "NtCreateFile"})

    assert with_capped_raw(event) is event


def test_an_event_without_raw_is_returned_as_it_is() -> None:
    event = {"event": {"id": "a"}}

    assert with_capped_raw(event) is event


def test_an_oversized_raw_record_is_replaced_by_a_note_of_its_size() -> None:
    event = event_with_raw({"blob": "x" * (MAX_RAW_BYTES + 1)})

    capped = with_capped_raw(event)

    assert capped["tartarus"]["raw"]["truncated"] is True
    assert capped["tartarus"]["raw"]["original_bytes"] > MAX_RAW_BYTES
    assert capped["tartarus"]["lane"] == "api"
    assert event["tartarus"]["raw"]["blob"].startswith("x")


def test_a_raw_record_that_is_not_plain_json_is_measured_as_text() -> None:
    event = event_with_raw({"bytes": b"x" * (MAX_RAW_BYTES + 1)})

    assert with_capped_raw(event)["tartarus"]["raw"]["truncated"] is True
