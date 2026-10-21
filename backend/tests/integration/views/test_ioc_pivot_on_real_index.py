from collections.abc import AsyncIterator
from typing import Any

import pytest
from opensearchpy import AsyncOpenSearch

from app.schemas.views_findings import IocType
from app.search.client import create_opensearch_client
from app.search.index import EventIndex
from app.views.ioc_pivot import AnalysisHits, analyses_containing

pytestmark = pytest.mark.integration

SHARING = (8101, 8102)
OTHER = 8103


def dns_event(analysis_id: int, number: int, name: str) -> dict[str, Any]:
    return {
        "event": {"id": f"a{analysis_id}-{number}"},
        "tartarus": {"analysis_id": analysis_id, "lane": "network"},
        "dns": {"question": {"name": name}},
    }


@pytest.fixture
async def events_index(opensearch_url: str) -> AsyncIterator[EventIndex]:
    client: AsyncOpenSearch = create_opensearch_client(opensearch_url)
    events_index = EventIndex(client)
    await events_index.ensure_template()
    for analysis_id in (*SHARING, OTHER):
        await events_index.drop(analysis_id)
        await events_index.create(analysis_id)
    await events_index.bulk_index(
        SHARING[0], [dns_event(SHARING[0], n, "Evil.Example") for n in range(3)]
    )
    await events_index.bulk_index(
        SHARING[1], [dns_event(SHARING[1], 0, "evil.example"), dns_event(SHARING[1], 1, "ok.test")]
    )
    await events_index.bulk_index(OTHER, [dns_event(OTHER, 0, "unrelated.example")])
    for analysis_id in (*SHARING, OTHER):
        await events_index.refresh(analysis_id)
    yield events_index
    for analysis_id in (*SHARING, OTHER):
        await events_index.drop(analysis_id)
    await client.close()


async def test_pivot_lists_both_analyses_sharing_a_domain_and_not_a_third(
    events_index: EventIndex,
) -> None:
    hits = await analyses_containing(events_index, IocType.DOMAIN, "evil.example")

    assert hits == [AnalysisHits(SHARING[0], 3), AnalysisHits(SHARING[1], 1)]


async def test_pivot_value_matches_regardless_of_case(events_index: EventIndex) -> None:
    hits = await analyses_containing(events_index, IocType.DOMAIN, "EVIL.example")

    assert {hit.analysis_id for hit in hits} == set(SHARING)
