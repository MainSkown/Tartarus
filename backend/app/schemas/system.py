from datetime import datetime

from pydantic import Field

from app.db.models.analysis import AnalysisStatus
from app.schemas.base import ApiModel


class RunningAnalysis(ApiModel):
    id: int
    filename: str
    guest: str | None
    status: AnalysisStatus
    started_at: datetime | None
    elapsed_s: int | None = Field(
        description="Seconds since `started_at`, as of when this queue was read. A client that "
        "shows a running clock counts on `started_at`, not on this value."
    )


class QueuedAnalysis(ApiModel):
    id: int
    filename: str
    guest: str | None
    position: int = Field(
        description="1 is served next on this guest; the line is per guest, so two analyses on "
        "different guests are both position 1."
    )


class QueueSnapshot(ApiModel):
    running: list[RunningAnalysis]
    queued_count: int
    queued: list[QueuedAnalysis]
