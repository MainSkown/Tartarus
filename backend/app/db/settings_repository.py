from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting
from app.schemas.settings import SettingsBody

DEFAULTS = SettingsBody().model_dump()


async def read_settings(session: AsyncSession) -> SettingsBody:
    rows = await session.scalars(select(Setting).where(Setting.key.in_(DEFAULTS)))
    stored = {row.key: row.value for row in rows}
    return SettingsBody.model_validate({**DEFAULTS, **stored})


async def replace_settings(session: AsyncSession, body: SettingsBody) -> None:
    for key, value in body.model_dump().items():
        await session.merge(Setting(key=key, value=value))
    await session.commit()
