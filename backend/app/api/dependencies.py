from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.ports import RunnerControl
from app.cape.client import CapeClient
from app.db.analysis_repository import get_analysis
from app.db.models import Analysis
from app.samples.store import SampleStore
from app.search.index import EventIndex


def get_cape(request: Request) -> CapeClient:
    return cast(CapeClient, request.app.state.cape)


def get_sample_store(request: Request) -> SampleStore:
    return cast(SampleStore, request.app.state.sample_store)


def get_runner(request: Request) -> RunnerControl:
    return cast(RunnerControl, request.app.state.runner)


def get_event_index(request: Request) -> EventIndex:
    return cast(EventIndex, request.app.state.event_index)


async def require_analysis(session: AsyncSession, analysis_id: int) -> Analysis:
    analysis = await get_analysis(session, analysis_id)
    if analysis is None:
        raise HTTPException(404, f"Analysis {analysis_id} not found")
    return analysis
