from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.analyses.summary import ReportSummary
from app.db.models.analysis import AnalysisPhase, AnalysisStatus, Severity


class AnalysisRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

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
    summary: ReportSummary | None
    queue_position: int | None = Field(
        default=None, description="1 for the analysis served next; null unless `queued`."
    )
