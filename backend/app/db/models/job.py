from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now
from app.db.models.analysis import text_enum

LOG_TAIL_LIMIT = 4000


class JobType(StrEnum):
    GUEST_BUILD = "guest_build"
    INGEST = "ingest"
    REINGEST = "reingest"
    EXPORT_REPORT = "export_report"
    DELETE_ANALYSIS = "delete_analysis"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (CheckConstraint("progress BETWEEN 0 AND 100", name="progress_range"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), Identity(), primary_key=True
    )
    type: Mapped[JobType] = mapped_column(text_enum(JobType, "job_type"))
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        text_enum(JobStatus, "job_status"), default=JobStatus.PENDING
    )
    step: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    log: Mapped[str] = mapped_column(Text, default="")
    # SQLite has no JSONB; the variant only lets the unit tests build the table.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
