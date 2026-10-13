from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    PROCESSING = "processing"
    INGESTING = "ingesting"
    DONE = "done"
    FAILED = "failed"
    REPORT_FAILED = "report_failed"
    CANCELLED = "cancelled"


class AnalysisPhase(StrEnum):
    LIVE = "live"
    FINAL = "final"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


ACTIVE_STATUSES = (
    AnalysisStatus.STARTING,
    AnalysisStatus.RUNNING,
    AnalysisStatus.PROCESSING,
    AnalysisStatus.INGESTING,
)


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


def text_enum(enum_class: type[StrEnum], constraint_name: str) -> Enum:
    # Text plus a CHECK constraint: a new state is a constraint change, not a native type change.
    return Enum(
        enum_class,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        values_callable=_enum_values,
    )


class Analysis(Base):
    __tablename__ = "analysis"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), Identity(), primary_key=True
    )
    sample_sha256: Mapped[str] = mapped_column(
        ForeignKey("sample.sha256", ondelete="RESTRICT"), index=True
    )
    filename: Mapped[str] = mapped_column(Text)
    cape_task_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[AnalysisStatus] = mapped_column(text_enum(AnalysisStatus, "analysis_status"))
    phase: Mapped[AnalysisPhase] = mapped_column(
        text_enum(AnalysisPhase, "analysis_phase"), default=AnalysisPhase.LIVE
    )
    # SQLite has no JSONB; the variants only let the unit tests build the tables.
    options: Mapped[dict[str, Any]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))
    score: Mapped[float | None] = mapped_column(Numeric(3, 1, asdecimal=False))
    max_severity: Mapped[Severity | None] = mapped_column(
        text_enum(Severity, "analysis_max_severity")
    )
    detected_families: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(Text()).with_variant(JSON(), "sqlite"), default=list
    )
    event_count: Mapped[int] = mapped_column(BigInteger, default=0)
    disk_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))
