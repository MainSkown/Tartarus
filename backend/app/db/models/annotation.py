from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now
from app.db.models.analysis import text_enum

# Identity primary keys are bigint on Postgres; SQLite only autoincrements a plain INTEGER key.
_ID = BigInteger().with_variant(Integer(), "sqlite")


class TargetType(StrEnum):
    ANALYSIS = "analysis"
    PROCESS = "process"
    EVENT = "event"


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(_ID, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TagLink(Base):
    __tablename__ = "tag_link"
    __table_args__ = (UniqueConstraint("tag_id", "analysis_id", "target_type", "target_ref"),)

    id: Mapped[int] = mapped_column(_ID, Identity(), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[TargetType] = mapped_column(text_enum(TargetType, "annotation_target_type"))
    # "" for the analysis, the pid for a process, the event.id for an event.
    target_ref: Mapped[str] = mapped_column(Text, default="")


class Note(Base):
    __tablename__ = "note"

    id: Mapped[int] = mapped_column(_ID, Identity(), primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analysis.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[TargetType] = mapped_column(text_enum(TargetType, "annotation_target_type"))
    target_ref: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
