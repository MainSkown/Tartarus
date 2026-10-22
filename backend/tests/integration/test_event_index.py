from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from opensearchpy import AsyncOpenSearch

from app.search.client import create_opensearch_client
from app.search.index import EventIndex, IndexingError, index_name
from app.search.oversize import MAX_RAW_BYTES

pytestmark = pytest.mark.integration

ANALYSIS_ID = 4242


@pytest.fixture
async def client(opensearch_url: str) -> AsyncIterator[AsyncOpenSearch]:
    opensearch = create_opensearch_client(opensearch_url)
    yield opensearch
    await opensearch.close()


@pytest.fixture
async def events_index(client: AsyncOpenSearch) -> AsyncIterator[EventIndex]:
    events_index = EventIndex(client)
    await events_index.ensure_template()
    await events_index.drop(ANALYSIS_ID)
    await events_index.create(ANALYSIS_ID)
    yield events_index
    await events_index.drop(ANALYSIS_ID)


def make_event(number: int, process_name: str = "Cmd.EXE") -> dict[str, Any]:
    return {
        "event": {"id": f"event-{number}", "sequence": number},
        "process": {"name": process_name, "pid": number},
        "tartarus": {"analysis_id": ANALYSIS_ID, "unmapped": "keptinsource"},
    }


def generate_events(count: int) -> Iterator[dict[str, Any]]:
    return (make_event(number) for number in range(count))


async def count_where(client: AsyncOpenSearch, query: dict[str, Any]) -> int:
    response = await client.count(index=index_name(ANALYSIS_ID), body={"query": query})
    return int(response["count"])


def test_index_name_carries_the_analysis_id() -> None:
    assert index_name(7) == "tartarus-events-7"


async def test_ensure_template_can_run_twice(client: AsyncOpenSearch) -> None:
    events_index = EventIndex(client)

    await events_index.ensure_template()
    await events_index.ensure_template()

    assert await client.indices.exists_index_template(name="tartarus-events")


async def test_created_index_gets_the_template_settings(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    response = await client.indices.get_settings(index=index_name(ANALYSIS_ID))
    settings = response[index_name(ANALYSIS_ID)]["settings"]["index"]

    assert settings["number_of_shards"] == "1"
    assert settings["number_of_replicas"] == "0"
    assert settings["refresh_interval"] == "1s"


async def test_bulk_index_stores_every_event_in_chunks(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    indexed = await events_index.bulk_index(ANALYSIS_ID, generate_events(2500), chunk_size=1000)
    await events_index.refresh(ANALYSIS_ID)

    assert indexed == 2500
    assert await count_where(client, {"match_all": {}}) == 2500


async def test_bulk_index_uses_the_event_id_as_the_document_id(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    await events_index.bulk_index(ANALYSIS_ID, [make_event(1), make_event(1)])
    await events_index.refresh(ANALYSIS_ID)

    document = await client.get(index=index_name(ANALYSIS_ID), id="event-1")

    assert document["_source"]["process"]["pid"] == 1
    assert await count_where(client, {"match_all": {}}) == 1


async def test_indexing_nothing_returns_zero(events_index: EventIndex) -> None:
    assert await events_index.bulk_index(ANALYSIS_ID, []) == 0


async def test_process_name_search_ignores_case(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    await events_index.bulk_index(
        ANALYSIS_ID, [make_event(1, "Cmd.EXE"), make_event(2, "calc.exe")]
    )
    await events_index.refresh(ANALYSIS_ID)

    assert await count_where(client, {"term": {"process.name": "cmd.exe"}}) == 1
    assert await count_where(client, {"term": {"process.name": "CMD.exe"}}) == 1


async def test_unmapped_fields_stay_in_source_but_are_not_searchable(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    await events_index.bulk_index(ANALYSIS_ID, [make_event(1)])
    await events_index.refresh(ANALYSIS_ID)

    document = await client.get(index=index_name(ANALYSIS_ID), id="event-1")

    assert document["_source"]["tartarus"]["unmapped"] == "keptinsource"
    assert await count_where(client, {"term": {"tartarus.unmapped": "keptinsource"}}) == 0


async def test_refresh_interval_can_be_changed(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    await events_index.set_refresh_interval(ANALYSIS_ID, "30s")

    response = await client.indices.get_settings(index=index_name(ANALYSIS_ID))

    assert response[index_name(ANALYSIS_ID)]["settings"]["index"]["refresh_interval"] == "30s"


async def test_bulk_index_raises_when_a_document_is_rejected(events_index: EventIndex) -> None:
    rejected = make_event(1)
    rejected["process"]["pid"] = "not a number"

    with pytest.raises(IndexingError, match="event-1"):
        await events_index.bulk_index(ANALYSIS_ID, [make_event(0), rejected])


async def test_drop_removes_the_index_and_dropping_again_is_fine(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    await events_index.drop(ANALYSIS_ID)
    await events_index.drop(ANALYSIS_ID)

    assert not await client.indices.exists(index=index_name(ANALYSIS_ID))


async def test_bulk_index_rejects_an_event_without_an_id(events_index: EventIndex) -> None:
    with pytest.raises(IndexingError, match=r"event\.id"):
        await events_index.bulk_index(ANALYSIS_ID, [{"process": {"pid": 1}}])


async def test_bulk_index_takes_only_nested_events(events_index: EventIndex) -> None:
    with pytest.raises(IndexingError, match=r"event\.id"):
        await events_index.bulk_index(ANALYSIS_ID, [{"event.id": "dotted-1", "process.pid": 9}])


async def test_search_returns_the_raw_response_of_the_analysis_index(
    events_index: EventIndex,
) -> None:
    await events_index.bulk_index(ANALYSIS_ID, generate_events(3))
    await events_index.refresh(ANALYSIS_ID)

    response = await events_index.search(
        ANALYSIS_ID, {"query": {"term": {"process.name": "cmd.exe"}}}
    )

    assert response["hits"]["total"]["value"] == 3


async def test_search_on_an_analysis_without_an_index_finds_nothing(
    events_index: EventIndex,
) -> None:
    response = await events_index.search(ANALYSIS_ID + 1, {"query": {"match_all": {}}})

    assert response["hits"]["total"]["value"] == 0
    assert response["hits"]["hits"] == []
    assert response["aggregations"] == {}


async def test_ensure_index_creates_a_missing_index_and_leaves_an_existing_one_alone(
    client: AsyncOpenSearch,
) -> None:
    events_index = EventIndex(client)
    await events_index.ensure_template()
    await events_index.drop(ANALYSIS_ID)

    await events_index.ensure_index(ANALYSIS_ID)
    await events_index.bulk_index(ANALYSIS_ID, [make_event(1)])
    await events_index.ensure_index(ANALYSIS_ID)
    await events_index.refresh(ANALYSIS_ID)

    assert await count_where(client, {"match_all": {}}) == 1
    await events_index.drop(ANALYSIS_ID)


async def test_an_oversized_raw_record_is_cut_and_its_neighbours_are_still_indexed(
    client: AsyncOpenSearch, events_index: EventIndex
) -> None:
    huge = make_event(1)
    huge["tartarus"]["raw"] = {"blob": "x" * (MAX_RAW_BYTES + 1)}
    neighbours = [make_event(0), huge, make_event(2)]

    stored = await events_index.bulk_index(ANALYSIS_ID, neighbours)

    document = await client.get(index=index_name(ANALYSIS_ID), id="event-1")
    assert stored == 3
    assert document["_source"]["tartarus"]["raw"]["truncated"] is True
