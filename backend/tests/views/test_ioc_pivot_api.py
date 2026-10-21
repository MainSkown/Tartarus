from typing import Any

import httpx
from fastapi import FastAPI

from app.api.dependencies import get_event_index
from app.search.index import index_name


class FakeIndex:
    def __init__(self, buckets: list[dict[str, Any]] | None = None) -> None:
        self.buckets = buckets or []
        self.bodies: list[dict[str, Any]] = []

    async def search_all(self, body: dict[str, Any], request_timeout: float | None = None) -> Any:
        self.bodies.append(body)
        return {"aggregations": {"analyses": {"buckets": self.buckets}}}


def bucket(analysis_id: int, count: int) -> dict[str, Any]:
    return {"key": index_name(analysis_id), "doc_count": count}


def use(app: FastAPI, index: FakeIndex) -> None:
    app.dependency_overrides[get_event_index] = lambda: index


async def test_the_analyses_holding_the_domain_come_most_hits_first(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use(app, FakeIndex([bucket(5, 2), bucket(9, 40)]))

    response = await client.get("/api/iocs/domain/evil.example/analyses")

    assert response.status_code == 200
    assert response.json() == [
        {"analysis_id": 9, "count": 40},
        {"analysis_id": 5, "count": 2},
    ]


async def test_no_analysis_holding_the_value_is_an_empty_list(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use(app, FakeIndex())

    response = await client.get("/api/iocs/ip/203.0.113.7/analyses")

    assert response.status_code == 200
    assert response.json() == []


async def test_an_encoded_url_with_slashes_and_a_query_is_searched_as_the_value(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    index = FakeIndex()
    use(app, index)

    response = await client.get("/api/iocs/url/http%3A%2F%2Fevil.example%2Fa%3Fb%3D1/analyses")

    assert response.status_code == 200
    assert {"term": {"url.full": "http://evil.example/a?b=1"}} in index.bodies[0]["query"]["bool"][
        "filter"
    ]


async def test_a_mutex_is_a_422_because_no_event_holds_it(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use(app, FakeIndex())

    response = await client.get("/api/iocs/mutex/Global%5Cx/analyses")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unpivotable_ioc"


async def test_an_unknown_kind_is_a_validation_error(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use(app, FakeIndex())

    response = await client.get("/api/iocs/nonsense/x/analyses")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_the_pivot_is_documented_with_its_operation_id(app: FastAPI) -> None:
    operation = app.openapi()["paths"]["/api/iocs/{kind}/{value}/analyses"]["get"]

    assert operation["operationId"] == "iocs_analyses"
