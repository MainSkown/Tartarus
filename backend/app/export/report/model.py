"""Everything a report says, as plain typed data: the renderers draw it and read nothing else."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models.analysis import AnalysisStatus, Severity
from app.export.inputs import TargetType
from app.export.report.key_events import EventFacts, KeyEvents
from app.export.report.process_tree_svg import TreeRow
from app.schemas.views_events import DnsRow, FlowRow, HostRow, HttpRow, Listing, ProcessRef
from app.schemas.views_findings import Ioc, IocType


class ReportModelBase(BaseModel):
    model_config = ConfigDict(frozen=True)


class ReportInclude(ReportModelBase):
    """The sections the analyst may leave out. Tags stay either way: they are the header's
    metadata, and a `tlp:*` tag says how the report may be shared.
    """

    notes: bool = True
    screenshots: bool = True
    raw_iocs: bool = True


class ReportHeader(ReportModelBase):
    analysis_id: int
    sample_name: str
    sample_type: str | None
    sha256: str
    md5: str | None
    sha1: str | None
    status: AnalysisStatus
    route: str | None
    guest: str | None
    submitted_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_s: int | None
    generated_at: datetime


class ReportCounts(ReportModelBase):
    events: int
    processes: int
    detections: int
    files_written: int
    registry_keys_written: int
    dns_queries: int
    hosts: int
    tcp_flows: int


class ReportTechnique(ReportModelBase):
    """One technique under one tactic; `name` is None for an id the ATT&CK table does not know."""

    id: str
    name: str | None
    tactic: str
    severity: Severity
    hit_count: int
    signatures: tuple[str, ...]


class ReportDetection(ReportModelBase):
    id: str
    name: str
    description: str | None
    severity: Severity
    ruleset: str
    techniques: tuple[str, ...]
    match: str | None
    references: tuple[str, ...]
    author: str | None
    time: datetime
    process: ProcessRef | None
    cited_events: tuple[EventFacts, ...]
    more_events: int


class ReportDetectionGroup(ReportModelBase):
    ruleset: str
    detections: tuple[ReportDetection, ...]


class NetworkSection(ReportModelBase):
    dns: Listing[DnsRow]
    http: Listing[HttpRow]
    hosts: Listing[HostRow]
    flows: Listing[FlowRow]
    simulated: bool


class IocGroup(ReportModelBase):
    """The indicators of one type: `shown` of the `total`, `more` not listed. `truncated` is
    true when the IOCs view itself stopped at its own limit for this type.
    """

    type: IocType
    total: int
    shown: tuple[Ioc, ...]
    more: int
    truncated: bool


class ReportScreenshot(ReportModelBase):
    n: int
    data_uri: str


class NoteGroup(ReportModelBase):
    """The analyst's notes on one target, oldest first. `detail` is the event id of an event."""

    target_type: TargetType
    title: str
    detail: str | None
    notes: tuple[str, ...]


class ReportModel(ReportModelBase):
    header: ReportHeader
    score: float | None
    max_severity: Severity | None
    families: tuple[str, ...]
    tags: tuple[str, ...]
    counts: ReportCounts
    techniques: tuple[ReportTechnique, ...]
    process_tree: tuple[TreeRow, ...]
    key_events: KeyEvents
    detections: tuple[ReportDetectionGroup, ...]
    network: NetworkSection
    iocs: tuple[IocGroup, ...]
    screenshots: tuple[ReportScreenshot, ...]
    notes: tuple[NoteGroup, ...]
    include: ReportInclude
