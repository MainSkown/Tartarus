import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.version import read_backend_version


def settings_with_commit(commit: str | None) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://user:pw@localhost:5432/db",
        opensearch_url="http://localhost:9200",
        tartarus_commit=commit,
    )


async def test_version_reports_the_release_license_and_the_commit(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: settings_with_commit("abc1234")
    backend = read_backend_version()

    response = await client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": backend.version,
        "commit": "abc1234",
        "license": backend.license,
    }


async def test_version_reports_a_null_commit_when_none_is_configured(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: settings_with_commit(None)

    response = await client.get("/api/version")

    assert response.json()["commit"] is None


def test_the_commit_is_read_from_the_tartarus_commit_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARTARUS_COMMIT", "fedcba9")

    assert (
        Settings(
            database_url="postgresql+asyncpg://user:pw@localhost:5432/db",
            opensearch_url="http://localhost:9200",
        ).tartarus_commit
        == "fedcba9"
    )
