from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class IngestContext:
    """What a normaliser knows about the analysis beyond the report itself.

    `started_at` is the analysis start in UTC. CAPE's `info.started` is the host's local time, so
    the caller converts it; a naive datetime is refused here rather than silently shifting a
    whole timeline.
    """

    analysis_id: int
    started_at: datetime

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must carry a timezone")
        object.__setattr__(self, "started_at", self.started_at.astimezone(UTC))


@runtime_checkable
class Normalizer(Protocol):
    """Public interface: turns one source's records into event documents.

    `source` names the normaliser (`capemon`, `sysmon`, ...) and is part of every event id.
    `normalise` yields event documents shaped by the field catalog, built through
    `app.ingest.ecs.EventFactory`. It must not raise on unknown or malformed records: it skips
    the part it cannot map and keeps the rest. It must not mutate `report`.
    """

    source: str

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]: ...
