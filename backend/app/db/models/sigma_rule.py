from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now
from app.db.models.analysis import text_enum
from app.rules.rule import Validity


class SigmaRule(Base):
    """A loaded rule file. The file owns every column but `enabled`, which the analyst owns."""

    __tablename__ = "sigma_rule"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Three states, so a boolean `valid` cannot say "valid Sigma this engine cannot run".
    validity: Mapped[Validity] = mapped_column(text_enum(Validity, "sigma_rule_validity"))
    error: Mapped[str | None] = mapped_column(Text)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
