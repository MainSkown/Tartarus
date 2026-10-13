from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from opensearchpy import AsyncOpenSearch

from app.live.collector import LiveCollector
from app.search.client import create_opensearch_client
from app.search.index import EventIndex, index_name
from tests.live.collector_support import (
    ANALYSIS_ID,
    STARTED_AT,
    FakeSink,
    by_id,
    fixture_logs,
    reference_events,
    write_in_slices,
)

pytestmark = pytest.mark.integration

POLL_S = 0.02


@pytest.fixture
async def client(opensearch_url: str) -> AsyncIterator[AsyncOpenSearch]:
    opensearch = create_opensearch_client(opensearch_url)
    yield opensearch
    await opensearch.close()


@pytest.fixture
async def event_index(client: AsyncOpenSearch) -> AsyncIterator[EventIndex]:
    index = EventIndex(client)
    await index.drop(ANALYSIS_ID)
    yield index
    await index.drop(ANALYSIS_ID)


def collector_for(logs_dir: Path, event_index: EventIndex, sink: FakeSink) -> LiveCollector:
    return LiveCollector(
        analysis_id=ANALYSIS_ID,
        logs_dir=logs_dir,
        started_at=STARTED_AT,
        store=event_index,
        sink=sink,
        poll_interval_s=POLL_S,
    )


async def indexed_count(client: AsyncOpenSearch, event_index: EventIndex, query: object) -> int:
    await event_index.refresh(ANALYSIS_ID)
    response = await client.count(index=index_name(ANALYSIS_ID), body={"query": query})
    return int(response["count"])


async def test_a_run_written_in_slices_ends_up_searchable_in_the_analysis_index(
    tmp_path: Path, client: AsyncOpenSearch, event_index: EventIndex
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    sink = FakeSink()
    collector = collector_for(logs_dir, event_index, sink)
    collector.start()

    await write_in_slices(logs_dir, fixture_logs(), seed=11, pause_s=0.005)
    await collector.stop()

    expected = reference_events()
    assert sink.errors == []
    assert len(sink.events) == len(expected)
    assert await indexed_count(client, event_index, {"match_all": {}}) == len(sink.events)
    for lane in {event["tartarus"]["lane"] for event in expected}:
        in_lane = sum(1 for event in expected if event["tartarus"]["lane"] == lane)
        assert (
            await indexed_count(client, event_index, {"term": {"tartarus.lane": lane}}) == in_lane
        )
    assert set(by_id(sink.events)) == set(by_id(expected))


async def test_a_collector_started_again_on_the_same_logs_adds_no_duplicates(
    tmp_path: Path, client: AsyncOpenSearch, event_index: EventIndex
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    first = collector_for(logs_dir, event_index, FakeSink())
    first.start()
    await write_in_slices(logs_dir, fixture_logs(), seed=12, pause_s=0.005)
    await first.stop()
    after_first = await indexed_count(client, event_index, {"match_all": {}})

    await collector_for(logs_dir, event_index, FakeSink()).stop()

    assert after_first == len(reference_events())
    assert await indexed_count(client, event_index, {"match_all": {}}) == after_first
