from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import rule_repository as repository
from app.db.base import Base
from app.rules.rule import Validity
from tests.rules.rule_factory import make_rule

FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rules.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db_session:
        yield db_session
    await engine.dispose()


async def test_a_synced_rule_is_stored_with_what_the_file_says_and_enabled(
    session: AsyncSession,
) -> None:
    await repository.sync_rules(session, [make_rule(FIRST, title="Whoami")])

    [stored] = await repository.list_rules(session)

    assert (stored.id, stored.title, stored.level, stored.status) == (
        FIRST,
        "Whoami",
        "high",
        "test",
    )
    assert stored.path == "/rules/sigma/custom/a.yml"
    assert stored.content_sha256 == "a" * 64
    assert (stored.validity, stored.error, stored.enabled) == (Validity.VALID, None, True)
    assert stored.loaded_at is not None


async def test_sync_returns_the_enabled_flag_of_every_rule(session: AsyncSession) -> None:
    await repository.sync_rules(session, [make_rule(FIRST)])
    await repository.set_enabled(session, FIRST, False)

    flags = await repository.sync_rules(session, [make_rule(FIRST), make_rule(SECOND)])

    assert flags == {FIRST: False, SECOND: True}


async def test_a_resynced_rule_takes_the_file_values_but_keeps_the_analysts_enabled_flag(
    session: AsyncSession,
) -> None:
    await repository.sync_rules(session, [make_rule(FIRST, title="Before")])
    await repository.set_enabled(session, FIRST, False)

    broken = make_rule(FIRST, title="After", validity=Validity.INVALID, error="bad", sha="b" * 64)
    await repository.sync_rules(session, [broken])
    [stored] = await repository.list_rules(session)

    assert (stored.title, stored.validity, stored.error) == ("After", Validity.INVALID, "bad")
    assert stored.content_sha256 == "b" * 64
    assert stored.enabled is False


async def test_an_unsupported_rule_is_told_apart_from_an_invalid_one(session: AsyncSession) -> None:
    unsupported = make_rule(FIRST, validity=Validity.UNSUPPORTED, error="no aggregations")
    await repository.sync_rules(
        session, [unsupported, make_rule(SECOND, validity=Validity.INVALID)]
    )

    stored = {rule.id: rule.validity for rule in await repository.list_rules(session)}

    assert stored == {FIRST: Validity.UNSUPPORTED, SECOND: Validity.INVALID}


async def test_a_rule_whose_file_is_gone_is_deleted(session: AsyncSession) -> None:
    await repository.sync_rules(session, [make_rule(FIRST), make_rule(SECOND)])

    await repository.sync_rules(session, [make_rule(SECOND)])

    assert [rule.id for rule in await repository.list_rules(session)] == [SECOND]


async def test_syncing_nothing_empties_the_table(session: AsyncSession) -> None:
    await repository.sync_rules(session, [make_rule(FIRST)])

    assert await repository.sync_rules(session, []) == {}
    assert await repository.list_rules(session) == []


async def test_set_enabled_says_whether_the_rule_exists(session: AsyncSession) -> None:
    await repository.sync_rules(session, [make_rule(FIRST)])

    assert await repository.set_enabled(session, FIRST, False) is True
    assert await repository.set_enabled(session, SECOND, False) is False
    [stored] = await repository.list_rules(session)
    assert stored.enabled is False
