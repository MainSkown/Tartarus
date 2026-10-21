import hashlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.analyses import router as analyses_router
from app.api.dependencies import (
    get_cape,
    get_event_index,
    get_exports_path,
    get_guest_control,
    get_runner,
    get_sample_store,
)
from app.api.operation_ids import generate_operation_id
from app.config import Settings, get_settings
from app.db.analysis_repository import update_analysis
from app.db.base import Base
from app.db.models import Analysis, Sample
from app.db.models.analysis import AnalysisKind, AnalysisStatus
from app.errors import install_error_handlers
from app.samples.store import SampleStore
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.test_analyses_api import FakeCape, FakeEventIndex, FakeRunner

PCAP = bytes.fromhex("d4c3b2a1") + b"\x02\x00\x04\x00" + b"\x00" * 40
PCAPNG = bytes.fromhex("0a0d0d0a") + b"\x1c\x00\x00\x00" + b"\x00" * 40
MEMORY_IMAGE = b"\x7fELF" + b"\x02\x01\x01\x00" + b"\x00" * 40
GARBAGE = b"MZ\x90\x00 not a capture"
PLAIN = "/api/analyses/import"
MEMORY_PATH = "/api/analyses/import/memory-image"


@dataclass
class ImportHarness:
    client: httpx.AsyncClient
    app: FastAPI
    factory: async_sessionmaker[AsyncSession]
    runner: FakeRunner
    imports: Path
    samples: Path

    def limit(self, *, pcap: int | None = None, memory_image: int | None = None) -> None:
        settings = self.app.dependency_overrides[get_settings]()
        update = {
            "import_pcap_max_bytes": pcap or settings.import_pcap_max_bytes,
            "import_memory_image_max_bytes": memory_image or settings.import_memory_image_max_bytes,
        }
        self.app.dependency_overrides[get_settings] = lambda: settings.model_copy(update=update)

    async def upload(
        self, content: bytes, path: str = PLAIN, name: str = "capture.pcap"
    ) -> httpx.Response:
        return await self.client.post(path, files={"file": (name, content)})

    async def rows[T](self, model: type[T]) -> list[T]:
        async with self.factory() as session:
            return list((await session.scalars(select(model))).all())  # type: ignore[arg-type]

    def files_under_imports(self) -> list[str]:
        return sorted(
            str(path.relative_to(self.imports))
            for path in self.imports.rglob("*")
            if path.is_file()
        )


@pytest.fixture
async def imports_harness(
    tmp_path: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[ImportHarness]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'import.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    imports, samples, runner = tmp_path / "imports", tmp_path / "samples", FakeRunner()
    settings = Settings(
        database_url="postgresql+asyncpg://unused",
        opensearch_url="http://unused",
        imports_dir=imports,
    )

    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    app.include_router(analyses_router, prefix="/api")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_runner] = lambda: runner
    app.dependency_overrides[get_guest_control] = lambda: ScriptedGuestControl([])
    app.dependency_overrides[get_sample_store] = lambda: SampleStore(samples)
    cape, index = FakeCape(), FakeEventIndex()
    app.dependency_overrides[get_cape] = lambda: cape
    app.dependency_overrides[get_event_index] = lambda: index
    app.dependency_overrides[get_exports_path] = lambda: tmp_path / "exports"

    async with make_client(app) as client:
        yield ImportHarness(client, app, factory, runner, imports, samples)
    await engine.dispose()


async def test_a_pcap_is_imported_as_a_queued_analysis_without_a_guest(
    imports_harness: ImportHarness,
) -> None:
    response = await imports_harness.upload(PCAP)

    assert response.status_code == 201
    body = response.json()
    assert (body["kind"], body["status"], body["guest"]) == ("imported", "queued", None)
    assert body["filename"] == "capture.pcap"
    assert body["options"] == {
        "import": {"kind": "pcap", "filename": "capture.pcap", "size": len(PCAP)}
    }
    assert body["sample_sha256"] == hashlib.sha256(PCAP).hexdigest()


async def test_the_upload_is_kept_at_the_path_the_runner_reads(
    imports_harness: ImportHarness,
) -> None:
    body = (await imports_harness.upload(PCAP)).json()

    assert (imports_harness.imports / str(body["id"]) / "upload").read_bytes() == PCAP
    assert imports_harness.files_under_imports() == [f"{body['id']}/upload"]


async def test_the_analysis_is_stored_as_imported_and_the_runner_is_woken(
    imports_harness: ImportHarness,
) -> None:
    await imports_harness.upload(PCAP)

    (analysis,) = await imports_harness.rows(Analysis)
    assert (analysis.kind, analysis.status) == (AnalysisKind.IMPORTED, AnalysisStatus.QUEUED)
    assert imports_harness.runner.nudges == 1


async def test_the_sample_is_recorded_by_hash_without_a_copy_in_the_sample_store(
    imports_harness: ImportHarness,
) -> None:
    await imports_harness.upload(PCAP)

    (sample,) = await imports_harness.rows(Sample)
    assert sample.sha256 == hashlib.sha256(PCAP).hexdigest()
    assert (sample.size, sample.original_name) == (len(PCAP), "capture.pcap")
    assert not imports_harness.samples.exists()


async def test_a_pcapng_is_imported_as_the_pcap_kind(imports_harness: ImportHarness) -> None:
    body = (await imports_harness.upload(PCAPNG, name="trace.pcapng")).json()

    assert body["options"]["import"]["kind"] == "pcap"


async def test_the_file_name_is_shortened_to_its_last_part(imports_harness: ImportHarness) -> None:
    body = (await imports_harness.upload(PCAP, name="C:\\captures\\lab.pcap")).json()

    assert body["filename"] == "lab.pcap"
    assert body["options"]["import"]["filename"] == "lab.pcap"


async def test_a_memory_image_is_imported_on_its_own_path(imports_harness: ImportHarness) -> None:
    response = await imports_harness.upload(MEMORY_IMAGE, MEMORY_PATH, name="host.raw")

    assert response.status_code == 201
    body = response.json()
    assert body["options"]["import"] == {
        "kind": "memory_image",
        "filename": "host.raw",
        "size": len(MEMORY_IMAGE),
    }
    assert (imports_harness.imports / str(body["id"]) / "upload").read_bytes() == MEMORY_IMAGE


async def test_a_pcap_is_also_accepted_on_the_memory_image_path(
    imports_harness: ImportHarness,
) -> None:
    response = await imports_harness.upload(PCAP, MEMORY_PATH)

    assert response.status_code == 201
    assert response.json()["options"]["import"]["kind"] == "pcap"


@pytest.mark.parametrize("path", [PLAIN, MEMORY_PATH])
async def test_a_file_that_is_neither_is_refused_with_415_and_leaves_nothing(
    imports_harness: ImportHarness, path: str
) -> None:
    response = await imports_harness.upload(GARBAGE, path)

    assert response.status_code == 415
    await assert_nothing_kept(imports_harness)


async def test_a_memory_image_on_the_plain_path_is_refused_pointing_to_its_own_path(
    imports_harness: ImportHarness,
) -> None:
    response = await imports_harness.upload(MEMORY_IMAGE)

    assert response.status_code == 415
    assert MEMORY_PATH in response.json()["error"]["message"]
    await assert_nothing_kept(imports_harness)


async def test_a_pcap_over_the_limit_is_refused_with_413_and_the_partial_file_removed(
    imports_harness: ImportHarness,
) -> None:
    imports_harness.limit(pcap=len(PCAP) - 1)

    response = await imports_harness.upload(PCAP)

    assert response.status_code == 413
    await assert_nothing_kept(imports_harness)


async def test_a_memory_image_over_its_limit_is_refused_with_413(
    imports_harness: ImportHarness,
) -> None:
    imports_harness.limit(memory_image=len(MEMORY_IMAGE) - 1)

    response = await imports_harness.upload(MEMORY_IMAGE, MEMORY_PATH)

    assert response.status_code == 413
    await assert_nothing_kept(imports_harness)


async def test_the_pcap_limit_does_not_apply_to_a_memory_image(
    imports_harness: ImportHarness,
) -> None:
    imports_harness.limit(pcap=8)

    response = await imports_harness.upload(MEMORY_IMAGE, MEMORY_PATH)

    assert response.status_code == 201


async def test_an_empty_file_is_refused_naming_the_field(imports_harness: ImportHarness) -> None:
    response = await imports_harness.upload(b"")

    assert response.status_code == 422
    await assert_nothing_kept(imports_harness)


async def test_the_same_capture_imported_twice_makes_two_analyses_on_one_sample(
    imports_harness: ImportHarness,
) -> None:
    first = (await imports_harness.upload(PCAP)).json()
    second = (await imports_harness.upload(PCAP)).json()

    assert first["id"] != second["id"]
    assert len(await imports_harness.rows(Sample)) == 1
    assert len(imports_harness.files_under_imports()) == 2


async def test_deleting_an_imported_analysis_removes_its_upload_and_its_sample_row(
    imports_harness: ImportHarness,
) -> None:
    created = (await imports_harness.upload(PCAP)).json()
    async with imports_harness.factory() as session:
        await update_analysis(session, created["id"], status=AnalysisStatus.DONE)

    response = await imports_harness.client.delete(f"/api/analyses/{created['id']}")

    assert response.status_code == 204
    assert imports_harness.files_under_imports() == []
    assert await imports_harness.rows(Sample) == []


async def assert_nothing_kept(imports_harness: ImportHarness) -> None:
    assert await imports_harness.rows(Analysis) == []
    assert await imports_harness.rows(Sample) == []
    assert imports_harness.files_under_imports() == []
    assert imports_harness.runner.nudges == 0
