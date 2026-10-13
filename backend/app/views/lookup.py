from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.analysis_repository import get_analysis
from app.db.models import Analysis


async def require_analysis(session: AsyncSession, analysis_id: int) -> Analysis:
    analysis = await get_analysis(session, analysis_id)
    if analysis is None:
        raise HTTPException(404, f"Analysis {analysis_id} not found")
    return analysis
