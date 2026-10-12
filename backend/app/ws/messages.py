from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.health import SystemHealth


class HealthMessage(BaseModel):
    """`/ws/system`'s `health` push: the envelope `{type, ts, data}` from the backend spec's
    WebSockets section, with `data` the same `SystemHealth` shape `GET /api/system/health`
    returns, so the two can never disagree on what health means.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["health"] = "health"
    ts: datetime
    data: SystemHealth
