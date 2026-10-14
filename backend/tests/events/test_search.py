from typing import Any

import pytest

from app.errors import ApiError
from app.events.cursor import encode_cursor
from app.events.search import build_search_body, read_search_response
from app.schemas.events_api import EventFilter, SearchRequest


def hit(number: int) -> dict[str, Any]:
    return {
        "_source": {
            "@timestamp": "2026-10-13T12:12:41.383Z",
            "event": {"id": f"id-{number}", "sequence": number},
        },
        "sort": [1791892361383, number, f"id-{number}"],
    }


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
