from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.models.analysis import Severity
from app.schemas.views_events import ProcessRef


class _Finding(BaseModel):
    """Lists and nullable fields are required in the OpenAPI schema, so the client never
    has to guess whether a missing key means empty."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class RelatedEvent(_Finding):
    id: str
    time: datetime
    lane: str
    action: str
    summary: str
    process: ProcessRef | None


class Detection(_Finding):
    id: str
    name: str
    description: str | None
    severity: Severity
    ruleset: str
    techniques: list[str]
    match: str | None
    references: list[str]
    time: datetime
    process: ProcessRef | None
    related_events: list[RelatedEvent]
    related_event_total: int


class DetectionGroup(_Finding):
    ruleset: str
    detections: list[Detection]


class DetectionsView(_Finding):
    groups: list[DetectionGroup]
    total: int


class AttackTechniqueHit(_Finding):
    id: str
    name: str | None
    hit_count: int
    severity: Severity
    detection_ids: list[str]


class AttackTactic(_Finding):
    id: str
    name: str
    techniques: list[AttackTechniqueHit]


class AttackMatrix(_Finding):
    tactics: list[AttackTactic]
    attack_version: str


class IocType(StrEnum):
    HASH = "hash"
    DOMAIN = "domain"
    IP = "ip"
    URL = "url"
    MUTEX = "mutex"
    REGISTRY = "registry"
    FILE = "file"


class Ioc(_Finding):
    type: IocType
    value: str
    count: int
    context: str
    source_event_ids: list[str]
    process: ProcessRef | None


class IocsView(_Finding):
    iocs: list[Ioc]
    truncated_types: list[IocType]


class Artifact(_Finding):
    id: str
    name: str
    size: int | None
    sha256: str | None
    md5: str | None
    type: str | None
    cape_type: str | None
    yara: list[str]
    source_process: ProcessRef | None
    guest_path: str | None
    downloadable: bool


class Screenshot(_Finding):
    n: int
    name: str
    size: int


class ExtractedConfig(_Finding):
    id: str
    family: str
    data: dict[str, Any]


class ArtifactsView(_Finding):
    dropped: list[Artifact]
    payloads: list[Artifact]
    procdumps: list[Artifact]
    memory_dump: Artifact | None
    pcap: Artifact | None
    screenshots: list[Screenshot]
    configs: list[ExtractedConfig]
