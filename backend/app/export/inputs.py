from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.schemas.views_findings import Ioc, IocType

TLP_PREFIX = "tlp:"


class TargetType(StrEnum):
    ANALYSIS = "analysis"
    PROCESS = "process"
    EVENT = "event"


@dataclass(frozen=True)
class ExportNote:
    body: str
    target_type: TargetType
    target_ref: str | None

    @property
    def label(self) -> str:
        about = (
            "the analysis" if self.target_ref is None else f"{self.target_type} {self.target_ref}"
        )
        return f"Analyst note on {about}"


@dataclass(frozen=True)
class ExportAnnotations:
    """The analyst's tags on the analysis and every note, as the exporters need them."""

    tags: tuple[str, ...] = ()
    notes: tuple[ExportNote, ...] = ()

    @property
    def tlp_tag(self) -> str | None:
        return min((tag for tag in self.tags if tag.startswith(TLP_PREFIX)), default=None)


@dataclass(frozen=True)
class ExportSample:
    filename: str
    sha256: str
    md5: str | None = None
    sha1: str | None = None


@dataclass(frozen=True)
class ExportTechnique:
    """`name` is None for an id the bundled ATT&CK table does not know."""

    id: str
    name: str | None


@dataclass(frozen=True)
class IocExportInput:
    """Everything the three IOC exporters read; they query nothing else."""

    analysis_id: int
    sample: ExportSample
    observed_at: datetime
    iocs: tuple[Ioc, ...]
    families: tuple[str, ...] = ()
    techniques: tuple[ExportTechnique, ...] = ()
    annotations: ExportAnnotations = field(default_factory=ExportAnnotations)

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at needs a timezone: exports are in UTC")

    @property
    def distinct_iocs(self) -> tuple[Ioc, ...]:
        first_of_each: dict[tuple[IocType, str], Ioc] = {}
        for ioc in self.iocs:
            first_of_each.setdefault((ioc.type, ioc.value.casefold()), ioc)
        return tuple(first_of_each.values())
