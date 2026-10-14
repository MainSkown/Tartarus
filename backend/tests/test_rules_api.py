from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_event_index, get_rule_registry
from app.api.operation_ids import generate_operation_id
from app.api.rules import analysis_router, router
from app.db.base import Base
from app.errors import install_error_handlers
from app.rules.registry import RuleRegistry
from tests.rules.support import rule_yaml, simple_detection
from tests.test_analysis_repository import seeded_analysis

SELECTION = simple_detection("Image|endswith: '\\cmd.exe'")
FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
UPPER = "ABCDEF00-1111-4111-8111-111111111111"


def counts_response(counts: dict[str, int]) -> dict[str, Any]:
    buckets = [{"key": key, "doc_count": count} for key, count in counts.items()]
    return {"aggregations": {"rules": {"buckets": buckets}}}


@dataclass
class FakeEventIndex:
    total: dict[str, int] = field(default_factory=dict)
    by_analysis: dict[int, dict[str, int]] = field(default_factory=dict)
    searched: list[int] = field(default_factory=list)

    async def search_all(self, body: dict[str, Any]) -> dict[str, Any]:
        return counts_response(self.total)

    async def search(self, analysis_id: int, body: dict[str, Any]) -> dict[str, Any]:
        self.searched.append(analysis_id)
        return counts_response(self.by_analysis.get(analysis_id, {}))


@dataclass
class Harness:
    client: httpx.AsyncClient
    registry: RuleRegistry
    index: FakeEventIndex
    root: Path
    factory: async_sessionmaker[AsyncSession]

    def write_rule(self, name: str, rule_id: str, title: str = "Test rule") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rule_yaml(SELECTION, rule_id=rule_id, title=title), encoding="utf-8")
        return path


@pytest.fixture
async def harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rules-api.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    root = tmp_path / "sigma"
    registry = RuleRegistry(root, factory)
    index = FakeEventIndex()
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    app.include_router(router, prefix="/api")
    app.include_router(analysis_router, prefix="/api")
    app.dependency_overrides[get_rule_registry] = lambda: registry
    app.dependency_overrides[get_event_index] = lambda: index
    async with make_client(app) as client:
        yield Harness(client, registry, index, root, factory)
    await engine.dispose()


async def test_the_rule_list_has_every_rule_with_its_verdict_state_and_total_hits(
    harness: Harness,
) -> None:
    harness.write_rule("custom/a.yml", FIRST, title="Whoami")
    (harness.root / "custom" / "broken.yml").write_text("title: [unclosed", encoding="utf-8")
    await harness.registry.reload()
    await harness.registry.set_enabled(FIRST, False)
    harness.index.total = {FIRST: 7}

    response = await harness.client.get("/api/rules")

    assert response.status_code == 200
    rules = {rule["title"]: rule for rule in response.json()}
    assert rules["Whoami"] == {
        "id": FIRST,
        "title": "Whoami",
        "description": "A rule for the tests",
        "level": "high",
        "status": "test",
        "tags": [],
        "logsource_category": "process_creation",
        "validity": "valid",
        "error": None,
        "enabled": False,
        "path": str(harness.root / "custom" / "a.yml"),
        "hits": 7,
    }
    broken = rules["broken"]
    assert broken["validity"] == "invalid"
    assert broken["error"]
    assert broken["hits"] == 0


async def test_hits_are_matched_to_a_rule_whose_id_has_capitals(harness: Harness) -> None:
    harness.write_rule("a.yml", UPPER)
    await harness.registry.reload()
    harness.index.total = {UPPER.lower(): 3}

    [rule] = (await harness.client.get("/api/rules")).json()

    assert rule["id"] == UPPER
    assert rule["hits"] == 3


async def test_one_rule_comes_with_its_yaml_text(harness: Harness) -> None:
    path = harness.write_rule("a.yml", FIRST)
    await harness.registry.reload()
    harness.index.total = {FIRST: 2}

    response = await harness.client.get(f"/api/rules/{FIRST}")

    assert response.status_code == 200
    body = response.json()
    assert body["yaml"] == path.read_text(encoding="utf-8")
    assert (body["id"], body["hits"]) == (FIRST, 2)


async def test_an_unknown_rule_is_a_404_in_the_error_envelope(harness: Harness) -> None:
    for call in (
        harness.client.get(f"/api/rules/{FIRST}"),
        harness.client.patch(f"/api/rules/{FIRST}", json={"enabled": False}),
    ):
        response = await call

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


async def test_a_rule_file_outside_the_rules_directory_is_not_served(
    harness: Harness, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.yml"
    secret.write_text(rule_yaml(SELECTION, rule_id=FIRST), encoding="utf-8")
    harness.root.mkdir()
    (harness.root / "link.yml").symlink_to(secret)
    await harness.registry.reload()

    response = await harness.client.get(f"/api/rules/{FIRST}")

    assert response.status_code == 404
    assert "secret" not in response.text


async def test_patching_enabled_switches_the_rule_and_answers_with_it(harness: Harness) -> None:
    harness.write_rule("a.yml", FIRST)
    await harness.registry.reload()

    response = await harness.client.patch(f"/api/rules/{FIRST}", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert harness.registry.active_rules() == []


async def test_patching_without_enabled_is_a_validation_error(harness: Harness) -> None:
    harness.write_rule("a.yml", FIRST)
    await harness.registry.reload()

    response = await harness.client.patch(f"/api/rules/{FIRST}", json={})

    assert response.status_code == 422


async def test_reload_rereads_the_directory_and_lists_the_rules(harness: Harness) -> None:
    await harness.registry.reload()
    harness.write_rule("new.yml", SECOND, title="Fresh")

    response = await harness.client.post("/api/rules/reload")

    assert response.status_code == 200
    assert [rule["id"] for rule in response.json()] == [SECOND]


async def test_the_hits_of_an_analysis_come_from_its_own_index(harness: Harness) -> None:
    async with harness.factory() as session:
        analysis = await seeded_analysis(session)
    harness.index.by_analysis = {analysis.id: {FIRST: 4, SECOND: 1}}
    harness.index.total = {FIRST: 99}
    harness.write_rule("a.yml", FIRST)
    await harness.registry.reload()

    response = await harness.client.get(f"/api/analyses/{analysis.id}/rules/hits")

    assert response.status_code == 200
    assert response.json() == [
        {"rule_id": FIRST, "count": 4},
        {"rule_id": SECOND, "count": 1},
    ]
    assert harness.index.searched == [analysis.id]


async def test_the_hits_of_an_unknown_analysis_are_a_404(harness: Harness) -> None:
    response = await harness.client.get("/api/analyses/9999/rules/hits")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_rule_endpoints_have_stable_operation_ids(app: FastAPI) -> None:
    operations = {
        (method, path): operation["operationId"]
        for path, methods in app.openapi()["paths"].items()
        if "/rules" in path
        for method, operation in methods.items()
    }

    assert operations == {
        ("get", "/api/rules"): "rules_list",
        ("post", "/api/rules/reload"): "rules_reload",
        ("get", "/api/rules/{rule_id}"): "rules_read",
        ("patch", "/api/rules/{rule_id}"): "rules_update",
        ("get", "/api/analyses/{analysis_id}/rules/hits"): "rules_hits",
    }
