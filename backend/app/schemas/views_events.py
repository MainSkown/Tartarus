from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models.analysis import Severity


class _View(BaseModel):
    """Lists and nullable fields are required in the OpenAPI schema, so the client never
    has to guess whether a missing key means empty."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ProcessRef(_View):
    pid: int
    name: str | None


class ProcessSummary(_View):
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


class ProcessNode(ProcessSummary):
    children: list[ProcessNode]


class ProcessTree(_View):
    roots: list[ProcessNode]
    total: int


class LoadedModule(_View):
    name: str
    path: str | None
    base_address: str | None
    loaded_at: datetime


class ApiCount(_View):
    name: str
    count: int


class ProcessEventRow(_View):
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


class DnsRow(_View):
    event_id: str
    time: datetime
    query: str
    type: str | None
    answers: list[str]
    process: ProcessRef | None


class HttpRow(_View):
    event_id: str
    time: datetime
    method: str | None
    url: str
    host: str | None
    status: int | None
    user_agent: str | None
    process: ProcessRef | None


class TlsRow(_View):
    event_id: str
    time: datetime
    server_name: str | None
    ja3: str | None
    ja3s: str | None
    process: ProcessRef | None


class FlowRow(_View):
    event_id: str
    time: datetime
    transport: str | None
    source_ip: str | None
    source_port: int | None
    destination_ip: str | None
    destination_port: int | None
    process: ProcessRef | None


class NetworkAlertRow(_View):
    event_id: str
    time: datetime
    signature: str
    severity: Severity
    process: ProcessRef | None


class HostRow(_View):
    host: str
    kind: str
    count: int
    related: list[str]


class Listing[T](_View):
    """The first `items` of a list; `total` counts every row, so a capped list can say so."""

    items: list[T]
    total: int


class NetworkView(_View):
    dns: Listing[DnsRow]
    http: Listing[HttpRow]
    tls: Listing[TlsRow]
    flows: Listing[FlowRow]
    alerts: Listing[NetworkAlertRow]
    hosts: Listing[HostRow]
    simulated: bool


class RegistryChange(_View):
    event_id: str
    time: datetime
    action: str
    value_name: str | None
    data_type: str | None
    data: list[str]
    process: ProcessRef | None


class RegistryKeyGroup(_View):
    key: str
    hive: str | None
    changes: list[RegistryChange]


class RegistryView(_View):
    keys: list[RegistryKeyGroup]
    total: int
