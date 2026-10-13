import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import analyses as analyses_api
from app.api.analyses import router as analyses_router
from app.api.dependencies import get_cape, get_runner, get_sample_store
from app.api.internal import router as internal_router
from app.api.operation_ids import generate_operation_id
from app.cape.errors import CapeRejected, CapeTaskNotFound, CapeUnreachable
from app.db import analysis_repository as repository
from app.db.base import Base
from app.db.models import Analysis, Sample
from app.db.models.analysis import AnalysisStatus
from app.errors import install_error_handlers
from app.health import ComponentHealth, HealthStatus
from app.samples.store import SampleStore

CONTENT = b"MZ\x90\x00 a pretend executable"
OTHER_CONTENT = b"MZ\x90\x00 another pretend executable"
OPTIONS: dict[str, Any] = {"route": "inetsim", "timeout": 180, "package": "auto"}


@dataclass
class FakeGuest:
    health: ComponentHealth = field(default_factory=lambda: ComponentHealth(status=HealthStatus.OK))

    async def check(self) -> ComponentHealth:
        return self.health


@dataclass
class FakeRunner:
    nudges: int = 0

    def nudge(self) -> None:
        self.nudges += 1


@dataclass
class FakeCape:
    status: str = "reported"
    status_error: Exception | None = None
    delete_error: Exception | None = None
    status_calls: list[int] = field(default_factory=list)
    deleted: list[tuple[int, str | None]] = field(default_factory=list)

    async def task_status(self, task_id: int) -> str:
        self.status_calls.append(task_id)
        if self.status_error:
            raise self.status_error
        return self.status

    async def delete_task(self, task_id: int, task_status: str | None = None) -> None:
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((task_id, task_status))


@dataclass
class Harness:
    client: httpx.AsyncClient
    app: FastAPI
    factory: async_sessionmaker[AsyncSession]
    store: SampleStore
    runner: FakeRunner
    cape: FakeCape
    guest: FakeGuest

    async def upload(
        self,
        content: bytes = CONTENT,
        name: str = "benign.exe",
        options: dict[str, Any] | str | None = None,
    ) -> httpx.Response:
        data = {} if options is None else {"options": _as_json(options)}
        return await self.client.post("/api/analyses", files={"file": (name, content)}, data=data)

    async def rows(self, model: type[Base]) -> list[Any]:
        async with self.factory() as session:
            return list((await session.scalars(select(model))).all())

    async def analysis(self, analysis_id: int) -> Analysis:
        async with self.factory() as session:
            found = await repository.get_analysis(session, analysis_id)
        assert found is not None
        return found

    async def set_state(self, analysis_id: int, **changes: Any) -> None:
        async with self.factory() as session:
            await repository.update_analysis(session, analysis_id, **changes)

    def stored_files(self) -> list[str]:
        root = self.store.root
        return (
            sorted(path.name for path in root.rglob("*") if path.is_file()) if root.exists() else []
        )


def _as_json(options: dict[str, Any] | str) -> str:
    return options if isinstance(options, str) else json.dumps(options)


def _enable_foreign_keys(dbapi_connection: Any, _record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[Harness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SampleStore(tmp_path / "samples")
    runner, cape, guest = FakeRunner(), FakeCape(), FakeGuest()

    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    app.include_router(analyses_router, prefix="/api")
    app.dependency_overrides[get_sample_store] = lambda: store
    app.dependency_overrides[get_runner] = lambda: runner
    app.dependency_overrides[get_cape] = lambda: cape
    app.dependency_overrides[analyses_api.get_guest_check] = lambda: guest

    async with make_client(app) as client:
        yield Harness(client, app, factory, store, runner, cape, guest)
    await engine.dispose()


def error_locations(response: httpx.Response) -> list[list[object]]:
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    return [field["location"] for field in response.json()["error"]["details"]["fields"]]


async def test_a_submission_is_queued_with_the_default_options(harness: Harness) -> None:
    response = await harness.upload()

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["filename"] == "benign.exe"
    assert body["options"] == OPTIONS
    assert body["cape_task_id"] is None
    assert body["summary"] is None


async def test_a_submission_stores_the_sample_and_wakes_the_runner(harness: Harness) -> None:
    body = (await harness.upload()).json()

    (sample,) = await harness.rows(Sample)
    assert sample.sha256 == body["sample_sha256"]
    assert (sample.size, sample.original_name) == (len(CONTENT), "benign.exe")
    assert harness.stored_files() == [f"{sample.sha256}.zip"]
    assert Path(sample.stored_path) == harness.store.root / f"{sample.sha256}.zip"
    assert harness.runner.nudges == 1


async def test_submitted_options_are_kept(harness: Harness) -> None:
    options = {"route": "none", "timeout": 600, "package": "dll"}

    body = (await harness.upload(options=options)).json()

    assert body["options"] == options


async def test_a_file_name_with_a_path_is_shortened_to_its_last_part(harness: Harness) -> None:
    body = (await harness.upload(name="C:\\Users\\bob\\evil.exe")).json()

    assert body["filename"] == "evil.exe"


@pytest.mark.parametrize(
    ("options", "location"),
    [
        ({"route": "sneaky"}, ["body", "options", "route"]),
        ({"timeout": 59}, ["body", "options", "timeout"]),
        ({"timeout": 1201}, ["body", "options", "timeout"]),
        ({"package": ""}, ["body", "options", "package"]),
        ({"package": "../exe"}, ["body", "options", "package"]),
        ("{not json", ["body", "options"]),
        ("[]", ["body", "options"]),
    ],
)
async def test_invalid_options_are_rejected_naming_the_field_and_store_nothing(
    harness: Harness, options: dict[str, Any] | str, location: list[object]
) -> None:
    response = await harness.upload(options=options)

    assert location in error_locations(response)
    assert await harness.rows(Sample) == []
    assert await harness.rows(Analysis) == []
    assert harness.stored_files() == []
    assert harness.runner.nudges == 0


async def test_a_submission_without_a_file_is_rejected_naming_it(harness: Harness) -> None:
    response = await harness.client.post("/api/analyses", data={"options": "{}"})

    assert ["body", "file"] in error_locations(response)


async def test_an_empty_file_is_rejected_and_stores_nothing(harness: Harness) -> None:
    response = await harness.upload(content=b"")

    assert ["body", "file"] in error_locations(response)
    assert await harness.rows(Sample) == []
    assert harness.stored_files() == []


async def test_a_file_over_the_size_limit_is_rejected_with_413_and_stores_nothing(
    harness: Harness,
) -> None:
    harness.app.dependency_overrides[get_sample_store] = lambda: SampleStore(
        harness.store.root, max_bytes=8
    )

    response = await harness.upload()

    assert response.status_code == 413
    assert await harness.rows(Sample) == []
    assert harness.stored_files() == []


@pytest.mark.parametrize("status", [HealthStatus.DOWN, HealthStatus.DEGRADED])
async def test_a_submission_is_refused_with_409_while_the_guest_is_not_ready(
    harness: Harness, status: HealthStatus
) -> None:
    harness.guest.health = ComponentHealth(status=status, message="guest win is not listed")

    response = await harness.upload()

    assert response.status_code == 409
    assert "guest" in response.json()["error"]["message"].lower()
    assert await harness.rows(Sample) == []
    assert await harness.rows(Analysis) == []
    assert harness.stored_files() == []
    assert harness.runner.nudges == 0


async def test_a_guest_check_that_crashes_counts_as_not_ready(harness: Harness) -> None:
    async def explode() -> ComponentHealth:
        raise RuntimeError("boom")

    harness.guest.check = explode  # type: ignore[method-assign]

    assert (await harness.upload()).status_code == 409


async def test_the_same_file_submitted_twice_makes_two_analyses_of_one_sample(
    harness: Harness,
) -> None:
    first = (await harness.upload()).json()
    second = (await harness.upload(name="renamed.exe")).json()

    assert first["id"] != second["id"]
    assert first["sample_sha256"] == second["sample_sha256"]
    assert len(await harness.rows(Sample)) == 1
    assert len(harness.stored_files()) == 1
    assert harness.runner.nudges == 2


async def test_a_duplicate_upload_race_reads_the_row_the_other_request_inserted(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def other_request_wins(session: AsyncSession, sample: Sample) -> Sample:
        async with harness.factory() as other:
            other.add(
                Sample(
                    sha256=sample.sha256,
                    sha1=sample.sha1,
                    md5=sample.md5,
                    size=sample.size,
                    original_name="from-the-other-request.exe",
                    stored_path=sample.stored_path,
                )
            )
            await other.commit()
        raise IntegrityError("INSERT INTO sample", {}, Exception("duplicate key"))

    monkeypatch.setattr(analyses_api, "add_sample_if_new", other_request_wins)

    response = await harness.upload()

    assert response.status_code == 201
    (sample,) = await harness.rows(Sample)
    assert sample.original_name == "from-the-other-request.exe"
    assert len(await harness.rows(Analysis)) == 1
    assert harness.stored_files() == [f"{sample.sha256}.zip"]


async def test_a_failed_first_submission_leaves_no_file_and_no_row(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: object, **__: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(analyses_api, "create_analysis", broken)

    response = await harness.upload()

    assert response.status_code == 500
    assert await harness.rows(Sample) == []
    assert harness.stored_files() == []
    assert harness.runner.nudges == 0


async def test_a_failed_repeat_submission_keeps_the_sample_other_analyses_use(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await harness.upload()

    async def broken(*_: object, **__: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(analyses_api, "create_analysis", broken)
    assert (await harness.upload()).status_code == 500

    assert len(await harness.rows(Sample)) == 1
    assert len(harness.stored_files()) == 1


async def test_listing_returns_the_newest_first_with_the_total(harness: Harness) -> None:
    ids = [(await harness.upload(name=f"{n}.exe")).json()["id"] for n in range(3)]

    body = (await harness.client.get("/api/analyses")).json()

    assert [item["id"] for item in body["items"]] == ids[::-1]
    assert body["total"] == 3


async def test_listing_pages_with_limit_and_offset_and_keeps_the_full_total(
    harness: Harness,
) -> None:
    ids = [(await harness.upload(name=f"{n}.exe")).json()["id"] for n in range(5)]

    body = (await harness.client.get("/api/analyses", params={"limit": 2, "offset": 2})).json()

    assert [item["id"] for item in body["items"]] == ids[::-1][2:4]
    assert body["total"] == 5


async def test_listing_filters_by_name_or_hash_substring_and_reports_the_filtered_total(
    harness: Harness,
) -> None:
    keep = (await harness.upload(name="Invoice.exe")).json()
    await harness.upload(content=OTHER_CONTENT, name="other.exe")

    by_name = (await harness.client.get("/api/analyses", params={"q": "invoice"})).json()
    by_hash = (
        await harness.client.get("/api/analyses", params={"q": keep["sample_sha256"][:10]})
    ).json()

    assert [item["id"] for item in by_name["items"]] == [keep["id"]]
    assert by_name["total"] == 1
    assert [item["id"] for item in by_hash["items"]] == [keep["id"]]


async def test_listing_filters_by_status(harness: Harness) -> None:
    queued = (await harness.upload(name="a.exe")).json()
    running = (await harness.upload(content=OTHER_CONTENT, name="b.exe")).json()
    await harness.set_state(running["id"], status=AnalysisStatus.RUNNING)

    body = (await harness.client.get("/api/analyses", params={"status": "running"})).json()

    assert [item["id"] for item in body["items"]] == [running["id"]]
    assert queued["id"] not in [item["id"] for item in body["items"]]


@pytest.mark.parametrize(
    ("params", "field_name"),
    [
        ({"status": "exploded"}, "status"),
        ({"limit": 0}, "limit"),
        ({"limit": 1000}, "limit"),
        ({"offset": -1}, "offset"),
    ],
)
async def test_listing_rejects_bad_query_parameters_naming_them(
    harness: Harness, params: dict[str, Any], field_name: str
) -> None:
    response = await harness.client.get("/api/analyses", params=params)

    assert ["query", field_name] in error_locations(response)


async def test_an_analysis_is_read_with_its_summary(harness: Harness) -> None:
    created = (await harness.upload()).json()
    summary = {"duration_s": 55, "process_count": 2, "signatures": [], "techniques": []}
    await harness.set_state(created["id"], summary=summary, score=6.0)

    body = (await harness.client.get(f"/api/analyses/{created['id']}")).json()

    assert body["score"] == 6.0
    assert body["summary"]["duration_s"] == 55
    assert body["summary"]["process_count"] == 2


async def test_a_submission_reports_its_place_in_the_queue(harness: Harness) -> None:
    first = (await harness.upload(name="a.exe")).json()
    second = (await harness.upload(content=OTHER_CONTENT, name="b.exe")).json()

    assert (first["queue_position"], second["queue_position"]) == (1, 2)


async def test_a_read_analysis_reports_its_queue_position_only_while_queued(
    harness: Harness,
) -> None:
    first = (await harness.upload(name="a.exe")).json()
    second = (await harness.upload(content=OTHER_CONTENT, name="b.exe")).json()
    await harness.set_state(first["id"], status=AnalysisStatus.RUNNING)

    running = (await harness.client.get(f"/api/analyses/{first['id']}")).json()
    waiting = (await harness.client.get(f"/api/analyses/{second['id']}")).json()

    assert running["queue_position"] is None
    assert waiting["queue_position"] == 1


async def test_the_listing_reports_a_queue_position_on_every_queued_item(
    harness: Harness,
) -> None:
    ids = [(await harness.upload(name=f"{n}.exe")).json()["id"] for n in range(4)]
    await harness.set_state(ids[0], status=AnalysisStatus.DONE)

    items = (await harness.client.get("/api/analyses", params={"limit": 2})).json()["items"]

    assert [(item["id"], item["queue_position"]) for item in items] == [(ids[3], 3), (ids[2], 2)]


async def test_a_cancelled_analysis_has_no_queue_position_and_the_next_one_moves_up(
    harness: Harness,
) -> None:
    first = (await harness.upload(name="a.exe")).json()
    second = (await harness.upload(content=OTHER_CONTENT, name="b.exe")).json()

    cancelled = (await harness.client.post(f"/api/analyses/{first['id']}/cancel")).json()
    waiting = (await harness.client.get(f"/api/analyses/{second['id']}")).json()

    assert cancelled["queue_position"] is None
    assert waiting["queue_position"] == 1


async def test_reading_an_unknown_analysis_is_a_404_in_the_error_envelope(
    harness: Harness,
) -> None:
    response = await harness.client.get("/api/analyses/999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_queued_analysis_can_be_cancelled(harness: Harness) -> None:
    created = (await harness.upload()).json()

    response = await harness.client.post(f"/api/analyses/{created['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["finished_at"] is not None
    assert (await harness.analysis(created["id"])).status is AnalysisStatus.CANCELLED


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.STARTING,
        AnalysisStatus.RUNNING,
        AnalysisStatus.DONE,
        AnalysisStatus.CANCELLED,
    ],
)
async def test_an_analysis_that_is_not_queued_cannot_be_cancelled(
    harness: Harness, status: AnalysisStatus
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=status)

    response = await harness.client.post(f"/api/analyses/{created['id']}/cancel")

    assert response.status_code == 409
    assert (await harness.analysis(created["id"])).status is status


async def test_cancelling_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    assert (await harness.client.post("/api/analyses/999/cancel")).status_code == 404


async def test_deleting_an_analysis_removes_its_row_its_sample_row_and_its_file(
    harness: Harness,
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE)

    response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert await harness.rows(Analysis) == []
    assert await harness.rows(Sample) == []
    assert harness.stored_files() == []


async def test_the_sample_outlives_all_but_the_last_analysis_that_uses_it(
    harness: Harness,
) -> None:
    first = (await harness.upload()).json()
    second = (await harness.upload()).json()

    await harness.client.delete(f"/api/analyses/{first['id']}")
    assert len(await harness.rows(Sample)) == 1
    assert len(harness.stored_files()) == 1

    await harness.client.delete(f"/api/analyses/{second['id']}")
    assert await harness.rows(Sample) == []
    assert harness.stored_files() == []


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.STARTING,
        AnalysisStatus.RUNNING,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.INGESTING,
    ],
)
async def test_an_active_analysis_cannot_be_deleted(
    harness: Harness, status: AnalysisStatus
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=status, cape_task_id=7)

    response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 409
    assert len(await harness.rows(Analysis)) == 1
    assert harness.cape.deleted == []
    assert len(harness.stored_files()) == 1


async def test_deleting_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    assert (await harness.client.delete("/api/analyses/999")).status_code == 404


async def test_deleting_a_finished_analysis_deletes_its_cape_task_using_the_tasks_status(
    harness: Harness,
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.FAILED, cape_task_id=7)
    harness.cape.status = "failed_analysis"

    response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert harness.cape.status_calls == [7]
    assert harness.cape.deleted == [(7, "failed_analysis")]


async def test_an_analysis_that_never_reached_cape_does_not_call_it(harness: Harness) -> None:
    created = (await harness.upload()).json()

    await harness.client.delete(f"/api/analyses/{created['id']}")

    assert harness.cape.status_calls == []


@pytest.mark.parametrize(
    ("status_error", "delete_error"),
    [
        (CapeTaskNotFound("tasks/status", 7, "Task does not exist"), None),
        (CapeUnreachable("tasks/status", "ConnectError"), None),
        (None, CapeUnreachable("tasks/delete", "ConnectError")),
        (None, CapeRejected("tasks/delete", "Task(s) ID(s) 7 failed to remove")),
    ],
    ids=["task-gone", "cape-down-at-status", "cape-down-at-delete", "cape-refuses"],
)
async def test_a_cape_task_that_cannot_be_deleted_never_blocks_deleting_the_analysis(
    harness: Harness,
    caplog: pytest.LogCaptureFixture,
    status_error: Exception | None,
    delete_error: Exception | None,
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE, cape_task_id=7)
    harness.cape.status_error = status_error
    harness.cape.delete_error = delete_error

    with caplog.at_level(logging.WARNING):
        response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert await harness.rows(Analysis) == []
    assert harness.stored_files() == []
    already_gone = isinstance(status_error, CapeTaskNotFound)
    assert bool(caplog.records) is not already_gone


def test_the_operation_ids_are_tag_and_function_name_and_unique() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")
    app.include_router(internal_router)

    operations = {
        (method, path): operation["operationId"]
        for path, methods in app.openapi()["paths"].items()
        for method, operation in methods.items()
    }

    assert operations == {
        ("post", "/api/analyses"): "analyses_create",
        ("get", "/api/analyses"): "analyses_list",
        ("get", "/api/analyses/{analysis_id}"): "analyses_read",
        ("post", "/api/analyses/{analysis_id}/cancel"): "analyses_cancel",
        ("delete", "/api/analyses/{analysis_id}"): "analyses_delete",
    }
    assert len(set(operations.values())) == len(operations)


def test_the_openapi_schema_describes_the_summary_and_the_upload() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")

    schemas = app.openapi()["components"]["schemas"]

    assert "ReportSummary" in schemas
    assert set(schemas["Body_analyses_create"]["properties"]) == {"file", "options"}


def test_the_openapi_schema_always_lists_the_queue_position_of_an_analysis() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")

    read = app.openapi()["components"]["schemas"]["AnalysisRead"]

    assert "queue_position" in read["required"]
