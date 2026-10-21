from pathlib import Path
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.guest_choice import recorded_guest
from app.analyses.memory_disk import FreeSpaceProbe, StorageFreeSpace
from app.analyses.ports import RunnerControl
from app.cape.client import CapeClient
from app.config import Settings, get_settings
from app.db.analysis_repository import GUEST_NEEDING_STATUSES, get_analysis
from app.db.models import Analysis
from app.db.models.analysis import AnalysisKind, AnalysisStatus
from app.guest.client import GuestControl
from app.imports.upload import ImportSubmitter
from app.jobs.runner import JobRunner
from app.rules.registry import RuleRegistry
from app.samples.store import SampleStore
from app.search.index import EventIndex


def get_cape(request: Request) -> CapeClient:
    return cast(CapeClient, request.app.state.cape)


def get_guest_control(request: Request) -> GuestControl:
    return cast(GuestControl, request.app.state.guest_control)


def get_sample_store(request: Request) -> SampleStore:
    return cast(SampleStore, request.app.state.sample_store)


def get_runner(request: Request) -> RunnerControl:
    return cast(RunnerControl, request.app.state.runner)


def get_event_index(request: Request) -> EventIndex:
    return cast(EventIndex, request.app.state.event_index)


def get_job_runner(request: Request) -> JobRunner:
    return cast(JobRunner, request.app.state.job_runner)


def get_rule_registry(request: Request) -> RuleRegistry:
    return cast(RuleRegistry, request.app.state.rule_registry)


async def require_analysis(session: AsyncSession, analysis_id: int) -> Analysis:
    analysis = await get_analysis(session, analysis_id)
    if analysis is None:
        raise HTTPException(404, f"Analysis {analysis_id} not found")
    return analysis


async def analyses_needing_a_guest(session: AsyncSession) -> list[Analysis]:
    statement = (
        select(Analysis)
        .where(Analysis.status.in_(GUEST_NEEDING_STATUSES), Analysis.kind == AnalysisKind.RUN)
        .order_by(Analysis.id)
    )
    return list(await session.scalars(statement))


def _holders_of_the_guest(analyses: list[Analysis]) -> list[Analysis]:
    """The analyses using a guest now, or else the queued ones waiting for one."""
    using = [a for a in analyses if a.status in (AnalysisStatus.STARTING, AnalysisStatus.RUNNING)]
    return using or analyses


async def require_no_analysis_needing_a_guest(session: AsyncSession, outcome: str) -> None:
    """`409` while an analysis is queued, starting or running, naming the ones holding the guest.

    Registering, deleting or restoring a guest restarts or disturbs CAPE, and the control service
    cannot see the backend's queue, so the backend checks before asking it.
    """
    holders = _holders_of_the_guest(await analyses_needing_a_guest(session))
    if holders:
        named = ", ".join(
            f"analysis {a.id} on {recorded_guest(a.options) or 'an unknown guest'}" for a in holders
        )
        raise HTTPException(
            409,
            f"A guest cannot be {outcome} while an analysis is queued, starting or running: "
            f"{named}. Wait for it to finish or cancel it",
        )


def get_cape_storage_path(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.cape_storage_path


def get_free_space_probe(
    settings: Annotated[Settings, Depends(get_settings)],
) -> FreeSpaceProbe:
    return StorageFreeSpace(settings.cape_storage_path)


def get_exports_path(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.exports_path


def get_imports_dir(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.imports_dir


def get_import_submitter(
    settings: Annotated[Settings, Depends(get_settings)],
    runner: Annotated[RunnerControl, Depends(get_runner)],
) -> ImportSubmitter:
    return ImportSubmitter.from_settings(settings, runner)
