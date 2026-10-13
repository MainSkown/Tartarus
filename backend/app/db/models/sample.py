from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class Sample(Base):
    __tablename__ = "sample"

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    sha1: Mapped[str] = mapped_column(Text)
    md5: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    file_type: Mapped[str | None] = mapped_column(Text)
    original_name: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[str] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
