from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.health import SystemHealth
from app.schemas.jobs import JobProgress


class HealthMessage(BaseModel):
    """`/ws/system`'s `health` push: the envelope `{type, ts, data}` from the backend spec's
    WebSockets section, with `data` the same `SystemHealth` shape `GET /api/system/health`
    returns, so the two can never disagree on what health means.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["health"] = "health"
    ts: datetime
    data: SystemHealth


class JobMessage(BaseModel):
    """`/ws/system`'s `job` push: sent whenever a job is submitted, starts, reports progress or
    ends, and once per still-active job when a client connects.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["job"] = "job"
    job: JobProgress
