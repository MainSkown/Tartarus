from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class IngestContext:
    """What a normaliser knows about the analysis beyond the report itself.

    `started_at` is the analysis start in UTC, which is CAPE's `info.started` as it stands (the
    host's clock is UTC); a naive datetime is refused here rather than silently shifting a whole
    timeline.

    `host_registrations` is when the host logged each process registering (pid to UTC time, see
    `app.ingest.clock`); it anchors the guest clock exactly and may be empty.

    `analysis_dir` is the folder of CAPE's task, where the sources that are not part of
    `report.json` leave their files (`sysmon/sysmon.xml`, `aux/defender.xml`); `None` when the
    caller has no folder to offer.
    """

    analysis_id: int
    started_at: datetime
    host_registrations: Mapping[int, datetime] = field(default_factory=dict)
    analysis_dir: Path | None = None

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
