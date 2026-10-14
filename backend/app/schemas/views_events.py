from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.db.models.analysis import Severity
from app.schemas.base import ApiModel


class ProcessRef(ApiModel):
    pid: int
    name: str | None


class ProcessSummary(ApiModel):
    entity_id: str
    pid: int
    ppid: int | None
    name: str | None
    executable: str | None
    command_line: str | None
    start: datetime | None
    end: datetime | None
    integrity: str | None
    max_severity: Severity | None
    detection_count: int
    injected_into: list[int]
    network_hosts: list[str]
    event_counts_by_lane: dict[str, int]
    tags: list[str] = Field(
        default_factory=list, description="The analyst's tags on this pid, sorted by name."
    )
    note_count: int = Field(default=0, description="The analyst's notes on this pid.")


class ProcessNode(ProcessSummary):
    children: list[ProcessNode]


class ProcessTree(ApiModel):
    roots: list[ProcessNode]
    total: int


class LoadedModule(ApiModel):
    name: str
    path: str | None
    base_address: str | None
    loaded_at: datetime


class ApiCount(ApiModel):
    name: str
    count: int


class ProcessEventRow(ApiModel):
    time: datetime
    action: str
    summary: str
    lane: str
    event_id: str


class ProcessDetail(ProcessSummary):
    modules: list[LoadedModule]
    top_apis: list[ApiCount]
    events: list[ProcessEventRow]
    event_total: int


class DnsRow(ApiModel):
    event_id: str
    time: datetime
    query: str
    type: str | None
    answers: list[str]
    process: ProcessRef | None


class HttpRow(ApiModel):
    event_id: str
    time: datetime
    method: str | None
    url: str
    host: str | None
    status: int | None
    user_agent: str | None
    process: ProcessRef | None


class TlsRow(ApiModel):
    event_id: str
    time: datetime
    server_name: str | None
    ja3: str | None
    ja3s: str | None
    process: ProcessRef | None


class FlowRow(ApiModel):
    event_id: str
    time: datetime
    transport: str | None
    source_ip: str | None
    source_port: int | None
    destination_ip: str | None
    destination_port: int | None
    process: ProcessRef | None


class NetworkAlertRow(ApiModel):
    event_id: str
    time: datetime
    signature: str
    severity: Severity
    process: ProcessRef | None


class HostRow(ApiModel):
    host: str
    kind: str
    count: int
    related: list[str]


class Listing[T](ApiModel):
    """The first `items` of a list; `total` counts every row, so a capped list can say so."""

    items: list[T]
    total: int


class NetworkView(ApiModel):
    dns: Listing[DnsRow]
    http: Listing[HttpRow]
    tls: Listing[TlsRow]
    flows: Listing[FlowRow]
    alerts: Listing[NetworkAlertRow]
    hosts: Listing[HostRow]
    simulated: bool


class RegistryChange(ApiModel):
    event_id: str
    time: datetime
    action: str
    value_name: str | None
    data_type: str | None
    data: list[str]
    process: ProcessRef | None


class RegistryKeyGroup(ApiModel):
    key: str
    hive: str | None
    changes: list[RegistryChange]


class RegistryView(ApiModel):
    keys: list[RegistryKeyGroup]
    total: int
