from datetime import datetime
from enum import StrEnum
from typing import Any

from app.db.models.analysis import Severity
from app.schemas.base import ApiModel
from app.schemas.views_events import ProcessRef


class RelatedEvent(ApiModel):
    id: str
    time: datetime
    lane: str
    action: str
    summary: str
    process: ProcessRef | None


class Detection(ApiModel):
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


class DetectionGroup(ApiModel):
    ruleset: str
    detections: list[Detection]


class DetectionsView(ApiModel):
    groups: list[DetectionGroup]
    total: int


class AttackTechniqueHit(ApiModel):
    id: str
    name: str | None
    hit_count: int
    severity: Severity
    detection_ids: list[str]


class AttackTactic(ApiModel):
    id: str
    name: str
    techniques: list[AttackTechniqueHit]


class AttackMatrix(ApiModel):
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


class Ioc(ApiModel):
    type: IocType
    value: str
    count: int
    context: str
    source_event_ids: list[str]
    process: ProcessRef | None


class IocsView(ApiModel):
    iocs: list[Ioc]
    truncated_types: list[IocType]


class Artifact(ApiModel):
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


class Screenshot(ApiModel):
    n: int
    name: str
    size: int


class ExtractedConfig(ApiModel):
    id: str
    family: str
    data: dict[str, Any]


class ArtifactsView(ApiModel):
    dropped: list[Artifact]
    payloads: list[Artifact]
    procdumps: list[Artifact]
    memory_dump: Artifact | None
    pcap: Artifact | None
    screenshots: list[Screenshot]
    configs: list[ExtractedConfig]
