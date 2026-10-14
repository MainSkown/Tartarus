from typing import Any

from app.db import analysis_repository as repository
from tests.integration.views.conftest import ViewStack
from tests.test_analysis_repository import OPTIONS, SHA_A


async def get_view(stack: ViewStack, path: str, analysis_id: int | None = None) -> Any:
    target = stack.analysis_id if analysis_id is None else analysis_id
    response = await stack.client.get(f"/api/analyses/{target}/{path}")
    assert response.status_code == 200, response.text
    return response.json()


async def add_analysis_without_index(stack: ViewStack) -> int:
    async with stack.factory() as session:
        created = await repository.create_analysis(
            session, sample_sha256=SHA_A, filename="bare.exe", options=OPTIONS
        )
    return created.id


async def set_route(stack: ViewStack, route: str) -> None:
    async with stack.factory() as session:
        analysis = await repository.get_analysis(session, stack.analysis_id)
        assert analysis is not None
        analysis.options = {**OPTIONS, "route": route}
        await session.commit()


async def index_extra_events(stack: ViewStack, events: list[dict[str, Any]]) -> None:
    await stack.index.bulk_index(stack.analysis_id, events)
    await stack.index.refresh(stack.analysis_id)


def process_fields(
    stack: ViewStack, pid: int, name: str, start: str, parent_pid: int
) -> dict[str, Any]:
    return {
        "pid": pid,
        "name": name,
        "entity_id": f"{stack.analysis_id}:{pid}@{start}",
        "start": start,
        "parent": {"pid": parent_pid},
    }


def synthetic_event(
    event_id: str, timestamp: str, action: str, lane: str, **sections: Any
) -> dict[str, Any]:
    return {
        "@timestamp": timestamp,
        "event": {
            "id": event_id,
            "sequence": 100_000 + int(event_id.rsplit("-", 1)[-1]),
            "kind": "event",
            "action": action,
            "module": "capemon",
            "dataset": "capemon.derived",
            "severity": 0,
        },
        "tartarus": {"analysis_id": 6, "lane": lane, "phase": "final", "summary": action},
        **sections,
    }


async def indexed_events(stack: ViewStack) -> dict[str, dict[str, Any]]:
    """Every stored document by id, read back with a match-all, for the plain scan."""
    response = await stack.index.search(
        stack.analysis_id, {"size": 10_000, "query": {"match_all": {}}}
    )
    return {hit["_id"]: hit["_source"] for hit in response["hits"]["hits"]}
