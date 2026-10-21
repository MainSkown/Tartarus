from typing import Any

import pytest
from opensearchpy.exceptions import ConnectionTimeout, TransportError

from app.errors import ApiError
from app.events.cross_search import CrossSearchHit, search_across_analyses
from app.events.cursor import encode_cursor
from app.events.filters import filter_query
from app.schemas.events_api import SearchRequest
from app.search.index import EventIndex, index_name


class FakeIndex:
    def __init__(self, hits: list[dict[str, Any]] | None = None, raises: Exception | None = None):
        self.hits = hits or []
        self.raises = raises
        self.bodies: list[dict[str, Any]] = []

    async def search_all(self, body: dict[str, Any], request_timeout: float | None = None) -> Any:
        self.bodies.append(body)
        if self.raises is not None:
            raise self.raises
        return {"hits": {"total": {"value": len(self.hits)}, "hits": self.hits}}


def hit(analysis_id: int, number: int) -> dict[str, Any]:
    event_id = f"id-{analysis_id}-{number}"
    return {
        "_index": index_name(analysis_id),
        "_source": {
            "@timestamp": "2026-10-13T12:12:41.383Z",
            "event": {"id": event_id, "sequence": number},
        },
        "sort": [1791892361383, number, event_id, index_name(analysis_id)],
    }


async def run(index: FakeIndex, request: SearchRequest) -> Any:
    fake: EventIndex = index  # type: ignore[assignment]
    return await search_across_analyses(fake, request)


async def test_the_query_is_compiled_by_the_events_filter_and_sent_to_every_analysis() -> None:
    request = SearchRequest(query="process.name:cmd.exe", lanes=["process"])
    index = FakeIndex()

    await run(index, request)

    assert index.bodies[0]["query"] == filter_query(request)


async def test_a_query_that_does_not_compile_is_a_422_and_nothing_is_searched() -> None:
    index = FakeIndex()

    with pytest.raises(ApiError) as caught:
        await run(index, SearchRequest(query="nosuchfield:1"))

    assert (caught.value.status_code, caught.value.code) == (422, "invalid_query")
    assert index.bodies == []


@pytest.mark.parametrize(("sort", "order"), [("@timestamp", "asc"), ("-@timestamp", "desc")])
async def test_the_sort_ends_with_the_index_so_equal_events_of_two_analyses_keep_one_order(
    sort: Any, order: str
) -> None:
    index = FakeIndex()

    await run(index, SearchRequest(sort=sort))

    assert index.bodies[0]["sort"] == [
        {"@timestamp": order},
        {"event.sequence": order},
        {"event.id": order},
        {"_index": order},
    ]


async def test_one_more_hit_than_the_page_is_fetched() -> None:
    index = FakeIndex()

    await run(index, SearchRequest(size=20))

    assert index.bodies[0]["size"] == 21


async def test_each_event_carries_the_analysis_its_index_belongs_to() -> None:
    index = FakeIndex([hit(3, 1), hit(9, 1)])

    page = await run(index, SearchRequest())

    assert [(found.analysis_id, found.event.id) for found in page.events] == [
        (3, "id-3-1"),
        (9, "id-9-1"),
    ]
    assert all(isinstance(found, CrossSearchHit) for found in page.events)
    assert page.total == 2
    assert page.next_cursor is None


async def test_a_full_page_with_more_behind_it_gets_a_cursor_after_its_last_event() -> None:
    index = FakeIndex([hit(3, 1), hit(9, 1), hit(3, 2)])

    page = await run(index, SearchRequest(size=2))

    assert [found.event.id for found in page.events] == ["id-3-1", "id-9-1"]
    assert page.next_cursor == encode_cursor("@timestamp", hit(9, 1)["sort"])


async def test_the_cursor_resumes_the_search_after_the_last_event_including_its_index() -> None:
    cursor = encode_cursor("@timestamp", hit(9, 1)["sort"])
    index = FakeIndex()

    await run(index, SearchRequest(search_after=cursor))

    assert index.bodies[0]["search_after"] == hit(9, 1)["sort"]


async def test_a_cursor_of_a_single_analysis_search_is_refused() -> None:
    cursor = encode_cursor("@timestamp", [1791892361383, 1, "id-1"])

    with pytest.raises(ApiError) as caught:
        await run(FakeIndex(), SearchRequest(search_after=cursor))

    assert (caught.value.status_code, caught.value.code) == (422, "invalid_cursor")


async def test_a_cursor_issued_for_the_other_sort_order_is_refused() -> None:
    cursor = encode_cursor("-@timestamp", hit(9, 1)["sort"])

    with pytest.raises(ApiError) as caught:
        await run(FakeIndex(), SearchRequest(search_after=cursor))

    assert caught.value.code == "invalid_cursor"


async def test_a_slow_search_is_a_504() -> None:
    failure = ConnectionTimeout("TIMEOUT", "took too long", Exception())

    with pytest.raises(ApiError) as caught:
        await run(FakeIndex(raises=failure), SearchRequest())

    assert (caught.value.status_code, caught.value.code) == (504, "search_timeout")


async def test_any_other_failure_is_a_502_that_does_not_leak_the_original_error() -> None:
    failure = TransportError(500, "secret internals", {})

    with pytest.raises(ApiError) as caught:
        await run(FakeIndex(raises=failure), SearchRequest())

    assert (caught.value.status_code, caught.value.code) == (502, "search_failed")
    assert "secret" not in caught.value.message
