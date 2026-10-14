from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.annotations.validation import Target
from app.api.annotations import router
from app.api.dependencies import get_event_index
from app.api.events import router as events_router
from app.api.operation_ids import generate_operation_id
from app.api.views_events import router as processes_router
from app.db import analysis_repository
from app.db import annotation_repository as repository
from app.db.base import Base
from app.db.models.analysis import AnalysisStatus
from app.db.models.annotation import TargetType
from app.errors import install_error_handlers
from tests.test_analysis_repository import SHA_B, _enable_foreign_keys, seeded_analysis

WHOLE = Target(TargetType.ANALYSIS)


def event_source(event_id: str) -> dict[str, Any]:
    return {
        "@timestamp": "2026-10-13T12:12:41.383Z",
        "event": {"id": event_id, "sequence": 1},
        "tartarus": {"lane": "api", "summary": event_id},
    }


def process_bucket(pid: int) -> dict[str, Any]:
    empty: dict[str, Any] = {"buckets": []}
    return {
        "key": f"1:{pid}@1",
        "record": {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "process": {
                                "entity_id": f"1:{pid}@1",
                                "pid": pid,
                                "name": f"p{pid}.exe",
                                "start": "2026-10-13T12:12:41.383Z",
                            }
                        }
                    }
                ]
            }
        },
        "ended": {"at": {}},
        "lanes": empty,
        "injected": {"targets": empty},
        "network": {
            "dns.question.name": empty,
            "destination.domain": empty,
            "destination.ip": empty,
        },
    }


@dataclass
class FakeEventIndex:
    """Answers by the shape of the search: events by id, the pids with a process, the buckets
    of the process view; everything else finds nothing.
    """

    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    pids: set[int] = field(default_factory=set)
    searches: list[dict[str, Any]] = field(default_factory=list)

    async def search(
        self, analysis_id: int, body: dict[str, Any], request_timeout: float | None = None
    ) -> dict[str, Any]:
        self.searches.append(body)
        if "ids" in body["query"]:
            wanted = body["query"]["ids"]["values"]
            return self._hits(
                [{"_id": i, "_source": self.events[i]} for i in wanted if i in self.events]
            )
        aggregations = body.get("aggs", {})
        if "present" in aggregations:
            buckets = [{"key": pid} for pid in sorted(self.pids)]
            return {
                "hits": {"total": {"value": 0}, "hits": []},
                "aggregations": {"present": {"buckets": buckets}},
            }
        if "by_process" in aggregations:
            buckets = [process_bucket(pid) for pid in sorted(self.pids)]
            return {
                "hits": {"total": {"value": 0}, "hits": []},
                "aggregations": {"by_process": {"buckets": buckets}},
            }
        return self._hits([])

    @staticmethod
    def _hits(hits: list[dict[str, Any]]) -> dict[str, Any]:
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}, "aggregations": {}}

    def ids_searches(self) -> list[dict[str, Any]]:
        return [body for body in self.searches if "ids" in body["query"]]


@dataclass
class Harness:
    client: httpx.AsyncClient
    factory: async_sessionmaker[AsyncSession]
    index: FakeEventIndex

    async def analysis(self, *, done: bool = True, sha256: str = "a" * 64) -> int:
        async with self.factory() as session:
            analysis = await seeded_analysis(session, sha256=sha256)
            if done:
                await analysis_repository.update_analysis(
                    session, analysis.id, status=AnalysisStatus.DONE
                )
            return analysis.id

    async def post_tag(
        self, analysis_id: int, tag: str, target_type: str = "analysis", target_ref: str = ""
    ) -> httpx.Response:
        return await self.client.post(
            f"/api/analyses/{analysis_id}/tags",
            json={"tag": tag, "target_type": target_type, "target_ref": target_ref},
        )

    async def post_note(
        self, analysis_id: int, body: str, target_type: str = "analysis", target_ref: str = ""
    ) -> httpx.Response:
        return await self.client.post(
            f"/api/analyses/{analysis_id}/notes",
            json={"body": body, "target_type": target_type, "target_ref": target_ref},
        )

    async def annotations(self, analysis_id: int, **params: str) -> dict[str, Any]:
        response = await self.client.get(f"/api/analyses/{analysis_id}/annotations", params=params)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


@pytest.fixture
async def harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'annotations-api.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    index = FakeEventIndex()
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    for included in (router, events_router, processes_router):
        app.include_router(included, prefix="/api")
    app.dependency_overrides[get_event_index] = lambda: index
    async with make_client(app) as client:
        yield Harness(client, factory, index)
    await engine.dispose()


def instant(text: str) -> datetime:
    """SQLite hands timestamps back naive; Postgres keeps the zone."""
    return datetime.fromisoformat(text).replace(tzinfo=None)


def error_code(response: httpx.Response) -> str:
    return str(response.json()["error"]["code"])


def invalid_locations(response: httpx.Response) -> list[list[object]]:
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    return [field["location"] for field in response.json()["error"]["details"]["fields"]]


async def test_a_tag_is_added_to_an_analysis_and_answered_with_its_link(harness: Harness) -> None:
    analysis_id = await harness.analysis()

    response = await harness.post_tag(analysis_id, "Phishing")

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "link_id": body["link_id"],
        "tag": "phishing",
        "target_type": "analysis",
        "target_ref": "",
        "orphaned": False,
    }


async def test_a_tag_is_added_to_a_process_by_pid_and_to_an_event_by_id(harness: Harness) -> None:
    analysis_id = await harness.analysis()

    process = await harness.post_tag(analysis_id, "dropper", "process", "0412")
    on_event = await harness.post_tag(analysis_id, "c2", "event", "evt/1:a b")

    assert process.json()["target_ref"] == "412"
    assert on_event.json()["target_ref"] == "evt/1:a b"


async def test_the_same_tag_on_the_same_target_twice_is_a_409_and_a_new_target_is_fine(
    harness: Harness,
) -> None:
    analysis_id = await harness.analysis()
    await harness.post_tag(analysis_id, "emotet", "process", "4")

    again = await harness.post_tag(analysis_id, "EMOTET", "process", "04")
    elsewhere = await harness.post_tag(analysis_id, "emotet", "process", "5")

    assert again.status_code == 409
    assert error_code(again) == "conflict"
    assert elsewhere.status_code == 201
    assert len((await harness.annotations(analysis_id))["tags"]) == 2


@pytest.mark.parametrize(
    ("tag", "target_type", "target_ref", "location"),
    [
        ("has space", "analysis", "", ["body", "tag"]),
        ("a" * 41, "analysis", "", ["body", "tag"]),
        ("", "analysis", "", ["body", "tag"]),
        ("ok", "process", "abc", ["body", "target_ref"]),
        ("ok", "process", "-4", ["body", "target_ref"]),
        ("ok", "process", "4.5", ["body", "target_ref"]),
        ("ok", "process", "", ["body", "target_ref"]),
        ("ok", "process", "٤", ["body", "target_ref"]),
        ("ok", "process", "1" * 11, ["body", "target_ref"]),
        ("ok", "analysis", "4", ["body", "target_ref"]),
        ("ok", "event", "", ["body", "target_ref"]),
        ("ok", "file", "", ["body", "target_type"]),
    ],
)
async def test_a_bad_tag_or_target_is_a_validation_error_naming_the_field(
    harness: Harness, tag: str, target_type: str, target_ref: str, location: list[object]
) -> None:
    analysis_id = await harness.analysis()

    response = await harness.post_tag(analysis_id, tag, target_type, target_ref)

    assert location in invalid_locations(response)
    assert (await harness.annotations(analysis_id))["tags"] == []


async def test_a_tag_name_of_exactly_40_characters_is_accepted(harness: Harness) -> None:
    analysis_id = await harness.analysis()

    assert (await harness.post_tag(analysis_id, "a" * 40)).status_code == 201


async def test_tagging_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    response = await harness.post_tag(999, "emotet")

    assert response.status_code == 404
    assert error_code(response) == "not_found"


@pytest.mark.parametrize("status", [s for s in AnalysisStatus if s is not AnalysisStatus.DONE])
async def test_an_event_is_only_annotated_once_the_analysis_is_done(
    harness: Harness, status: AnalysisStatus
) -> None:
    analysis_id = await harness.analysis(done=False)
    async with harness.factory() as session:
        await analysis_repository.update_analysis(session, analysis_id, status=status)

    tag = await harness.post_tag(analysis_id, "c2", "event", "evt-1")
    note = await harness.post_note(analysis_id, "beacon", "event", "evt-1")

    for response in (tag, note):
        assert response.status_code == 409
        assert error_code(response) == "conflict"
        assert "events can be annotated once the analysis is finished" in response.text
    assert await harness.annotations(analysis_id) == {"tags": [], "notes": []}


@pytest.mark.parametrize("status", list(AnalysisStatus))
async def test_the_analysis_and_its_processes_are_annotated_in_any_state(
    harness: Harness, status: AnalysisStatus
) -> None:
    analysis_id = await harness.analysis(done=False)
    async with harness.factory() as session:
        await analysis_repository.update_analysis(session, analysis_id, status=status)

    responses = [
        await harness.post_tag(analysis_id, "a"),
        await harness.post_tag(analysis_id, "b", "process", "4"),
        await harness.post_note(analysis_id, "whole"),
        await harness.post_note(analysis_id, "process", "process", "4"),
    ]

    assert [response.status_code for response in responses] == [201] * 4


async def test_removing_a_tag_link_removes_it_and_a_tag_nothing_uses_leaves_the_list(
    harness: Harness,
) -> None:
    analysis_id = await harness.analysis()
    link_id = (await harness.post_tag(analysis_id, "emotet")).json()["link_id"]

    response = await harness.client.delete(f"/api/analyses/{analysis_id}/tags/{link_id}")

    assert response.status_code == 204
    assert (await harness.annotations(analysis_id))["tags"] == []
    assert (await harness.client.get("/api/tags")).json() == []


async def test_a_link_of_another_analysis_or_no_link_at_all_is_a_404(harness: Harness) -> None:
    first = await harness.analysis()
    second = await harness.analysis(sha256=SHA_B)
    link_id = (await harness.post_tag(first, "emotet")).json()["link_id"]

    other = await harness.client.delete(f"/api/analyses/{second}/tags/{link_id}")
    unknown = await harness.client.delete(f"/api/analyses/{first}/tags/999")
    no_analysis = await harness.client.delete(f"/api/analyses/999/tags/{link_id}")

    for response in (other, unknown, no_analysis):
        assert response.status_code == 404
        assert error_code(response) == "not_found"
    assert len((await harness.annotations(first))["tags"]) == 1


async def test_the_tag_list_has_each_tag_in_use_with_its_count_most_used_first(
    harness: Harness,
) -> None:
    first = await harness.analysis()
    second = await harness.analysis(sha256=SHA_B)
    await harness.post_tag(first, "zeta")
    await harness.post_tag(first, "alpha")
    await harness.post_tag(second, "alpha")
    await harness.post_tag(second, "beta", "process", "4")

    response = await harness.client.get("/api/tags")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "alpha", "count": 2},
        {"name": "beta", "count": 1},
        {"name": "zeta", "count": 1},
    ]


async def test_a_note_is_created_with_its_times_and_read_back(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    harness.index.pids = {4}

    response = await harness.post_note(analysis_id, "dropper stage two", "process", "4")

    assert response.status_code == 201
    body = response.json()
    assert (body["body"], body["target_type"], body["target_ref"], body["orphaned"]) == (
        "dropper stage two",
        "process",
        "4",
        False,
    )
    assert body["created_at"] == body["updated_at"]
    [listed] = (await harness.annotations(analysis_id))["notes"]
    assert (listed["id"], listed["body"], listed["orphaned"]) == (body["id"], body["body"], False)
    assert instant(listed["created_at"]) == instant(body["created_at"])


@pytest.mark.parametrize("body", ["", "  \n ", "n" * 20_001])
async def test_an_empty_or_too_long_note_is_a_validation_error(harness: Harness, body: str) -> None:
    analysis_id = await harness.analysis()

    response = await harness.post_note(analysis_id, body)

    assert ["body", "body"] in invalid_locations(response)
    assert (await harness.annotations(analysis_id))["notes"] == []


async def test_a_note_of_exactly_20000_characters_is_accepted(harness: Harness) -> None:
    analysis_id = await harness.analysis()

    assert (await harness.post_note(analysis_id, "n" * 20_000)).status_code == 201


async def test_a_note_with_a_bad_target_is_a_validation_error(harness: Harness) -> None:
    analysis_id = await harness.analysis()

    response = await harness.post_note(analysis_id, "text", "process", "x")

    assert ["body", "target_ref"] in invalid_locations(response)


async def test_a_note_on_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    assert (await harness.post_note(999, "text")).status_code == 404


async def test_patching_a_note_replaces_its_text_and_moves_updated_at(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    created = (await harness.post_note(analysis_id, "first")).json()

    response = await harness.client.patch(f"/api/notes/{created['id']}", json={"body": "second"})

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["body"]) == (created["id"], "second")
    assert instant(body["created_at"]) == instant(created["created_at"])
    assert instant(body["updated_at"]) > instant(created["updated_at"])


@pytest.mark.parametrize("body", ["", " ", "n" * 20_001])
async def test_patching_a_note_to_nothing_or_too_much_is_a_validation_error(
    harness: Harness, body: str
) -> None:
    analysis_id = await harness.analysis()
    created = (await harness.post_note(analysis_id, "first")).json()

    response = await harness.client.patch(f"/api/notes/{created['id']}", json={"body": body})

    assert ["body", "body"] in invalid_locations(response)
    assert (await harness.annotations(analysis_id))["notes"][0]["body"] == "first"


async def test_patching_or_deleting_an_unknown_note_is_a_404(harness: Harness) -> None:
    patched = await harness.client.patch("/api/notes/999", json={"body": "x"})
    deleted = await harness.client.delete("/api/notes/999")

    for response in (patched, deleted):
        assert response.status_code == 404
        assert error_code(response) == "not_found"


async def test_deleting_a_note_removes_it(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    created = (await harness.post_note(analysis_id, "first")).json()

    response = await harness.client.delete(f"/api/notes/{created['id']}")

    assert response.status_code == 204
    assert (await harness.annotations(analysis_id))["notes"] == []


async def test_the_annotations_list_every_tag_and_note_and_narrows_to_a_target(
    harness: Harness,
) -> None:
    analysis_id = await harness.analysis()
    await harness.post_tag(analysis_id, "whole")
    await harness.post_tag(analysis_id, "p4", "process", "4")
    await harness.post_tag(analysis_id, "p5", "process", "5")
    await harness.post_note(analysis_id, "note on 4", "process", "4")
    await harness.post_note(analysis_id, "note on whole")
    harness.index.pids = {4, 5}

    everything = await harness.annotations(analysis_id)
    processes = await harness.annotations(analysis_id, target_type="process")
    one = await harness.annotations(analysis_id, target_type="process", target_ref="004")
    analysis_only = await harness.annotations(analysis_id, target_type="analysis")

    assert [tag["tag"] for tag in everything["tags"]] == ["whole", "p4", "p5"]
    assert [note["body"] for note in everything["notes"]] == ["note on 4", "note on whole"]
    assert [tag["tag"] for tag in processes["tags"]] == ["p4", "p5"]
    assert ([tag["tag"] for tag in one["tags"]], [n["body"] for n in one["notes"]]) == (
        ["p4"],
        ["note on 4"],
    )
    assert [tag["tag"] for tag in analysis_only["tags"]] == ["whole"]


@pytest.mark.parametrize(
    "params",
    [{"target_ref": "4"}, {"target_type": "process", "target_ref": "x"}, {"target_type": "file"}],
)
async def test_a_bad_annotation_filter_is_a_validation_error(
    harness: Harness, params: dict[str, str]
) -> None:
    analysis_id = await harness.analysis()

    response = await harness.client.get(f"/api/analyses/{analysis_id}/annotations", params=params)

    assert response.status_code == 422
    assert error_code(response) == "validation_error"


async def test_reading_the_annotations_of_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    assert (await harness.client.get("/api/analyses/999/annotations")).status_code == 404


async def test_an_event_annotation_is_orphaned_when_the_event_is_no_longer_indexed(
    harness: Harness,
) -> None:
    analysis_id = await harness.analysis()
    harness.index.events = {"kept": event_source("kept")}
    await harness.post_tag(analysis_id, "c2", "event", "kept")
    await harness.post_tag(analysis_id, "c2", "event", "gone")
    await harness.post_note(analysis_id, "beacon", "event", "gone")
    await harness.post_note(analysis_id, "fine", "event", "kept")

    found = await harness.annotations(analysis_id)

    assert {(tag["target_ref"], tag["orphaned"]) for tag in found["tags"]} == {
        ("kept", False),
        ("gone", True),
    }
    assert {(note["target_ref"], note["orphaned"]) for note in found["notes"]} == {
        ("kept", False),
        ("gone", True),
    }


async def test_the_events_of_all_annotations_are_checked_with_one_search(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    for number in range(5):
        await harness.post_tag(analysis_id, "c2", "event", f"evt-{number}")
        await harness.post_note(analysis_id, "n", "event", f"evt-{number}")

    await harness.annotations(analysis_id)

    [search] = harness.index.ids_searches()
    assert sorted(search["query"]["ids"]["values"]) == [f"evt-{n}" for n in range(5)]


async def test_a_process_annotation_is_orphaned_when_the_analysis_has_no_such_pid(
    harness: Harness,
) -> None:
    analysis_id = await harness.analysis()
    harness.index.pids = {4}
    await harness.post_tag(analysis_id, "dropper", "process", "4")
    await harness.post_tag(analysis_id, "dropper", "process", "9")
    await harness.post_note(analysis_id, "n", "process", "9")

    found = await harness.annotations(analysis_id)

    assert {(tag["target_ref"], tag["orphaned"]) for tag in found["tags"]} == {
        ("4", False),
        ("9", True),
    }
    assert [note["orphaned"] for note in found["notes"]] == [True]


async def test_analysis_annotations_are_never_checked_against_the_index(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    await harness.post_tag(analysis_id, "phishing")
    await harness.post_note(analysis_id, "overall")

    found = await harness.annotations(analysis_id)

    assert [tag["orphaned"] for tag in found["tags"]] == [False]
    assert [note["orphaned"] for note in found["notes"]] == [False]
    assert harness.index.searches == []


async def test_the_event_detail_carries_the_annotations_of_that_event_only(
    harness: Harness,
) -> None:
    analysis_id = await harness.analysis()
    harness.index.events = {"evt/1": event_source("evt/1"), "other": event_source("other")}
    await harness.post_tag(analysis_id, "c2", "event", "evt/1")
    await harness.post_note(analysis_id, "beacon", "event", "evt/1")
    await harness.post_tag(analysis_id, "unrelated", "event", "other")
    await harness.post_tag(analysis_id, "whole")

    response = await harness.client.get(
        f"/api/analyses/{analysis_id}/events/{quote('evt/1', safe='')}"
    )

    assert response.status_code == 200
    annotations = response.json()["annotations"]
    assert [tag["tag"] for tag in annotations["tags"]] == ["c2"]
    assert [note["body"] for note in annotations["notes"]] == ["beacon"]
    assert annotations["tags"][0]["orphaned"] is False


async def test_an_event_without_annotations_has_empty_lists(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    harness.index.events = {"evt-1": event_source("evt-1")}

    response = await harness.client.get(f"/api/analyses/{analysis_id}/events/evt-1")

    assert response.json()["annotations"] == {"tags": [], "notes": []}


async def test_the_process_tree_marks_each_process_with_its_tags_and_note_count(
    harness: Harness,
) -> None:
    analysis_id = await harness.analysis()
    harness.index.pids = {4, 5}
    await harness.post_tag(analysis_id, "zeta", "process", "4")
    await harness.post_tag(analysis_id, "alpha", "process", "4")
    await harness.post_note(analysis_id, "one", "process", "4")
    await harness.post_note(analysis_id, "two", "process", "4")
    await harness.post_note(analysis_id, "whole analysis")

    response = await harness.client.get(f"/api/analyses/{analysis_id}/processes")

    assert response.status_code == 200
    marks = {node["pid"]: (node["tags"], node["note_count"]) for node in response.json()["roots"]}
    assert marks == {4: (["alpha", "zeta"], 2), 5: ([], 0)}


async def test_the_process_detail_carries_the_same_marks(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    harness.index.pids = {4}
    await harness.post_tag(analysis_id, "dropper", "process", "4")
    await harness.post_note(analysis_id, "one", "process", "4")

    response = await harness.client.get(f"/api/analyses/{analysis_id}/processes/4")

    assert response.status_code == 200
    assert (response.json()["tags"], response.json()["note_count"]) == (["dropper"], 1)


async def test_deleting_an_analysis_takes_its_annotations_with_it(harness: Harness) -> None:
    analysis_id = await harness.analysis()
    await harness.post_tag(analysis_id, "emotet")
    await harness.post_note(analysis_id, "overall")

    async with harness.factory() as session:
        await analysis_repository.delete_analysis(session, analysis_id)

    assert (await harness.client.get("/api/tags")).json() == []
    async with harness.factory() as session:
        assert (await repository.annotations_of_analysis(session, analysis_id)).notes == []


def test_every_annotation_route_has_an_operation_id_named_after_its_tag() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(router, prefix="/api")

    operations = {
        (method, path): operation["operationId"]
        for path, methods in app.openapi()["paths"].items()
        for method, operation in methods.items()
    }

    assert operations == {
        ("get", "/api/tags"): "annotations_list_tags",
        ("get", "/api/analyses/{analysis_id}/annotations"): "annotations_read",
        ("post", "/api/analyses/{analysis_id}/tags"): "annotations_add_tag",
        ("delete", "/api/analyses/{analysis_id}/tags/{link_id}"): "annotations_remove_tag",
        ("post", "/api/analyses/{analysis_id}/notes"): "annotations_add_note",
        ("patch", "/api/notes/{note_id}"): "annotations_update_note",
        ("delete", "/api/notes/{note_id}"): "annotations_delete_note",
    }
