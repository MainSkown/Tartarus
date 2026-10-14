from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.db.models import SigmaRule
from app.rules.rule import Rule


async def sync_rules(session: AsyncSession, rules: Iterable[Rule]) -> dict[str, bool]:
    """Makes the table mirror `rules`: the files win everything but `enabled`.

    A new rule starts enabled and a known one keeps its flag; a row whose rule is no longer
    loaded is deleted. Returns `enabled` by rule id for every rule given.
    """
    loaded = {rule.id: rule for rule in rules}
    stored = {row.id: row for row in await session.scalars(select(SigmaRule))}
    now = utc_now()
    for rule_id, rule in loaded.items():
        row = stored.get(rule_id)
        if row is None:
            row = stored[rule_id] = SigmaRule(id=rule_id, enabled=True)
            session.add(row)
        _copy_file_fields(row, rule)
        row.loaded_at = now
    for rule_id in stored.keys() - loaded.keys():
        await session.delete(stored[rule_id])
    await session.commit()
    return {rule_id: stored[rule_id].enabled for rule_id in loaded}


async def list_rules(session: AsyncSession) -> list[SigmaRule]:
    rows = await session.scalars(select(SigmaRule).order_by(SigmaRule.title, SigmaRule.id))
    return list(rows)


async def set_enabled(session: AsyncSession, rule_id: str, enabled: bool) -> bool:
    """Stores the analyst's choice; False when no such rule is stored."""
    row = await session.get(SigmaRule, rule_id)
    if row is None:
        return False
    row.enabled = enabled
    await session.commit()
    return True


def _copy_file_fields(row: SigmaRule, rule: Rule) -> None:
    row.title = rule.title
    row.level = rule.level
    row.status = rule.status
    row.path = str(rule.path)
    row.content_sha256 = rule.content_sha256
    row.validity = rule.validity
    row.error = rule.error
