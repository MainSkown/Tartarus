from typing import Any

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Setting(Base):
    __tablename__ = "setting"

    # SQLite has no JSONB; the variant only lets the unit tests build the table.
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
