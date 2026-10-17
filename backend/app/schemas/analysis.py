from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from app.analyses.summary import ReportSummary
from app.db.models.analysis import AnalysisPhase, AnalysisStatus, Severity
from app.schemas.base import ApiModel


class AnalysisRead(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sample_sha256: str
    filename: str
    cape_task_id: int | None
    status: AnalysisStatus
    phase: AnalysisPhase
    options: dict[str, Any]
    score: float | None
    max_severity: Severity | None
    detected_families: list[str]
    event_count: int
    disk_bytes: int
    error: str | None
    submitted_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    deadline_at: datetime | None = Field(
        default=None,
        description="When an interactive run ends unless the analyst extends it; null otherwise.",
    )
    summary: ReportSummary | None
    tags: list[str] = Field(
        default_factory=list, description="The analyst's tags on the analysis itself, by name."
    )
    guest: str | None = Field(
        default=None, description="The guest the analysis runs on; the stored name even if deleted."
    )
    guest_badges: list[str] = Field(
        default_factory=list,
        description='The guest\'s badges ("DEFENDER ON"); empty when the guest is gone or the '
        "guest control service cannot be asked.",
    )
    queue_position: int | None = Field(
        default=None, description="1 for the analysis served next; null unless `queued`."
    )
