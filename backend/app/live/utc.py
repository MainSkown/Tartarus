from datetime import UTC, datetime


def as_utc(moment: datetime) -> datetime:
    """The database hands back naive datetimes on SQLite; they are UTC like the rest."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
