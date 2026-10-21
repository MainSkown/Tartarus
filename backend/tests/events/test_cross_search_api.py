from typing import Any

import httpx
from fastapi import FastAPI

from app.api.dependencies import get_event_index
from app.search.index import index_name


class FakeIndex:
    def __init__(self, hits: list[dict[str, Any]] | None = None) -> None:
        self.hits = hits or []
        self.bodies: list[dict[str, Any]] = []

    async def search_all(self, body: dict[str, Any], request_timeout: float | None = None) -> Any:
        self.bodies.append(body)
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


def use(app: FastAPI, index: FakeIndex) -> None:
    app.dependency_overrides[get_event_index] = lambda: index


async def test_the_matching_events_come_labelled_with_their_analysis(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use(app, FakeIndex([hit(4, 1)]))

    response = await client.post("/api/search", json={})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"events", "total", "next_cursor"}
    assert body["total"] == 1
    assert body["next_cursor"] is None
    assert [(item["analysis_id"], item["event"]["id"]) for item in body["events"]] == [
        (4, "id-4-1")
    ]


async def test_a_page_with_more_events_gives_a_cursor_for_the_next(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use(app, FakeIndex([hit(4, 1), hit(7, 1)]))

    response = await client.post("/api/search", json={"size": 1})

    body = response.json()
    assert [item["analysis_id"] for item in body["events"]] == [4]
    assert isinstance(body["next_cursor"], str)


async def test_no_matching_event_is_an_empty_page(app: FastAPI, client: httpx.AsyncClient) -> None:
    use(app, FakeIndex())

    response = await client.post("/api/search", json={"query": "process.name:cmd.exe"})

    assert response.status_code == 200
    assert response.json() == {"events": [], "total": 0, "next_cursor": None}


async def test_a_query_that_does_not_compile_is_a_422_in_the_error_envelope(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    index = FakeIndex()
    use(app, index)

    response = await client.post("/api/search", json={"query": "nosuchfield:1"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_query"
    assert index.bodies == []


async def test_a_page_size_out_of_range_is_a_validation_error(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use(app, FakeIndex())

    response = await client.post("/api/search", json={"size": 0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_the_search_is_documented_with_its_operation_id_and_response(app: FastAPI) -> None:
    schema = app.openapi()

    operation = schema["paths"]["/api/search"]["post"]
    assert operation["operationId"] == "search_across_analyses"
    assert {"CrossSearchEvent", "CrossSearchResponse"} <= set(schema["components"]["schemas"])
