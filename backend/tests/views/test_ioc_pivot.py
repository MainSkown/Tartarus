from typing import Any

import pytest

from app.schemas.views_findings import IocType
from app.search.index import index_name
from app.views.ioc_pivot import AnalysisHits, UnpivotableIocError, analyses_containing


class FakeIndex:
    def __init__(self, buckets: list[dict[str, Any]]) -> None:
        self._buckets = buckets
        self.bodies: list[dict[str, Any]] = []

    async def search_all(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(body)
        return {"aggregations": {"analyses": {"buckets": self._buckets}}}


def bucket(analysis_id: int, count: int) -> dict[str, Any]:
    return {"key": index_name(analysis_id), "doc_count": count}


def filters_of(body: dict[str, Any]) -> list[dict[str, Any]]:
    return list(body["query"]["bool"]["filter"])


async def test_hits_map_index_names_back_to_analysis_ids_most_hits_first() -> None:
    index = FakeIndex([bucket(3, 2), bucket(9, 40), bucket(5, 2)])

    hits = await analyses_containing(index, IocType.DOMAIN, "evil.example")

    assert hits == [AnalysisHits(9, 40), AnalysisHits(5, 2), AnalysisHits(3, 2)]


async def test_no_matching_analysis_gives_no_hits() -> None:
    assert await analyses_containing(FakeIndex([]), IocType.DOMAIN, "x.example") == []


async def test_domain_is_a_term_on_the_dns_question_name_aggregated_by_index() -> None:
    index = FakeIndex([])

    await analyses_containing(index, IocType.DOMAIN, "Evil.Example")

    body = index.bodies[0]
    assert body["size"] == 0
    assert {"term": {"dns.question.name": "Evil.Example"}} in filters_of(body)
    assert body["aggs"]["analyses"]["terms"]["field"] == "_index"


async def test_ip_pivot_ignores_the_sandbox_network_like_the_ioc_list() -> None:
    index = FakeIndex([])

    await analyses_containing(index, IocType.IP, "203.0.113.7")

    query = index.bodies[0]["query"]["bool"]
    assert {"term": {"destination.ip": "203.0.113.7"}} in query["filter"]
    assert {"term": {"destination.ip": "192.168.150.0/24"}} in query["must_not"]


async def test_hash_pivot_looks_in_file_events() -> None:
    index = FakeIndex([])

    await analyses_containing(index, IocType.HASH, "abc123")

    filters = filters_of(index.bodies[0])
    assert {"term": {"file.hash.sha256": "abc123"}} in filters
    assert {"term": {"tartarus.lane": "file"}} in filters


async def test_a_mutex_is_only_in_the_report_so_it_cannot_be_pivoted() -> None:
    with pytest.raises(UnpivotableIocError):
        await analyses_containing(FakeIndex([]), IocType.MUTEX, "Global\\x")
