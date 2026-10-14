from typing import Any

import pytest

from app.errors import ApiError
from app.events.cursor import encode_cursor
from app.events.event_model import EVENT_SOURCE_FIELDS, event_from_source
from app.events.search import build_search_body, read_search_response
from app.schemas.events_api import EventFilter, SearchRequest
from app.views.event_fields import WITHOUT_RAW, dig


def hit(number: int) -> dict[str, Any]:
    return {
        "_source": {
            "@timestamp": "2026-10-13T12:12:41.383Z",
            "event": {"id": f"id-{number}", "sequence": number},
        },
        "sort": [1791892361383, number, f"id-{number}"],
    }


def full_source() -> dict[str, Any]:
    return {
        "@timestamp": "2026-10-13T12:12:41.383Z",
        "event": {
            "id": "x",
            "sequence": 1,
            "kind": "event",
            "category": ["file"],
            "action": "a",
            "module": "m",
            "dataset": "d",
            "severity": 2,
            "type": ["creation"],
        },
        "tartarus": {"lane": "file", "summary": "s", "phase": "final"},
        "process": {"pid": 1, "name": "n", "entity_id": "e", "command_line": "c"},
        "api": {"name": "NtX", "status": True},
        "rule": {"name": "r", "ruleset": "cape", "id": "7"},
        "destination": {"ip": "1.2.3.4", "port": 80, "domain": "a.example", "bytes": 5},
        "dns": {"question": {"name": "a.example", "type": "A"}},
        "url": {"full": "http://a.example", "path": "/"},
        "file": {"path": "C:\\a", "name": "a"},
        "registry": {"path": "HKLM\\k", "key": "k"},
    }


def filtered(source: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    """The document as `_source` includes would return it."""
    kept: dict[str, Any] = {}
    for path in paths:
        value = dig(source, *path.split("."))
        if value is None:
            continue
        *parents, leaf = path.split(".")
        target = kept
        for parent in parents:
            target = target.setdefault(parent, {})
        target[leaf] = value
    return kept


def response(hits: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"timed_out": False, "hits": {"total": {"value": total}, "hits": hits}}


def test_the_body_sorts_by_time_then_sequence_then_id_so_the_order_is_total() -> None:
    body = build_search_body(SearchRequest())

    assert body["sort"] == [
        {"@timestamp": "asc"},
        {"event.sequence": "asc"},
        {"event.id": "asc"},
    ]


def test_the_descending_sort_flips_all_three_keys() -> None:
    body = build_search_body(SearchRequest(sort="-@timestamp"))

    assert body["sort"] == [
        {"@timestamp": "desc"},
        {"event.sequence": "desc"},
        {"event.id": "desc"},
    ]


def test_the_body_asks_for_one_more_event_than_the_page_to_know_whether_there_is_a_next_page() -> (
    None
):
    assert build_search_body(SearchRequest(size=25))["size"] == 26


def test_the_body_counts_exactly_has_a_timeout_and_leaves_the_raw_record_out() -> None:
    body = build_search_body(SearchRequest())

    assert body["track_total_hits"] is True
    assert body["timeout"] == "10s"
    assert body["_source"] == {"excludes": ["tartarus.raw"]}


def test_the_body_without_columns_leaves_only_the_raw_record_out() -> None:
    assert build_search_body(SearchRequest(columns=[]))["_source"] == WITHOUT_RAW


def test_the_body_with_columns_fetches_the_typed_fields_and_the_columns_without_the_raw() -> None:
    source = build_search_body(SearchRequest(columns=["cmdline", "file.hash.sha256"]))["_source"]

    assert source == {
        "includes": [*EVENT_SOURCE_FIELDS, "process.command_line", "file.hash.sha256"]
    }
    assert "tartarus.raw" not in source["includes"]


def test_a_column_that_cannot_be_shown_is_refused_before_any_search() -> None:
    with pytest.raises(ApiError) as caught:
        build_search_body(SearchRequest(columns=["tartarus.raw"]))

    assert caught.value.code == "invalid_column"


def test_the_page_carries_the_requested_columns_of_each_event() -> None:
    request = SearchRequest(columns=["cmdline"])
    first = hit(1)
    first["_source"]["process"] = {"command_line": "a.exe"}

    page = read_search_response(request, response([first, hit(2)], total=2))

    assert [event.fields for event in page.events] == [{"process.command_line": "a.exe"}, {}]


def test_the_typed_fields_survive_the_source_filter_the_body_asks_for() -> None:
    full = full_source()
    kept = filtered(full, EVENT_SOURCE_FIELDS)

    assert event_from_source(kept) == event_from_source(full)
    assert event_from_source(full).process is not None


def test_the_body_carries_the_filter_query() -> None:
    body = build_search_body(SearchRequest(query="lane:file"))

    assert body["query"] == {"bool": {"filter": [{"term": {"tartarus.lane": "file"}}]}}


def test_a_cursor_becomes_search_after() -> None:
    cursor = encode_cursor("@timestamp", [1791892361383, 5, "id-5"])

    body = build_search_body(SearchRequest(search_after=cursor))

    assert body["search_after"] == [1791892361383, 5, "id-5"]


def test_no_cursor_means_no_search_after() -> None:
    assert "search_after" not in build_search_body(SearchRequest())


def test_a_malformed_cursor_is_refused_before_any_search() -> None:
    with pytest.raises(ApiError) as caught:
        build_search_body(SearchRequest(search_after="junk"))

    assert caught.value.code == "invalid_cursor"


def test_a_bad_query_is_refused_before_any_search() -> None:
    with pytest.raises(ApiError) as caught:
        build_search_body(SearchRequest(query="nope:x"))

    assert caught.value.code == "invalid_query"


def test_a_full_page_with_more_behind_it_gets_a_cursor_on_its_last_event() -> None:
    request = SearchRequest(size=2)

    page = read_search_response(request, response([hit(1), hit(2), hit(3)], total=3))

    assert [event.id for event in page.events] == ["id-1", "id-2"]
    assert page.total == 3
    assert page.next_cursor == encode_cursor("@timestamp", [1791892361383, 2, "id-2"])


def test_the_last_page_has_no_cursor_even_when_it_is_full() -> None:
    page = read_search_response(SearchRequest(size=2), response([hit(1), hit(2)], total=2))

    assert [event.id for event in page.events] == ["id-1", "id-2"]
    assert page.next_cursor is None


def test_the_cursor_remembers_the_sort_it_was_issued_for() -> None:
    request = SearchRequest(size=1, sort="-@timestamp")

    page = read_search_response(request, response([hit(2), hit(1)], total=2))

    assert page.next_cursor == encode_cursor("-@timestamp", [1791892361383, 2, "id-2"])


def test_no_hits_is_an_empty_page() -> None:
    page = read_search_response(SearchRequest(), response([], total=0))

    assert (page.events, page.total, page.next_cursor) == ([], 0, None)


def test_a_filter_with_no_restriction_matches_everything() -> None:
    assert build_search_body(SearchRequest(**EventFilter().model_dump()))["query"] == {
        "match_all": {}
    }
