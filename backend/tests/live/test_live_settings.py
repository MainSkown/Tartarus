import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def required_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/tartarus")
    monkeypatch.setenv("OPENSEARCH_URL", "http://opensearch:9200")
    monkeypatch.delenv("LIVE_POLL_INTERVAL_SECONDS", raising=False)


def test_the_live_collector_polls_four_times_a_second_unless_told_otherwise() -> None:
    assert Settings().live_poll_interval_seconds == 0.25


def test_the_live_poll_interval_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_POLL_INTERVAL_SECONDS", "1.5")

    assert Settings().live_poll_interval_seconds == 1.5
