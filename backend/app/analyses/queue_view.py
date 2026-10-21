from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.analysis_repository import get_active_analyses, get_queued_analyses, queue_positions
from app.db.models import Analysis
from app.live.utc import as_utc
from app.schemas.system import QueuedAnalysis, QueueSnapshot, RunningAnalysis


async def queue_snapshot(session: AsyncSession, now: datetime) -> QueueSnapshot:
    running = await get_active_analyses(session)
    queued = await get_queued_analyses(session)
    positions = await queue_positions(session, [analysis.id for analysis in queued])
    return QueueSnapshot(
        running=[_running(analysis, now) for analysis in running],
        queued_count=len(queued),
        queued=[
            QueuedAnalysis(
                id=analysis.id,
                filename=analysis.filename,
                guest=_guest_of(analysis),
                position=positions[analysis.id],
            )
            for analysis in queued
        ],
    )


def _running(analysis: Analysis, now: datetime) -> RunningAnalysis:
    started_at = as_utc(analysis.started_at) if analysis.started_at is not None else None
    return RunningAnalysis(
        id=analysis.id,
        filename=analysis.filename,
        guest=_guest_of(analysis),
        status=analysis.status,
        started_at=started_at,
        elapsed_s=None if started_at is None else int((now - started_at).total_seconds()),
    )


def _guest_of(analysis: Analysis) -> str | None:
    guest = analysis.options.get("guest")
    return guest if isinstance(guest, str) else None
