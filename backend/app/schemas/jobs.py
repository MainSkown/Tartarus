from datetime import datetime
from typing import Any

from pydantic import ConfigDict

from app.db.models.job import JobStatus, JobType
from app.schemas.base import ApiModel


class JobProgress(ApiModel):
    """A job as `/ws/system` pushes it: where it stands, without the log."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: JobType
    analysis_id: int | None
    status: JobStatus
    step: str
    progress: int
    result: dict[str, Any] | None


class JobRead(JobProgress):
    log: str
    created_at: datetime
    updated_at: datetime
