"""The JSON messages of `WS /ws/analyses/{id}/live`, each `{type, ts, data}` (backend spec)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.analysis import AnalysisPhase, AnalysisStatus

LIVE_INDEX_FAILED = "live_index_failed"
LOG_FORMAT = "log_format"
QUERY_UNSUPPORTED = "query_unsupported"
BAD_MESSAGE = "bad_message"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveProcess(_Strict):
    pid: int
    ppid: int | None = None
    name: str | None = None
    executable: str | None = None
    command_line: str | None = None
    start: str | None = None
    end: str | None = None


class StatusData(_Strict):
    status: AnalysisStatus
    phase: AnalysisPhase
    elapsed_s: float | None
    remaining_s: float | None


class EventsData(_Strict):
    events: list[dict[str, Any]]
    dropped: int = 0


class ProcessData(_Strict):
    op: Literal["add", "update", "end"]
    node: LiveProcess


class CountsData(_Strict):
    by_lane: dict[str, int]
    by_severity: dict[str, int]
    total: int


class PhaseData(_Strict):
    phase: Literal["final"] = "final"


class ErrorData(_Strict):
    code: str
    message: str


class PongData(_Strict):
    pass


class StatusMessage(_Strict):
    type: Literal["status"] = "status"
    ts: datetime
    data: StatusData


class EventsMessage(_Strict):
    type: Literal["events"] = "events"
    ts: datetime
    data: EventsData


class ProcessMessage(_Strict):
    type: Literal["process"] = "process"
    ts: datetime
    data: ProcessData


class CountsMessage(_Strict):
    type: Literal["counts"] = "counts"
    ts: datetime
    data: CountsData


class PhaseMessage(_Strict):
    type: Literal["phase"] = "phase"
    ts: datetime
    data: PhaseData


class ErrorMessage(_Strict):
    type: Literal["error"] = "error"
    ts: datetime
    data: ErrorData


class PongMessage(_Strict):
    type: Literal["pong"] = "pong"
    ts: datetime
    data: PongData = Field(default_factory=PongData)


type LiveMessage = Annotated[
    StatusMessage
    | EventsMessage
    | ProcessMessage
    | CountsMessage
    | PhaseMessage
    | ErrorMessage
    | PongMessage,
    Field(discriminator="type"),
]


class SubscribeData(_Strict):
    lanes: list[str] | None = None
    pids: list[int] | None = None
    include_api: bool = False
    query: str | None = None


class SubscribeMessage(_Strict):
    type: Literal["subscribe"] = "subscribe"
    data: SubscribeData = Field(default_factory=SubscribeData)


class PingMessage(_Strict):
    type: Literal["ping"] = "ping"


type ClientMessage = Annotated[SubscribeMessage | PingMessage, Field(discriminator="type")]
