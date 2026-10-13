from pathlib import Path

import pytest

from app.analyses.runner import RunnerConfig
from app.config import Settings


@pytest.fixture(autouse=True)
def required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://opensearch:9200")
    for name in ("RUNNER_POLL_INTERVAL_SECONDS", "RUNNER_UNREACHABLE_GRACE_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def test_the_runner_polls_every_two_seconds_and_waits_two_minutes_for_cape_by_default() -> None:
    config = RunnerConfig.from_settings(Settings())

    assert config.poll_interval == 2.0
    assert config.unreachable_grace == 120.0


def test_the_runner_timings_and_paths_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNNER_POLL_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("RUNNER_UNREACHABLE_GRACE_SECONDS", "30")
    monkeypatch.setenv("CAPE_STORAGE_PATH", "/mnt/cape")
    monkeypatch.setenv("GUEST_LABEL", "win11")

    config = RunnerConfig.from_settings(Settings())

    assert config == RunnerConfig(
        cape_storage_path=Path("/mnt/cape"),
        guest_label="win11",
        poll_interval=0.5,
        unreachable_grace=30.0,
    )
