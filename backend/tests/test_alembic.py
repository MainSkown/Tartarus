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


def test_the_paused_job_status_is_added_by_replacing_the_status_check_constraint(
    alembic_config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    command.upgrade(alembic_config, "0005:0006", sql=True)

    sql = capsys.readouterr().out
    assert "DROP CONSTRAINT ck_job_job_status" in sql
    assert "ADD CONSTRAINT ck_job_job_status CHECK" in sql
    assert "'paused'" in sql


def test_downgrading_ends_the_paused_jobs_before_the_constraint_forbids_them(
    alembic_config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    command.downgrade(alembic_config, "0006:0005", sql=True)

    sql = capsys.readouterr().out
    assert sql.index("UPDATE job SET status='interrupted'") < sql.index("ADD CONSTRAINT")
    assert "'paused'" in sql.split("ADD CONSTRAINT")[0]
    assert "'paused'" not in sql.split("ADD CONSTRAINT")[1]


def test_the_deadline_is_added_as_a_nullable_timezone_aware_column_on_the_analysis(
    alembic_config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    command.upgrade(alembic_config, "0006:0007", sql=True)

    sql = capsys.readouterr().out
    assert "ALTER TABLE analysis ADD COLUMN deadline_at TIMESTAMP WITH TIME ZONE" in sql
    assert "deadline_at TIMESTAMP WITH TIME ZONE NOT NULL" not in sql


def test_downgrading_drops_the_deadline_column(
    alembic_config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    command.downgrade(alembic_config, "0007:0006", sql=True)

    assert "ALTER TABLE analysis DROP COLUMN deadline_at" in capsys.readouterr().out


def test_the_kind_is_added_as_a_checked_text_column_defaulting_to_run(
    alembic_config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    command.upgrade(alembic_config, "0007:0008", sql=True)

    sql = capsys.readouterr().out
    assert "ALTER TABLE analysis ADD COLUMN kind VARCHAR(8) DEFAULT 'run' NOT NULL" in sql
    assert "CONSTRAINT ck_analysis_analysis_kind CHECK (kind IN ('run', 'imported'))" in sql


def test_downgrading_drops_the_kind_column(
    alembic_config: Config, capsys: pytest.CaptureFixture[str]
) -> None:
    command.downgrade(alembic_config, "0008:0007", sql=True)

    assert "ALTER TABLE analysis DROP COLUMN kind" in capsys.readouterr().out
