from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from alembic import command
from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://localhost:9200")
    get_settings.cache_clear()
    yield Config(str(BACKEND_DIR / "alembic.ini"))
    get_settings.cache_clear()


def test_script_directory_is_the_committed_versions_folder(alembic_config: Config) -> None:
    script = ScriptDirectory.from_config(alembic_config)

    assert Path(script.versions) == BACKEND_DIR / "alembic" / "versions"


def test_env_runs_offline_with_the_database_url_from_settings(
    alembic_config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    command.upgrade(alembic_config, "head", sql=True)

    assert "BEGIN;" in capsys.readouterr().out


def test_env_needs_the_database_url_from_settings(
    alembic_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL")

    with pytest.raises(ValidationError):
        command.upgrade(alembic_config, "head", sql=True)
