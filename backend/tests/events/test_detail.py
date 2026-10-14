from typing import Any

from app.events.detail import (
    MAX_RELATED,
    find_body,
    read_detail,
    referenced_by_body,
    references_body,
    related_ids,
)
from app.views.event_fields import WITHOUT_RAW

TIME_ORDER = [{"@timestamp": "asc"}, {"event.sequence": "asc"}, {"event.id": "asc"}]


def source(event_id: str, **sections: Any) -> dict[str, Any]:
    return {
        "@timestamp": "2026-10-13T12:12:41.383Z",
        "event": {"id": event_id, "sequence": 1},
        "tartarus": {"lane": "api", "summary": event_id, "raw": {"k": "v"}},
        **sections,
    }


def listing(*sources: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    return {
        "hits": {
            "total": {"value": len(sources) if total is None else total},
            "hits": [{"_source": item} for item in sources],
        }
    }


def test_the_event_is_found_by_its_exact_id_with_its_raw_record() -> None:
    body = find_body("processes/12:34")

    assert body["query"] == {"ids": {"values": ["processes/12:34"]}}
    assert body["size"] == 1
    assert "_source" not in body


def test_the_events_a_detection_names_are_fetched_by_id_in_time_order() -> None:
    body = references_body(["a", "b"])

    assert body["query"] == {"ids": {"values": ["a", "b"]}}
    assert body["size"] == MAX_RELATED == 50
    assert body["sort"] == TIME_ORDER
    assert body["track_total_hits"] is True
    assert body["_source"] == WITHOUT_RAW


def test_the_detections_that_name_an_event_are_found_by_the_lowercased_id() -> None:
    body = referenced_by_body("Proc/ABC:1")

    assert body["query"] == {"bool": {"filter": [{"term": {"related.events": "proc/abc:1"}}]}}
    assert body["sort"] == TIME_ORDER
    assert body["size"] == MAX_RELATED


def test_the_ids_an_event_names_are_listed_whether_one_or_many() -> None:
    assert related_ids(source("x", related={"events": ["a", "b"]})) == ["a", "b"]
    assert related_ids(source("x", related={"events": "a"})) == ["a"]
    assert related_ids(source("x")) == []


def test_the_detail_has_the_event_the_whole_source_and_both_directions() -> None:
    found = source("alert-1", related={"events": ["a"]})

    detail = read_detail(found, listing(source("a"), total=1), listing(source("b"), total=9))

    assert detail.event.id == "alert-1"
    assert detail.source["tartarus"]["raw"] == {"k": "v"}
    assert [event.id for event in detail.related.references.items] == ["a"]
    assert detail.related.references.total == 1
    assert [event.id for event in detail.related.referenced_by.items] == ["b"]
    assert detail.related.referenced_by.total == 9
