from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.analysis_repository import get_analysis
from app.db.models import Analysis
from app.db.models.analysis import ACTIVE_STATUSES, AnalysisStatus
from app.live.messages import StatusData
from app.live.utc import as_utc

_UNFINISHED = (AnalysisStatus.QUEUED, *ACTIVE_STATUSES)


def is_finished(status: AnalysisStatus) -> bool:
    return status not in _UNFINISHED


class ProgressSource(Protocol):
    async def read(self, analysis_id: int) -> StatusData | None:
        """Where the analysis stands now; `None` when there is no such analysis."""


class DbProgressSource:
    """Reads an analysis's status and clock from the database, one fresh session per read."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def read(self, analysis_id: int) -> StatusData | None:
        async with self._session_factory() as session:
            analysis = await get_analysis(session, analysis_id)
        if analysis is None:
            return None
        elapsed_s = self._elapsed_s(analysis)
        return StatusData(
            status=analysis.status,
            phase=analysis.phase,
            elapsed_s=elapsed_s,
            remaining_s=_remaining_s(analysis, elapsed_s),
        )

    def _elapsed_s(self, analysis: Analysis) -> float | None:
        if analysis.started_at is None:
            return None
        end = as_utc(analysis.finished_at) if analysis.finished_at else self._clock()
        return max(0.0, (end - as_utc(analysis.started_at)).total_seconds())


def _remaining_s(analysis: Analysis, elapsed_s: float | None) -> float | None:
    if elapsed_s is None:
        return None
    if is_finished(analysis.status):
        return 0.0
    return max(0.0, float(analysis.options["timeout"]) - elapsed_s)
