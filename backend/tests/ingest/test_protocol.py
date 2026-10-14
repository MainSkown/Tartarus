import dataclasses
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from app.ingest.protocol import IngestContext, Normalizer

STARTED = datetime(2026, 10, 13, 10, 12, 18, tzinfo=UTC)


class EmptyNormalizer:
    source = "empty"

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        return iter(())


def test_any_object_with_source_and_normalise_is_a_normalizer() -> None:
    assert isinstance(EmptyNormalizer(), Normalizer)


def test_an_object_without_normalise_is_not_a_normalizer() -> None:
    class Nothing:
        source = "nothing"

    assert not isinstance(Nothing(), Normalizer)


def test_context_is_immutable() -> None:
    context = IngestContext(analysis_id=6, started_at=STARTED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.analysis_id = 7  # type: ignore[misc]


def test_context_refuses_a_naive_start_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        IngestContext(analysis_id=6, started_at=datetime(2026, 10, 13, 10, 12, 18))


def test_context_normalises_the_start_time_to_utc() -> None:
    local = datetime(2026, 10, 13, 12, 12, 18, tzinfo=timezone(timedelta(hours=2)))
    assert IngestContext(analysis_id=6, started_at=local).started_at == STARTED
    assert IngestContext(analysis_id=6, started_at=local).started_at.utcoffset() == timedelta(0)


def test_context_has_no_host_registrations_unless_given() -> None:
    assert IngestContext(analysis_id=6, started_at=STARTED).host_registrations == {}
    registered = {9708: STARTED}
    assert IngestContext(6, STARTED, registered).host_registrations == registered
