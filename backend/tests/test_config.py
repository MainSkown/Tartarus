from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "OPENSEARCH_URL",
        "ENVIRONMENT",
        "LOG_LEVEL",
        "CAPE_API_URL",
        "CAPE_API_TOKEN",
        "CAPE_STORAGE_PATH",
        "SAMPLE_STORE_PATH",
        "GUEST_LABEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_reads_every_field_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://opensearch:9200")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/tartarus"
    assert settings.opensearch_url == "http://opensearch:9200"
    assert settings.environment == "production"
    assert settings.log_level == "debug"


def test_environment_and_log_level_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://opensearch:9200")

    settings = Settings()

    assert settings.environment == "production"
    assert settings.log_level == "info"


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://opensearch:9200")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    assert Settings().log_level == "info"


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://opensearch:9200")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings()


def test_connection_urls_are_required() -> None:
    with pytest.raises(ValidationError) as error:
        Settings()

    missing = {issue["loc"][0] for issue in error.value.errors()}
    assert missing == {"database_url", "opensearch_url"}


@pytest.fixture
def required_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://opensearch:9200")


@pytest.mark.usefixtures("required_urls")
def test_cape_settings_have_the_documented_defaults() -> None:
    settings = Settings()

    assert settings.cape_api_url == "http://cape:8000"
    assert settings.cape_api_token is None
    assert settings.cape_storage_path == Path("/cape-storage")
    assert settings.sample_store_path == Path("/data/samples")
    assert settings.guest_label == "win"


@pytest.mark.usefixtures("required_urls")
def test_cape_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPE_API_URL", "http://localhost:8000")
    monkeypatch.setenv("CAPE_API_TOKEN", "s3cret")
    monkeypatch.setenv("CAPE_STORAGE_PATH", "/mnt/cape")
    monkeypatch.setenv("SAMPLE_STORE_PATH", "/mnt/samples")
    monkeypatch.setenv("GUEST_LABEL", "win11")

    settings = Settings()

    assert settings.cape_api_url == "http://localhost:8000"
    assert settings.cape_api_token is not None
    assert settings.cape_api_token.get_secret_value() == "s3cret"
    assert settings.cape_storage_path == Path("/mnt/cape")
    assert settings.sample_store_path == Path("/mnt/samples")
    assert settings.guest_label == "win11"


@pytest.mark.usefixtures("required_urls")
def test_cape_token_is_not_shown_in_the_settings_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPE_API_TOKEN", "s3cret")

    assert "s3cret" not in repr(Settings())
