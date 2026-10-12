import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "OPENSEARCH_URL", "ENVIRONMENT", "LOG_LEVEL"):
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
