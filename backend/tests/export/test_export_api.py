import csv
import io
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.annotations.validation import Target
from app.api import export as export_api
from app.api.dependencies import get_cape_storage_path, get_event_index
from app.api.export import load_export_annotations
from app.api.export import router as export_router
from app.api.operation_ids import generate_operation_id
from app.db import annotation_repository
from app.db.base import Base
from app.db.models.annotation import TargetType as StoredTargetType
from app.errors import install_error_handlers
from app.export.inputs import ExportAnnotations, ExportNote, TargetType
from app.schemas.views_findings import IocsView
from app.views.artifacts import AnalysisFiles
from tests.export.conftest import EVERY_TYPE
from tests.export.validation import misp_problems, parse_stix
from tests.test_analysis_repository import _enable_foreign_keys, seeded_analysis


class StubIndex:
    pass


@pytest.fixture
async def export_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FastAPI]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'export.sqlite3'}")
    event.listen(engine.sync_engine, "connect", _enable_foreign_keys)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seeded_analysis(session, filename="invoice.exe")

    async def collect(_index: object, _analysis: object, _files: AnalysisFiles) -> IocsView:
        return IocsView(iocs=list(EVERY_TYPE), truncated_types=[])

    monkeypatch.setattr(export_api, "collect_iocs", collect)
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = factory
    app.include_router(export_router, prefix="/api")
    app.dependency_overrides[get_event_index] = StubIndex
    app.dependency_overrides[get_cape_storage_path] = lambda: tmp_path / "cape"
    yield app
    await engine.dispose()


@pytest.fixture
async def client(
    export_app: FastAPI, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(export_app) as http_client:
        yield http_client


def download(client: httpx.AsyncClient, format_: str, analysis_id: int = 1) -> Any:
    return client.get(f"/api/analyses/{analysis_id}/export/iocs", params={"format": format_})


async def test_stix_downloads_as_a_valid_bundle(client: httpx.AsyncClient) -> None:
    response = await download(client, "stix")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/stix+json;version=2.1"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="tartarus-1-iocs.stix.json"'
    )
    parse_stix(response.json())
    patterns = {o["pattern"] for o in response.json()["objects"] if o["type"] == "indicator"}
    assert "[domain-name:value = 'evil.example']" in patterns


async def test_misp_downloads_as_a_valid_event_with_the_sample_hashes(
    client: httpx.AsyncClient,
) -> None:
    response = await download(client, "misp")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="tartarus-1-iocs.misp.json"'
    )
    document = response.json()
    assert misp_problems(document) == []
    assert document["Event"]["info"] == "Tartarus analysis #1 \N{EN DASH} invoice.exe"
    types = {a["type"] for a in document["Event"]["Attribute"]}
    assert {"md5", "sha1", "sha256"} <= types


async def test_csv_downloads_with_its_header_and_one_row_per_ioc(
    client: httpx.AsyncClient,
) -> None:
    response = await download(client, "csv")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="tartarus-1-iocs.csv"'
    rows = list(csv.reader(io.StringIO(response.text, newline="")))
    assert rows[0] == ["type", "value", "context", "first_seen", "source_process"]
    assert len(rows) == 1 + len(EVERY_TYPE)


async def test_an_unknown_analysis_is_a_404_in_the_error_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await download(client, "csv", analysis_id=99)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("params", [{"format": "pdf"}, {"format": ""}, {}])
async def test_a_missing_or_unknown_format_is_a_422_in_the_error_envelope(
    client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    response = await client.get("/api/analyses/1/export/iocs", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["fields"][0]["location"] == ["query", "format"]


async def test_the_annotations_come_from_the_one_loader_function(
    export_app: FastAPI, client: httpx.AsyncClient
) -> None:
    annotations = ExportAnnotations(
        tags=("tlp:red", "phishing"),
        notes=(ExportNote("Seen in a campaign.", TargetType.ANALYSIS, None),),
    )

    async def loaded() -> ExportAnnotations:
        return annotations

    export_app.dependency_overrides[load_export_annotations] = loaded

    document = json.loads((await download(client, "misp")).content)

    names = [tag["name"] for tag in document["Event"]["Tag"]]
    assert names[:2] == ["tlp:red", "phishing"]
    comments = [a for a in document["Event"]["Attribute"] if a["type"] == "comment"]
    assert [a["value"] for a in comments] == ["Seen in a campaign."]


async def test_the_stored_tags_and_notes_of_the_analysis_are_exported(
    export_app: FastAPI, client: httpx.AsyncClient
) -> None:
    whole = Target(StoredTargetType.ANALYSIS)
    async with export_app.state.session_factory() as session:
        await annotation_repository.add_tag(session, 1, whole, "tlp:red")
        await annotation_repository.add_tag(session, 1, whole, "phishing")
        await annotation_repository.add_note(session, 1, whole, "Seen in a campaign.")

    document = (await download(client, "misp")).json()

    names = [tag["name"] for tag in document["Event"]["Tag"]]
    assert names[:2] == ["tlp:red", "phishing"]
    comments = [a for a in document["Event"]["Attribute"] if a["type"] == "comment"]
    assert [a["value"] for a in comments] == ["Seen in a campaign."]


async def test_without_annotations_the_event_is_marked_tlp_amber(
    client: httpx.AsyncClient,
) -> None:
    document = (await download(client, "misp")).json()

    assert [tag["name"] for tag in document["Event"]["Tag"]] == ["tlp:amber"]


def test_the_route_has_a_stable_operation_id(export_app: FastAPI) -> None:
    operation = export_app.openapi()["paths"]["/api/analyses/{analysis_id}/export/iocs"]["get"]

    assert operation["operationId"] == "export_iocs"
    assert {p["name"] for p in operation["parameters"]} == {"analysis_id", "format"}


def test_the_real_app_serves_the_export_route_and_documents_every_media_type(
    app: FastAPI,
) -> None:
    operation = app.openapi()["paths"]["/api/analyses/{analysis_id}/export/iocs"]["get"]

    assert set(operation["responses"]["200"]["content"]) == {
        "application/stix+json;version=2.1",
        "application/json",
        "text/csv; charset=utf-8",
    }
