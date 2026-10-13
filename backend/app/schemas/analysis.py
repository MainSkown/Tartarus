from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.models.analysis import AnalysisPhase, AnalysisStatus, Severity


class AnalysisRead(BaseModel):
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
    summary: dict[str, Any] | None
