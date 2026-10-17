from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict, Unpack

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import annotation_repository
from app.db.base import utc_now
from app.db.models import Analysis, Sample, Tag, TagLink
from app.db.models.analysis import ACTIVE_STATUSES, AnalysisPhase, AnalysisStatus, Severity
from app.db.models.annotation import TargetType

# The one definition of "who goes next", shared by the runner and the position shown to users.
_QUEUE_ORDER = (Analysis.submitted_at, Analysis.id)

REINGESTABLE_STATUSES = (AnalysisStatus.DONE, AnalysisStatus.REPORT_FAILED)
# From submission until the guest has stopped; registering or deleting a guest restarts CAPE,
# which fails a task in any of these states (M6 plan, decision 7).
GUEST_NEEDING_STATUSES = (
    AnalysisStatus.QUEUED,
    AnalysisStatus.STARTING,
    AnalysisStatus.RUNNING,
)


class AnalysisChanges(TypedDict, total=False):
    status: AnalysisStatus
    phase: AnalysisPhase
    cape_task_id: int | None
    started_at: datetime | None
    finished_at: datetime | None
    deadline_at: datetime | None
    error: str | None
    summary: dict[str, Any] | None
    score: float | None
    max_severity: Severity | None
    detected_families: list[str]
    event_count: int
    disk_bytes: int


async def get_sample(session: AsyncSession, sha256: str) -> Sample | None:
    return await session.get(Sample, sha256)


async def add_sample_if_new(session: AsyncSession, sample: Sample) -> Sample:
    existing = await session.get(Sample, sample.sha256)
    if existing is not None:
        return existing
    session.add(sample)
    await session.commit()
    return sample


async def create_analysis(
    session: AsyncSession,
    *,
    sample_sha256: str,
    filename: str,
    options: dict[str, Any],
) -> Analysis:
    analysis = Analysis(
        sample_sha256=sample_sha256,
        filename=filename,
        status=AnalysisStatus.QUEUED,
        options=options,
    )
    session.add(analysis)
    await session.commit()
    return analysis


async def get_analysis(session: AsyncSession, analysis_id: int) -> Analysis | None:
    return await session.get(Analysis, analysis_id)


@dataclass(frozen=True, slots=True)
class AnalysisFilter:
    q: str | None = None
    status: AnalysisStatus | None = None
    tag: str | None = None


def _matching(filters: AnalysisFilter | None) -> list[ColumnElement[bool]]:
    criteria: list[ColumnElement[bool]] = []
    if filters is None:
        return criteria
    if filters.q:
        criteria.append(
            Analysis.filename.icontains(filters.q, autoescape=True)
            | Analysis.sample_sha256.icontains(filters.q, autoescape=True)
        )
    if filters.status is not None:
        criteria.append(Analysis.status == filters.status)
    if filters.tag:
        criteria.append(_tagged(filters.tag))
    return criteria


def _tagged(tag_name: str) -> ColumnElement[bool]:
    tagged_analyses = (
        select(TagLink.analysis_id)
        .join(Tag, Tag.id == TagLink.tag_id)
        .where(Tag.name == tag_name.lower(), TagLink.target_type == TargetType.ANALYSIS)
    )
    return Analysis.id.in_(tagged_analyses)


async def list_analyses(
    session: AsyncSession,
    filters: AnalysisFilter | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Analysis]:
    """Newest first."""
    statement = (
        select(Analysis)
        .where(*_matching(filters))
        .order_by(Analysis.submitted_at.desc(), Analysis.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(statement)).all())


async def count_analyses(session: AsyncSession, filters: AnalysisFilter | None = None) -> int:
    statement = select(func.count()).select_from(Analysis).where(*_matching(filters))
    return int(await session.scalar(statement) or 0)


async def update_analysis(
    session: AsyncSession, analysis_id: int, **changes: Unpack[AnalysisChanges]
) -> Analysis | None:
    unknown = changes.keys() - AnalysisChanges.__annotations__.keys()
    if unknown:
        raise TypeError(f"not an analysis field: {', '.join(sorted(unknown))}")
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        return None
    for field, value in changes.items():
        setattr(analysis, field, value)
    await session.commit()
    return analysis


async def delete_analysis(session: AsyncSession, analysis_id: int) -> bool:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None:
        return False
    await session.delete(analysis)
    await session.commit()
    await annotation_repository.delete_unused_tags(session)
    return True


async def delete_sample_if_unreferenced(session: AsyncSession, sha256: str) -> bool:
    referenced = await session.scalar(
        select(Analysis.id).where(Analysis.sample_sha256 == sha256).limit(1)
    )
    sample = await session.get(Sample, sha256)
    if referenced is not None or sample is None:
        return False
    await session.delete(sample)
    await session.commit()
    return True


async def get_active_analysis(session: AsyncSession) -> Analysis | None:
    statement = (
        select(Analysis)
        .where(Analysis.status.in_(ACTIVE_STATUSES))
        .order_by(Analysis.submitted_at, Analysis.id)
        .limit(1)
    )
    return await session.scalar(statement)


async def has_analysis_needing_a_guest(session: AsyncSession) -> bool:
    statement = select(Analysis.id).where(Analysis.status.in_(GUEST_NEEDING_STATUSES)).limit(1)
    return await session.scalar(statement) is not None


async def get_oldest_queued_analysis(session: AsyncSession) -> Analysis | None:
    statement = (
        select(Analysis)
        .where(Analysis.status == AnalysisStatus.QUEUED)
        .order_by(*_QUEUE_ORDER)
        .limit(1)
    )
    return await session.scalar(statement)


async def queue_positions(session: AsyncSession, analysis_ids: Collection[int]) -> dict[int, int]:
    """Maps each queued analysis among `analysis_ids` to its place in line (1 is served next)."""
    if not analysis_ids:
        return {}
    numbered = (
        select(Analysis.id, func.row_number().over(order_by=_QUEUE_ORDER).label("position"))
        .where(Analysis.status == AnalysisStatus.QUEUED)
        .subquery()
    )
    statement = select(numbered.c.id, numbered.c.position).where(numbered.c.id.in_(analysis_ids))
    return {row.id: row.position for row in await session.execute(statement)}


async def _transition_if_queued(session: AsyncSession, analysis_id: int, **changes: Any) -> bool:
    # One UPDATE with the status in its WHERE clause: whoever gets here first wins, so a cancel
    # and a claim made at the same moment cannot both succeed. Callers hold no stale copy that
    # matters (they re-read after), so the session's cached objects are not synchronised.
    statement = (
        update(Analysis)
        .where(Analysis.id == analysis_id, Analysis.status == AnalysisStatus.QUEUED)
        .values(**changes)
        .returning(Analysis.id)
        .execution_options(synchronize_session=False)
    )
    changed = await session.scalar(statement)
    await session.commit()
    return changed is not None


async def claim_queued(session: AsyncSession, analysis_id: int) -> bool:
    """Moves a queued analysis to `starting`; False if it is no longer queued."""
    return await _transition_if_queued(session, analysis_id, status=AnalysisStatus.STARTING)


async def cancel_if_queued(session: AsyncSession, analysis_id: int) -> bool:
    """Ends a queued analysis as `cancelled`; False if it has already started or ended."""
    return await _transition_if_queued(
        session, analysis_id, status=AnalysisStatus.CANCELLED, finished_at=utc_now()
    )


async def begin_reingest(session: AsyncSession, analysis_id: int) -> bool:
    """Puts a `done` or `report_failed` analysis back to `ingesting`; False if it may not.

    One UPDATE checks both the analysis's state and that nothing else is active, because the
    runner follows one analysis at a time and two callers must not both get past a separate check.
    """
    another_is_active = select(Analysis.id).where(Analysis.status.in_(ACTIVE_STATUSES)).exists()
    statement = (
        update(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.status.in_(REINGESTABLE_STATUSES),
            ~another_is_active,
        )
        .values(status=AnalysisStatus.INGESTING, error=None, finished_at=None)
        .returning(Analysis.id)
        .execution_options(synchronize_session=False)
    )
    changed = await session.scalar(statement)
    await session.commit()
    return changed is not None
