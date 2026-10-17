from datetime import UTC, datetime, timedelta

from app.analyses.deadline import (
    MAX_RUN_S,
    at_the_latest,
    extended_deadline,
    initial_deadline,
    latest_deadline,
)

STARTED = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return STARTED + timedelta(seconds=seconds)


def test_cape_runs_an_interactive_task_for_at_most_twenty_minutes() -> None:
    assert MAX_RUN_S == 1200


def test_the_latest_deadline_is_twenty_minutes_after_the_start() -> None:
    assert latest_deadline(STARTED) == at(1200)


def test_the_initial_deadline_is_the_timeout_counted_from_the_monitor() -> None:
    assert initial_deadline(at(25), STARTED, timeout_s=180) == at(205)


def test_the_initial_deadline_never_passes_the_latest_one() -> None:
    assert initial_deadline(at(25), STARTED, timeout_s=1200) == at(1200)


def test_an_extension_adds_its_seconds_to_the_current_deadline() -> None:
    assert extended_deadline(at(205), STARTED, seconds=60) == at(265)


def test_an_extension_is_clamped_to_the_latest_deadline() -> None:
    assert extended_deadline(at(1170), STARTED, seconds=600) == at(1200)


def test_an_extension_from_the_latest_deadline_stays_there() -> None:
    assert extended_deadline(at(1200), STARTED, seconds=60) == at(1200)


def test_the_run_is_at_its_longest_once_the_deadline_is_the_latest_one() -> None:
    assert at_the_latest(at(1200), STARTED)
    assert at_the_latest(at(1250), STARTED)


def test_the_run_is_not_at_its_longest_before_the_latest_deadline() -> None:
    assert not at_the_latest(at(1199), STARTED)
