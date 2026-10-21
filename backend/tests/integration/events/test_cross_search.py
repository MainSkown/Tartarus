from collections.abc import AsyncIterator
from typing import Any

import pytest
from opensearchpy import AsyncOpenSearch

from app.events.cross_search import CrossSearchHit, search_across_analyses
from app.schemas.events_api import SearchRequest
from app.search.client import create_opensearch_client
from app.search.index import EventIndex

pytestmark = pytest.mark.integration

ANALYSES = (8201, 8202)
EVENTS_PER_ANALYSIS = 5
PAGE_SIZE = 4


def process_event(analysis_id: int, number: int) -> dict[str, Any]:
    # Both analyses reuse each other's times, sequences and ids: only the index tells them apart.
    return {
        "@timestamp": f"2026-10-13T12:00:{number:02d}.000Z",
        "event": {"id": f"event-{number}", "sequence": number},
        "tartarus": {"analysis_id": analysis_id, "lane": "process"},
        "process": {"pid": number, "name": "cmd.exe"},
    }


@pytest.fixture
async def events_index(opensearch_url: str) -> AsyncIterator[EventIndex]:
    client: AsyncOpenSearch = create_opensearch_client(opensearch_url)
    events_index = EventIndex(client)
    await events_index.ensure_template()
    for analysis_id in ANALYSES:
        await events_index.drop(analysis_id)
        await events_index.create(analysis_id)
        await events_index.bulk_index(
            analysis_id, [process_event(analysis_id, n) for n in range(EVENTS_PER_ANALYSIS)]
        )
        await events_index.refresh(analysis_id)
    yield events_index
    for analysis_id in ANALYSES:
        await events_index.drop(analysis_id)
    await client.close()


def labelled(hits: list[CrossSearchHit]) -> list[tuple[int, str]]:
    return [(hit.analysis_id, hit.event.id) for hit in hits]


def expected_order(descending: bool = False) -> list[tuple[int, str]]:
    ordered = sorted(
        (number, analysis_id) for analysis_id in ANALYSES for number in range(EVENTS_PER_ANALYSIS)
    )
    if descending:
        ordered.reverse()
    return [(analysis_id, f"event-{number}") for number, analysis_id in ordered]


async def every_page(
    events_index: EventIndex, sort: Any, query: str = ""
) -> list[list[CrossSearchHit]]:
    pages: list[list[CrossSearchHit]] = []
    cursor: str | None = None
    while True:
        page = await search_across_analyses(
            events_index,
            SearchRequest(query=query, sort=sort, size=PAGE_SIZE, search_after=cursor),
        )
        pages.append(page.events)
        cursor = page.next_cursor
        if cursor is None:
            return pages


async def test_one_query_returns_the_events_of_both_analyses_in_time_order(
    events_index: EventIndex,
) -> None:
    page = await search_across_analyses(
        events_index, SearchRequest(query="process.name:cmd.exe", size=100)
    )

    assert labelled(page.events) == expected_order()
    assert page.total == len(ANALYSES) * EVENTS_PER_ANALYSIS
    assert page.next_cursor is None


@pytest.mark.parametrize("sort", ["@timestamp", "-@timestamp"])
async def test_paging_across_page_boundaries_loses_and_repeats_no_event(
    events_index: EventIndex, sort: Any
) -> None:
    pages = await every_page(events_index, sort, "process.name:cmd.exe")

    assert [len(page) for page in pages] == [4, 4, 2]
    assert [pair for page in pages for pair in labelled(page)] == expected_order(
        descending=sort.startswith("-")
    )


async def test_a_query_matching_one_analysis_only_returns_its_events(
    events_index: EventIndex,
) -> None:
    extra = {**process_event(ANALYSES[1], 9), "process": {"pid": 9, "name": "evil.exe"}}
    await events_index.bulk_index(ANALYSES[1], [extra])
    await events_index.refresh(ANALYSES[1])

    page = await search_across_analyses(events_index, SearchRequest(query="process.name:evil.exe"))

    assert labelled(page.events) == [(ANALYSES[1], "event-9")]
