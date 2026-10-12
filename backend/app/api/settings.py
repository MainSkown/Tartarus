from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.settings_repository import read_settings, replace_settings
from app.schemas.settings import SettingsBody

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def read(session: Annotated[AsyncSession, Depends(get_session)]) -> SettingsBody:
    """Stored settings. A key that was never stored reports its default; nothing is written."""
    return await read_settings(session)


@router.put("")
async def replace(
    body: SettingsBody, session: Annotated[AsyncSession, Depends(get_session)]
) -> SettingsBody:
    """Replaces every setting in one transaction."""
    await replace_settings(session, body)
    return body
