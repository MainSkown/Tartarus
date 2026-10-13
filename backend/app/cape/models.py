from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, field_validator


def _as_utc(moment: datetime) -> datetime:
    # CAPE stores naive UTC timestamps (`_utcnow_naive` in lib/cuckoo/core/data/task.py).
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


type UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class MachineCounts(BaseModel):
    total: int
    available: int


class TaskCounts(BaseModel):
    pending: int
    running: int
    completed: int
    reported: int


class CuckooStatus(BaseModel):
    version: str
    machines: MachineCounts
    tasks: TaskCounts


class Machine(BaseModel):
    id: int
    name: str
    label: str
    status: str
    locked: bool
    reserved: bool
    ip: str
    platform: str = ""
    snapshot: str | None = None


class TaskView(BaseModel):
    id: int
    status: str
    machine: str | None = None
    route: str | None = None
    package: str | None = None
    options: str | None = None
    timedout: bool = False
    added_on: UtcDatetime | None = None
    started_on: UtcDatetime | None = None
    completed_on: UtcDatetime | None = None
    reporting_finished_on: UtcDatetime | None = None

    @field_validator("machine", "route", "package", mode="before")
    @classmethod
    def _unset_is_none(cls, value: object) -> object:
        # CAPE's `route` column defaults to the boolean False.
        return value if isinstance(value, str) and value else None
