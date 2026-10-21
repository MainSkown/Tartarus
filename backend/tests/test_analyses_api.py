import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from opensearchpy.exceptions import ConnectionError as OpenSearchConnectionError
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analyses import submission as submission_module
from app.annotations.validation import Target
from app.api import analyses as analyses_api
from app.api.analyses import router as analyses_router
from app.api.dependencies import (
    get_cape,
    get_cape_storage_path,
    get_event_index,
    get_exports_path,
    get_free_space_probe,
    get_guest_control,
    get_imports_dir,
    get_runner,
    get_sample_store,
)
from app.api.internal import router as internal_router
from app.api.operation_ids import generate_operation_id
from app.cape.errors import CapeRejected, CapeTaskNotFound, CapeUnreachable
from app.db import analysis_repository as repository
from app.db import annotation_repository, job_repository
from app.db.base import Base
from app.db.models import Analysis, Sample, Setting
from app.db.models.analysis import AnalysisKind, AnalysisStatus
from app.db.models.annotation import TargetType
from app.db.models.job import JobStatus, JobType
from app.errors import install_error_handlers
from app.guest.errors import GuestControlBadResponse, GuestControlRejected, GuestControlUnreachable
from app.guest.http_errors import install_guest_control_error_handler
from app.live.utc import as_utc
from app.samples.store import SampleStore
from tests.analyses.fakes import FakeFreeSpace
from tests.analyses.guest_fakes import ScriptedGuestControl, guest_named
from tests.test_analysis_repository import SHA_A, make_sample

CONTENT = b"MZ\x90\x00 a pretend executable"
OTHER_CONTENT = b"MZ\x90\x00 another pretend executable"
OPTIONS: dict[str, Any] = {
    "route": "inetsim",
    "timeout": 180,
    "package": "auto",
    "interactive": False,
    "memory_dump": False,
    "keep_memory_dump": False,
    "guest": "win",
}


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
class FakeEventIndex:
    dropped: list[int] = field(default_factory=list)
    drop_error: Exception | None = None

    async def drop(self, analysis_id: int) -> None:
        if self.drop_error:
            raise self.drop_error
        self.dropped.append(analysis_id)


@dataclass
class Harness:
    client: httpx.AsyncClient
    app: FastAPI
    factory: async_sessionmaker[AsyncSession]
    store: SampleStore
    runner: FakeRunner
    cape: FakeCape
    guests: ScriptedGuestControl
    index: FakeEventIndex
    storage: Path
    exports: Path
    free_space: FakeFreeSpace

    def start_monitor(self, cape_task_id: int = 7) -> None:
        """Writes the first log the analyzer's monitor makes in the guest."""
        logs = self.storage / "analyses" / str(cape_task_id) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "1234.bson").write_bytes(b"\x05\x00\x00\x00\x00")

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
    runner, cape, index = FakeRunner(), FakeCape(), FakeEventIndex()
    guests = ScriptedGuestControl([guest_named("win"), guest_named("lab1")])
    free_space = FakeFreeSpace()

    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    install_guest_control_error_handler(app)
    app.state.session_factory = factory
    app.include_router(analyses_router, prefix="/api")
    app.dependency_overrides[get_sample_store] = lambda: store
    app.dependency_overrides[get_runner] = lambda: runner
    app.dependency_overrides[get_cape] = lambda: cape
    app.dependency_overrides[get_event_index] = lambda: index
    app.dependency_overrides[get_guest_control] = lambda: guests
    app.dependency_overrides[get_cape_storage_path] = lambda: tmp_path / "cape-storage"
    app.dependency_overrides[get_exports_path] = lambda: tmp_path / "exports"
    app.dependency_overrides[get_imports_dir] = lambda: tmp_path / "imports"
    app.dependency_overrides[get_free_space_probe] = lambda: free_space

    async with make_client(app) as client:
        yield Harness(
            client,
            app,
            factory,
            store,
            runner,
            cape,
            guests,
            index,
            tmp_path / "cape-storage",
            tmp_path / "exports",
            free_space,
        )
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
    options = {
        "route": "none",
        "timeout": 600,
        "package": "dll",
        "interactive": True,
        "memory_dump": True,
        "keep_memory_dump": True,
        "guest": "lab1",
    }

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
        ({"interactive": "maybe"}, ["body", "options", "interactive"]),
        ({"memory_dump": "maybe"}, ["body", "options", "memory_dump"]),
        ({"keep_memory_dump": True}, ["body", "options", "keep_memory_dump"]),
        (
            {"memory_dump": False, "keep_memory_dump": True},
            ["body", "options", "keep_memory_dump"],
        ),
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


async def assert_nothing_was_submitted(harness: Harness) -> None:
    assert await harness.rows(Sample) == []
    assert await harness.rows(Analysis) == []
    assert harness.stored_files() == []
    assert harness.runner.nudges == 0


def message_of(response: httpx.Response) -> str:
    return str(response.json()["error"]["message"])


async def test_a_memory_dump_with_room_is_accepted_without_a_warning(harness: Harness) -> None:
    response = await harness.upload(options={"memory_dump": True})

    assert response.status_code == 201
    assert response.json()["warnings"] == []
    assert response.json()["options"]["memory_dump"] is True


async def test_a_submission_without_a_memory_dump_never_asks_for_the_free_space(
    harness: Harness,
) -> None:
    harness.free_space.unreadable = True

    assert (await harness.upload()).status_code == 201


async def test_a_memory_dump_without_the_room_is_refused_with_the_numbers_and_stores_nothing(
    harness: Harness,
) -> None:
    harness.free_space.free = int(18.2 * 1024)

    response = await harness.upload(options={"memory_dump": True})

    assert response.status_code == 409
    assert message_of(response) == "A memory dump needs 48.8 GB free and 18.2 GB is available"
    await assert_nothing_was_submitted(harness)


async def test_the_room_a_memory_dump_needs_grows_with_the_chosen_guests_ram(
    harness: Harness,
) -> None:
    harness.guests.guests_listed = [guest_named("win", ram_mb=64 * 1024)]
    harness.free_space.free = 80 * 1024

    response = await harness.upload(options={"memory_dump": True})

    assert response.status_code == 409
    assert message_of(response) == "A memory dump needs 84.0 GB free and 80.0 GB is available"


async def test_a_memory_dump_with_little_room_to_spare_is_accepted_with_a_warning(
    harness: Harness,
) -> None:
    harness.free_space.free = 52 * 1024

    response = await harness.upload(options={"memory_dump": True})

    assert response.status_code == 201
    assert response.json()["warnings"] == [
        "Only 52.0 GB is free: a memory dump takes 4.0 GB, "
        "and the disk warning is at 50 GB free before the dump"
    ]


async def test_a_memory_dump_on_a_guest_of_unknown_ram_is_refused(harness: Harness) -> None:
    harness.guests.guests_listed = [guest_named("win", ram_mb=None)]

    response = await harness.upload(options={"memory_dump": True})

    assert response.status_code == 409
    assert "RAM of win" in message_of(response)
    await assert_nothing_was_submitted(harness)


async def test_a_storage_whose_free_space_cannot_be_read_refuses_a_memory_dump(
    harness: Harness,
) -> None:
    harness.free_space.unreadable = True

    response = await harness.upload(options={"memory_dump": True})

    assert response.status_code == 409
    assert "free space of the CAPE storage" in message_of(response)
    await assert_nothing_was_submitted(harness)


async def test_a_guest_that_is_not_ready_is_refused_naming_it_and_its_state(
    harness: Harness,
) -> None:
    harness.guests.guests_listed = [guest_named("win"), guest_named("lab2", "failed")]

    response = await harness.upload(options={"guest": "lab2"})

    assert response.status_code == 409
    assert message_of(response).startswith("lab2 is failed: it cannot run an analysis")
    await assert_nothing_was_submitted(harness)


async def test_a_guest_that_does_not_exist_is_refused_with_409(harness: Harness) -> None:
    response = await harness.upload(options={"guest": "lab9"})

    assert response.status_code == 409
    assert "lab9" in message_of(response)
    await assert_nothing_was_submitted(harness)


async def test_no_guest_built_is_refused_with_409(harness: Harness) -> None:
    harness.guests.guests_listed = []

    response = await harness.upload()

    assert response.status_code == 409
    assert "No guest has been built" in message_of(response)
    await assert_nothing_was_submitted(harness)


async def test_no_guest_ready_is_refused_with_409_listing_the_states(harness: Harness) -> None:
    harness.guests.guests_listed = [guest_named("win", "failed")]

    response = await harness.upload()

    assert response.status_code == 409
    assert "win is failed" in message_of(response)
    await assert_nothing_was_submitted(harness)


@pytest.mark.parametrize(("state", "words"), [("building", "built"), ("testing", "tested")])
async def test_a_guest_in_the_making_blocks_every_submission_even_to_a_ready_guest(
    harness: Harness, state: str, words: str
) -> None:
    harness.guests.guests_listed = [guest_named("win"), guest_named("lab2", state)]  # type: ignore[arg-type]

    response = await harness.upload(options={"guest": "win"})

    assert response.status_code == 409
    assert f"Guest lab2 is being {words}" in message_of(response)
    await assert_nothing_was_submitted(harness)


async def test_a_submission_is_allowed_while_some_guest_is_ready_and_another_is_not(
    harness: Harness,
) -> None:
    # The old gate refused this: the aggregate guest health is `degraded` when one guest is down.
    harness.guests.guests_listed = [guest_named("win"), guest_named("lab2", "failed")]

    assert (await harness.upload()).status_code == 201


async def test_a_control_service_that_cannot_be_asked_is_a_502(harness: Harness) -> None:
    harness.guests.error = GuestControlUnreachable("guests", "ConnectError")

    response = await harness.upload()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "bad_gateway"
    await assert_nothing_was_submitted(harness)


async def test_an_omitted_guest_is_stored_as_the_first_ready_one(harness: Harness) -> None:
    harness.guests.guests_listed = [guest_named("win", "failed"), guest_named("lab1")]

    body = (await harness.upload()).json()

    assert body["options"]["guest"] == "lab1"
    assert body["guest"] == "lab1"


async def test_the_default_guest_setting_is_used_when_the_options_name_none(
    harness: Harness,
) -> None:
    async with harness.factory() as session:
        session.add(Setting(key="default_guest", value="lab1"))
        await session.commit()

    assert (await harness.upload()).json()["options"]["guest"] == "lab1"


@pytest.mark.parametrize("guest", ["Lab1", "1lab", "x", "a_b", "x" * 33])
async def test_a_guest_option_that_is_not_a_guest_name_is_rejected_naming_it(
    harness: Harness, guest: str
) -> None:
    response = await harness.upload(options={"guest": guest})

    assert ["body", "options", "guest"] in error_locations(response)
    await assert_nothing_was_submitted(harness)


async def test_a_package_the_chosen_guest_does_not_accept_is_a_422_naming_the_allowed_ones(
    harness: Harness,
) -> None:
    response = await harness.upload(options={"package": "elf"})

    assert ["body", "options", "package"] in error_locations(response)
    field = response.json()["error"]["details"]["fields"][0]
    assert "auto, exe, dll" in field["message"]
    await assert_nothing_was_submitted(harness)


async def test_a_package_of_the_chosen_guests_profile_is_accepted(harness: Harness) -> None:
    response = await harness.upload(options={"package": "ps1", "guest": "lab1"})

    assert response.status_code == 201


async def test_a_guest_check_that_crashes_is_a_500_and_stores_nothing(harness: Harness) -> None:
    harness.guests.error = RuntimeError("boom")

    assert (await harness.upload()).status_code == 500
    await assert_nothing_was_submitted(harness)


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

    monkeypatch.setattr(submission_module, "add_sample_if_new", other_request_wins)

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

    monkeypatch.setattr(submission_module, "create_analysis", broken)

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

    monkeypatch.setattr(submission_module, "create_analysis", broken)
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


async def tag_analysis(harness: Harness, analysis_id: int, *names: str) -> None:
    async with harness.factory() as session:
        for name in names:
            await annotation_repository.add_tag(
                session, analysis_id, Target(TargetType.ANALYSIS), name
            )


async def test_listing_filters_by_a_tag_on_the_analysis_itself(harness: Harness) -> None:
    tagged = (await harness.upload(name="a.exe")).json()
    other = (await harness.upload(content=OTHER_CONTENT, name="b.exe")).json()
    await tag_analysis(harness, tagged["id"], "emotet")
    async with harness.factory() as session:
        await annotation_repository.add_tag(
            session, other["id"], Target(TargetType.PROCESS, "4"), "emotet"
        )

    body = (await harness.client.get("/api/analyses", params={"tag": "Emotet"})).json()

    assert [item["id"] for item in body["items"]] == [tagged["id"]]
    assert body["total"] == 1


async def test_listing_and_reading_show_the_tags_on_the_analysis_in_name_order(
    harness: Harness,
) -> None:
    tagged = (await harness.upload(name="a.exe")).json()
    plain = (await harness.upload(content=OTHER_CONTENT, name="b.exe")).json()
    await tag_analysis(harness, tagged["id"], "zeta", "alpha")
    async with harness.factory() as session:
        await annotation_repository.add_tag(
            session, plain["id"], Target(TargetType.EVENT, "e1"), "on-an-event"
        )

    listed = (await harness.client.get("/api/analyses")).json()["items"]
    read = (await harness.client.get(f"/api/analyses/{tagged['id']}")).json()

    assert {item["id"]: item["tags"] for item in listed} == {
        tagged["id"]: ["alpha", "zeta"],
        plain["id"]: [],
    }
    assert read["tags"] == ["alpha", "zeta"]


async def test_a_listing_reads_the_tags_of_all_its_analyses_in_one_query(
    harness: Harness,
) -> None:
    for number in range(4):
        created = (await harness.upload(content=bytes([number]) * 8, name=f"{number}.exe")).json()
        await tag_analysis(harness, created["id"], "emotet")
    statements: list[str] = []
    engine = harness.factory.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    await harness.client.get("/api/analyses")

    assert sum("tag_link" in statement for statement in statements) == 1


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


async def test_a_summary_stored_before_the_verdict_existed_is_served_with_empty_defaults(
    harness: Harness,
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], summary={"process_count": 2, "lane_counts": {"api": 4}})

    body = (await harness.client.get(f"/api/analyses/{created['id']}")).json()

    assert body["summary"]["defender"] is None
    assert body["summary"]["hidden_events"] == {}
    assert body["summary"]["memory"] is None


async def test_the_defender_verdict_and_hidden_event_counts_are_served_on_read_and_list(
    harness: Harness,
) -> None:
    created = (await harness.upload()).json()
    verdict = {
        "status": "removed",
        "sample_removed": True,
        "blocked_before_run": True,
        "threats": [
            {
                "detection_id": "{2F76116E-F537-4C6D-9327-BE2C781A26F9}",
                "threat_id": 2147519003,
                "name": "Virus:DOS/EICAR_Test_File",
                "severity": 4,
                "category_id": 42,
                "scope": "sample",
                "path": "C:\\Temp\\321\\eicar.com",
                "process": None,
                "user": None,
                "detected_at": "2026-10-18T23:33:45.000Z",
                "action": "quarantine",
                "outcome": "removed",
                "removed_at": None,
            }
        ],
    }
    hidden = {"windows-background": 3000}
    await harness.set_state(created["id"], summary={"defender": verdict, "hidden_events": hidden})

    read = (await harness.client.get(f"/api/analyses/{created['id']}")).json()
    listed = (await harness.client.get("/api/analyses")).json()["items"][0]

    for summary in (read["summary"], listed["summary"]):
        assert summary["defender"] == verdict
        assert summary["hidden_events"] == hidden


async def test_the_memory_summary_is_served_on_read_and_list(harness: Harness) -> None:
    created = (await harness.upload(options={"memory_dump": True})).json()
    memory = {
        "dump_taken": True,
        "findings": "ok",
        "error": None,
        "dump_bytes": 4_294_776_995,
        "dump_deleted": True,
    }
    await harness.set_state(created["id"], summary={"memory": memory})

    read = (await harness.client.get(f"/api/analyses/{created['id']}")).json()
    listed = (await harness.client.get("/api/analyses")).json()["items"][0]

    assert read["summary"]["memory"] == memory
    assert listed["summary"]["memory"] == memory


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


async def running_analysis(
    harness: Harness, cape_task_id: int | None = 7, *, monitor_started: bool = True
) -> int:
    analysis_id = (await harness.upload()).json()["id"]
    await harness.set_state(analysis_id, status=AnalysisStatus.RUNNING, cape_task_id=cape_task_id)
    if monitor_started and cape_task_id is not None:
        harness.start_monitor(cape_task_id)
    return int(analysis_id)


async def test_an_analysis_whose_monitor_has_not_started_cannot_be_finished_yet(
    harness: Harness,
) -> None:
    # CAPE says `running` about 14 s before the analyzer starts in the guest. Ending the run in that
    # gap made the guest agent stop answering, and CAPE then took minutes to give the analysis up.
    analysis_id = await running_analysis(harness, monitor_started=False)

    response = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert response.status_code == 409
    assert "not started" in response.json()["error"]["message"]
    assert harness.guests.finished == []


async def test_finishing_works_once_the_monitor_has_started(harness: Harness) -> None:
    analysis_id = await running_analysis(harness, monitor_started=False)
    refused = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    harness.start_monitor()
    accepted = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert (refused.status_code, accepted.status_code) == (409, 200)
    assert harness.guests.finished == [(7, "win")]


async def test_a_running_analysis_is_finished_by_asking_cape_to_end_its_task(
    harness: Harness,
) -> None:
    analysis_id = await running_analysis(harness)

    response = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert response.status_code == 200
    assert harness.guests.finished == [(7, "win")]
    body = response.json()
    assert (body["id"], body["cape_task_id"]) == (analysis_id, 7)


async def test_finishing_leaves_the_status_to_the_runner(harness: Harness) -> None:
    analysis_id = await running_analysis(harness)

    response = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert response.json()["status"] == "running"
    assert (await harness.analysis(analysis_id)).status is AnalysisStatus.RUNNING


async def test_finishing_twice_is_fine(harness: Harness) -> None:
    analysis_id = await running_analysis(harness)

    first = await harness.client.post(f"/api/analyses/{analysis_id}/finish")
    second = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert (first.status_code, second.status_code) == (200, 200)
    assert harness.guests.finished == [(7, "win"), (7, "win")]


@pytest.mark.parametrize(
    ("status", "words"),
    [
        (AnalysisStatus.QUEUED, "queued"),
        (AnalysisStatus.STARTING, "not running yet"),
        (AnalysisStatus.PROCESSING, "already over"),
        (AnalysisStatus.INGESTING, "already over"),
        (AnalysisStatus.DONE, "already over"),
        (AnalysisStatus.FAILED, "already over"),
        (AnalysisStatus.REPORT_FAILED, "already over"),
        (AnalysisStatus.CANCELLED, "already over"),
    ],
)
async def test_an_analysis_that_is_not_running_cannot_be_finished_and_the_reason_is_readable(
    harness: Harness, status: AnalysisStatus, words: str
) -> None:
    analysis_id = (await harness.upload()).json()["id"]
    await harness.set_state(analysis_id, status=status, cape_task_id=7)

    response = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert response.status_code == 409
    message = response.json()["error"]["message"]
    assert words in message
    assert status.value in message
    assert harness.guests.finished == []


async def test_a_running_analysis_without_a_cape_task_cannot_be_finished(
    harness: Harness,
) -> None:
    analysis_id = await running_analysis(harness, cape_task_id=None)

    response = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert response.status_code == 409
    assert "no CAPE task" in response.json()["error"]["message"]
    assert harness.guests.finished == []


EXTEND_STARTED = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)
INTERACTIVE_OPTIONS: dict[str, Any] = {**OPTIONS, "interactive": True}


def started_at(seconds: float) -> datetime:
    return EXTEND_STARTED + timedelta(seconds=seconds)


async def interactive_run(
    harness: Harness,
    *,
    deadline_at: datetime | None,
    status: AnalysisStatus = AnalysisStatus.RUNNING,
    options: dict[str, Any] = INTERACTIVE_OPTIONS,
) -> int:
    analysis_id = (await harness.upload(options=options)).json()["id"]
    await harness.set_state(
        analysis_id,
        status=status,
        cape_task_id=7,
        started_at=EXTEND_STARTED,
        deadline_at=deadline_at,
    )
    return int(analysis_id)


def deadline_in(body: dict[str, Any]) -> datetime:
    # SQLite returns naive datetimes; Postgres returns them with the UTC offset.
    return as_utc(datetime.fromisoformat(body["deadline_at"]))


def extend(harness: Harness, analysis_id: int, seconds: object) -> Any:
    return harness.client.post(f"/api/analyses/{analysis_id}/extend", json={"seconds": seconds})


async def test_extending_moves_the_deadline_by_the_seconds_asked(harness: Harness) -> None:
    analysis_id = await interactive_run(harness, deadline_at=started_at(300))

    response = await extend(harness, analysis_id, 60)

    assert response.status_code == 200
    assert deadline_in(response.json()) == started_at(360)
    assert (await harness.analysis(analysis_id)).deadline_at is not None


async def test_an_extension_stops_at_twenty_minutes_after_the_start(harness: Harness) -> None:
    analysis_id = await interactive_run(harness, deadline_at=started_at(1170))

    response = await extend(harness, analysis_id, 600)

    assert response.status_code == 200
    assert deadline_in(response.json()) == started_at(1200)


async def test_a_run_at_its_longest_cannot_be_extended_and_the_reason_says_why(
    harness: Harness,
) -> None:
    analysis_id = await interactive_run(harness, deadline_at=started_at(1200))

    response = await extend(harness, analysis_id, 60)

    assert response.status_code == 409
    assert response.json()["error"]["message"] == ("The run is already at its longest (20 minutes)")
    assert deadline_in((await harness.client.get(f"/api/analyses/{analysis_id}")).json()) == (
        started_at(1200)
    )


async def test_an_interactive_run_that_has_not_started_in_the_guest_cannot_be_extended(
    harness: Harness,
) -> None:
    analysis_id = await interactive_run(harness, deadline_at=None)

    response = await extend(harness, analysis_id, 60)

    assert response.status_code == 409
    assert "wait a few seconds" in response.json()["error"]["message"]
    assert (await harness.analysis(analysis_id)).deadline_at is None


async def test_only_an_interactive_run_can_be_extended(harness: Harness) -> None:
    analysis_id = await interactive_run(
        harness, deadline_at=started_at(300), options={**OPTIONS, "interactive": False}
    )

    response = await extend(harness, analysis_id, 60)

    assert response.status_code == 409
    assert "only an interactive run can be extended" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    "status",
    [AnalysisStatus.QUEUED, AnalysisStatus.DONE, AnalysisStatus.CANCELLED],
)
async def test_only_a_running_analysis_can_be_extended(
    harness: Harness, status: AnalysisStatus
) -> None:
    analysis_id = await interactive_run(harness, deadline_at=started_at(300), status=status)

    response = await extend(harness, analysis_id, 60)

    assert response.status_code == 409
    assert "only a running analysis can be extended" in response.json()["error"]["message"]
    assert (await harness.analysis(analysis_id)).deadline_at == started_at(300).replace(tzinfo=None)


@pytest.mark.parametrize("seconds", [0, 601, -5, "soon", None])
async def test_the_seconds_asked_must_be_a_whole_number_from_1_to_600(
    harness: Harness, seconds: object
) -> None:
    analysis_id = await interactive_run(harness, deadline_at=started_at(300))

    response = await extend(harness, analysis_id, seconds)

    assert response.status_code == 422
    assert ["body", "seconds"] in error_locations(response)


async def test_extending_does_not_end_or_touch_the_guest(harness: Harness) -> None:
    analysis_id = await interactive_run(harness, deadline_at=started_at(300))

    await extend(harness, analysis_id, 60)

    assert harness.guests.finished == []


async def test_the_analysis_shows_its_deadline_only_once_it_has_one(harness: Harness) -> None:
    upload = (await harness.upload()).json()
    deadline_id = await interactive_run(harness, deadline_at=started_at(300))

    assert upload["deadline_at"] is None
    shown = (await harness.client.get(f"/api/analyses/{deadline_id}")).json()
    assert deadline_in(shown) == started_at(300)


async def test_extending_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    response = await extend(harness, 999, 60)

    assert response.status_code == 404


async def test_finishing_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    response = await harness.client.post("/api/analyses/999/finish")

    assert response.status_code == 404
    assert harness.guests.finished == []


@pytest.mark.parametrize(
    "failure",
    [
        GuestControlUnreachable("finish_task", "ConnectError"),
        GuestControlRejected("finish_task", 502, "the guest agent is unreachable (URLError)"),
        GuestControlBadResponse("finish_task", "not a finish"),
    ],
    ids=["unreachable", "rejected", "bad-response"],
)
async def test_a_control_service_that_cannot_end_the_run_is_a_502_in_the_error_envelope(
    harness: Harness, failure: Exception
) -> None:
    analysis_id = await running_analysis(harness)
    harness.guests.finish_error = failure

    response = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "bad_gateway"
    assert str(failure) in error["message"]
    assert (await harness.analysis(analysis_id)).status is AnalysisStatus.RUNNING


async def test_finishing_asks_for_the_guest_the_analysis_ran_on(harness: Harness) -> None:
    analysis_id = (await harness.upload(options={"guest": "lab1"})).json()["id"]
    await harness.set_state(analysis_id, status=AnalysisStatus.RUNNING, cape_task_id=7)
    harness.start_monitor(7)

    await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert harness.guests.finished == [(7, "lab1")]


async def test_an_analysis_that_records_no_guest_cannot_be_finished(harness: Harness) -> None:
    analysis_id = await running_analysis(harness)
    async with harness.factory() as session:
        analysis = await session.get(Analysis, analysis_id)
        assert analysis is not None
        analysis.options = {"route": "inetsim", "timeout": 180}
        await session.commit()

    response = await harness.client.post(f"/api/analyses/{analysis_id}/finish")

    assert response.status_code == 409
    assert "guest" in message_of(response)
    assert harness.guests.finished == []


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


async def test_deleting_an_analysis_drops_its_event_index(harness: Harness) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE, cape_task_id=7)

    response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert harness.index.dropped == [created["id"]]


async def test_the_event_index_goes_after_the_cape_task_and_before_the_rows(
    harness: Harness,
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE, cape_task_id=7)
    seen: dict[str, Any] = {}
    real_drop = harness.index.drop

    async def watching_drop(analysis_id: int) -> None:
        seen["cape_deleted"] = list(harness.cape.deleted)
        seen["rows"] = len(await harness.rows(Analysis))
        await real_drop(analysis_id)

    harness.index.drop = watching_drop  # type: ignore[method-assign]

    await harness.client.delete(f"/api/analyses/{created['id']}")

    assert seen == {"cape_deleted": [(7, "reported")], "rows": 1}


async def test_an_active_analysis_keeps_its_event_index(harness: Harness) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.INGESTING, cape_task_id=7)

    await harness.client.delete(f"/api/analyses/{created['id']}")

    assert harness.index.dropped == []


async def test_an_event_index_that_cannot_be_dropped_never_blocks_deleting_the_analysis(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE)
    harness.index.drop_error = OpenSearchConnectionError("N/A", "opensearch is down", OSError())

    with caplog.at_level(logging.WARNING):
        response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert await harness.rows(Analysis) == []
    assert harness.stored_files() == []
    assert any("index" in record.getMessage() for record in caplog.records)


async def test_deleting_an_analysis_removes_its_exported_files(harness: Harness) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE)
    mine, theirs = harness.exports / str(created["id"]), harness.exports / "9999"
    for directory in (mine, theirs):
        directory.mkdir(parents=True)
        (directory / "report.pdf").write_bytes(b"%PDF")

    response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert not mine.exists()
    assert (theirs / "report.pdf").exists()


async def test_exported_files_that_cannot_be_removed_never_block_deleting_the_analysis(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE)

    def refuse(_root: Path, _analysis_id: int) -> None:
        raise PermissionError("read-only volume")

    monkeypatch.setattr(analyses_api, "remove_analysis_exports", refuse)

    with caplog.at_level(logging.WARNING):
        response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert await harness.rows(Analysis) == []
    assert any("exports" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.RUNNING])
async def test_an_analysis_with_an_export_in_progress_cannot_be_deleted(
    harness: Harness, status: JobStatus
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE)
    async with harness.factory() as session:
        job = await job_repository.create_job(session, JobType.EXPORT_REPORT, created["id"])
        if status is JobStatus.RUNNING:
            await job_repository.mark_running(session, job.id)

    response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 409
    assert "export" in response.json()["error"]["message"]
    assert len(await harness.rows(Analysis)) == 1
    assert harness.index.dropped == []


async def test_an_analysis_whose_export_has_finished_can_be_deleted_with_its_job(
    harness: Harness,
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=AnalysisStatus.DONE)
    async with harness.factory() as session:
        job = await job_repository.create_job(session, JobType.EXPORT_REPORT, created["id"])
        await job_repository.finish_job(session, job.id, JobStatus.DONE, {})

    response = await harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert await harness.rows(Analysis) == []


@pytest.mark.parametrize("earlier", [AnalysisStatus.DONE, AnalysisStatus.REPORT_FAILED])
async def test_a_finished_analysis_is_reingested(harness: Harness, earlier: AnalysisStatus) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(
        created["id"], status=earlier, cape_task_id=7, error="indexing failed", score=6.0
    )
    nudges_before = harness.runner.nudges

    response = await harness.client.post(f"/api/analyses/{created['id']}/reingest")

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["error"], body["finished_at"]) == ("ingesting", None, None)
    assert body["score"] == 6.0
    assert (await harness.analysis(created["id"])).status is AnalysisStatus.INGESTING
    assert harness.runner.nudges == nudges_before + 1


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.QUEUED,
        AnalysisStatus.STARTING,
        AnalysisStatus.RUNNING,
        AnalysisStatus.PROCESSING,
        AnalysisStatus.INGESTING,
        AnalysisStatus.FAILED,
        AnalysisStatus.CANCELLED,
    ],
)
async def test_an_analysis_that_is_not_done_or_report_failed_cannot_be_reingested(
    harness: Harness, status: AnalysisStatus
) -> None:
    created = (await harness.upload()).json()
    await harness.set_state(created["id"], status=status, cape_task_id=7)
    nudges_before = harness.runner.nudges

    response = await harness.client.post(f"/api/analyses/{created['id']}/reingest")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert status.value in error["message"]
    assert (await harness.analysis(created["id"])).status is status
    assert harness.runner.nudges == nudges_before


async def test_nothing_is_reingested_while_another_analysis_is_active(harness: Harness) -> None:
    finished = (await harness.upload()).json()
    await harness.set_state(finished["id"], status=AnalysisStatus.DONE, cape_task_id=7)
    busy = (await harness.upload(content=OTHER_CONTENT)).json()
    await harness.set_state(busy["id"], status=AnalysisStatus.RUNNING, cape_task_id=8)

    response = await harness.client.post(f"/api/analyses/{finished['id']}/reingest")

    assert response.status_code == 409
    assert "another analysis" in response.json()["error"]["message"]
    assert (await harness.analysis(finished["id"])).status is AnalysisStatus.DONE


async def test_reingesting_an_unknown_analysis_is_a_404(harness: Harness) -> None:
    response = await harness.client.post("/api/analyses/999/reingest")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


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
        ("post", "/api/analyses/import"): "analyses_import_capture",
        ("post", "/api/analyses/import/memory-image"): "analyses_import_memory_image",
        ("get", "/api/analyses"): "analyses_list",
        ("get", "/api/analyses/{analysis_id}"): "analyses_read",
        ("post", "/api/analyses/{analysis_id}/cancel"): "analyses_cancel",
        ("delete", "/api/analyses/{analysis_id}"): "analyses_delete",
        ("post", "/api/analyses/{analysis_id}/reingest"): "analyses_reingest",
        ("post", "/api/analyses/{analysis_id}/finish"): "analyses_finish",
        ("post", "/api/analyses/{analysis_id}/extend"): "analyses_extend",
    }
    assert len(set(operations.values())) == len(operations)


def test_the_openapi_schema_describes_the_summary_and_the_upload() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")

    schemas = app.openapi()["components"]["schemas"]

    assert "ReportSummary" in schemas
    assert "lane_counts" in schemas["ReportSummary"]["properties"]
    assert {"defender", "hidden_events"} <= set(schemas["ReportSummary"]["properties"])
    assert {"DefenderVerdict", "DefenderThreat"} <= set(schemas)
    assert set(schemas["Body_analyses_create"]["properties"]) == {"file", "options"}


def test_the_openapi_schema_tells_the_upload_form_about_the_interactive_option() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")

    schemas = app.openapi()["components"]["schemas"]

    assert (
        "`interactive`" in schemas["Body_analyses_create"]["properties"]["options"]["description"]
    )


def test_the_openapi_schema_always_lists_the_queue_position_of_an_analysis() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")

    read = app.openapi()["components"]["schemas"]["AnalysisRead"]

    assert "queue_position" in read["required"]


def guest_calls(harness: Harness) -> int:
    return sum(1 for call, _ in harness.guests.calls if call == "guests")


async def test_a_read_analysis_names_its_guest_and_carries_the_guests_badges(
    harness: Harness,
) -> None:
    harness.guests.guests_listed = [
        guest_named("win", badges=("DEFENDER ON",)),
        guest_named("lab1", badges=("DEFENDER OFF", "SYSMON")),
    ]
    analysis_id = (await harness.upload(options={"guest": "lab1"})).json()["id"]

    body = (await harness.client.get(f"/api/analyses/{analysis_id}")).json()

    assert body["guest"] == "lab1"
    assert body["guest_badges"] == ["DEFENDER OFF", "SYSMON"]


async def test_a_list_page_asks_the_control_service_once_for_all_its_guests(
    harness: Harness,
) -> None:
    harness.guests.guests_listed = [
        guest_named("win", badges=("DEFENDER ON",)),
        guest_named("lab1", badges=("DEFENDER OFF",)),
    ]
    await harness.upload(options={"guest": "win"})
    await harness.upload(options={"guest": "lab1"})
    await harness.upload(options={"guest": "win"})
    harness.guests.calls.clear()

    items = (await harness.client.get("/api/analyses")).json()["items"]

    assert guest_calls(harness) == 1
    assert sorted((item["guest"], tuple(item["guest_badges"])) for item in items) == [
        ("lab1", ("DEFENDER OFF",)),
        ("win", ("DEFENDER ON",)),
        ("win", ("DEFENDER ON",)),
    ]


async def test_reading_an_analysis_never_fails_because_the_control_service_is_down(
    harness: Harness,
) -> None:
    analysis_id = (await harness.upload()).json()["id"]
    harness.guests.error = GuestControlUnreachable("guests", "ConnectError")

    response = await harness.client.get(f"/api/analyses/{analysis_id}")

    assert response.status_code == 200
    assert (response.json()["guest"], response.json()["guest_badges"]) == ("win", [])


async def test_an_analysis_of_a_guest_deleted_since_keeps_the_name_and_has_no_badges(
    harness: Harness,
) -> None:
    analysis_id = (await harness.upload(options={"guest": "lab1"})).json()["id"]
    harness.guests.guests_listed = [guest_named("win", badges=("DEFENDER ON",))]

    body = (await harness.client.get(f"/api/analyses/{analysis_id}")).json()

    assert (body["guest"], body["guest_badges"]) == ("lab1", [])


async def test_an_analysis_that_records_no_guest_reads_without_asking_the_control_service(
    harness: Harness,
) -> None:
    analysis_id = (await harness.upload()).json()["id"]
    async with harness.factory() as session:
        analysis = await session.get(Analysis, analysis_id)
        assert analysis is not None
        analysis.options = {"route": "inetsim", "timeout": 180}
        await session.commit()
    harness.guests.calls.clear()

    body = (await harness.client.get(f"/api/analyses/{analysis_id}")).json()

    assert (body["guest"], body["guest_badges"]) == (None, [])
    assert guest_calls(harness) == 0


def test_the_openapi_schema_always_lists_the_guest_fields_of_an_analysis() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")

    read = app.openapi()["components"]["schemas"]["AnalysisRead"]

    assert {"guest", "guest_badges"} <= set(read["required"])


async def test_a_submitted_analysis_reads_as_a_run(harness: Harness) -> None:
    analysis_id = (await harness.upload()).json()["id"]

    body = (await harness.client.get(f"/api/analyses/{analysis_id}")).json()

    assert body["kind"] == "run"


async def test_an_imported_analysis_without_a_guest_reads_and_lists(harness: Harness) -> None:
    async with harness.factory() as session:
        await repository.add_sample_if_new(session, make_sample())
        imported = await repository.create_analysis(
            session,
            sample_sha256=SHA_A,
            filename="capture.pcap",
            options={},
            kind=AnalysisKind.IMPORTED,
        )
    harness.guests.calls.clear()

    body = (await harness.client.get(f"/api/analyses/{imported.id}")).json()
    listed = (await harness.client.get("/api/analyses")).json()["items"]

    assert (body["kind"], body["guest"], body["guest_badges"]) == ("imported", None, [])
    assert [item["kind"] for item in listed] == ["imported"]
    assert guest_calls(harness) == 0


def test_the_openapi_schema_always_lists_the_kind_of_an_analysis() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(analyses_router, prefix="/api")

    read = app.openapi()["components"]["schemas"]["AnalysisRead"]

    assert "kind" in read["required"]
