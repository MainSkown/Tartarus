import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.rules import registry as registry_module
from app.rules.registry import RuleFileUnavailable, RuleRegistry
from app.rules.rule import Rule, Validity
from tests.rules.support import rule_yaml, simple_detection

SELECTION = simple_detection("Image|endswith: '\\cmd.exe'")
FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
DEADLINE_S = 15.0

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def factory(tmp_path: Path) -> AsyncIterator[Factory]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registry.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "sigma"


@pytest.fixture
def existing_root(root: Path) -> Path:
    root.mkdir()
    return root


def write_rule(root: Path, name: str, rule_id: str, **options: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rule_yaml(SELECTION, rule_id=rule_id, **options), encoding="utf-8")
    return path


def new_registry(root: Path, factory: Factory) -> RuleRegistry:
    return RuleRegistry(root, factory, debounce_ms=50, retry_interval_s=0.05)


async def eventually(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(DEADLINE_S):
        while not condition():  # noqa: ASYNC110 - polling a plain predicate
            await asyncio.sleep(0.02)


def touch(path: Path) -> None:
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


async def rewrite_until(path: Path, condition: Callable[[], bool]) -> None:
    """Writes the file again until `condition` holds: a write made before the watcher is armed
    raises no event, and nothing tells the test when it is."""
    async with asyncio.timeout(DEADLINE_S):
        while not condition():
            touch(path)
            await asyncio.sleep(0.05)


def active_ids(registry: RuleRegistry) -> set[str]:
    return {rule.id for rule in registry.active_rules()}


def title_of(registry: RuleRegistry, rule_id: str) -> str | None:
    state = registry.state_of(rule_id)
    return None if state is None else state.rule.title


async def test_a_missing_rules_directory_is_an_empty_registry_not_an_error(
    root: Path, factory: Factory
) -> None:
    registry = new_registry(root, factory)

    await registry.start()
    await registry.stop()

    assert registry.states() == []
    assert registry.active_rules() == []


async def test_reload_loads_the_rules_and_lists_every_one_with_its_verdict(
    root: Path, factory: Factory
) -> None:
    write_rule(root, "custom/good.yml", FIRST)
    (root / "custom" / "broken.yml").write_text("title: [unclosed", encoding="utf-8")
    write_rule(root, "custom/wmi.yml", SECOND, category="wmi_event")
    registry = new_registry(root, factory)

    await registry.reload()

    verdicts = {state.rule.id: state.rule.validity for state in registry.states()}
    assert verdicts[FIRST] is Validity.VALID
    assert verdicts[SECOND] is Validity.UNSUPPORTED
    assert Validity.INVALID in verdicts.values()
    assert active_ids(registry) == {FIRST}


async def test_a_disabled_rule_is_not_active_but_stays_listed(root: Path, factory: Factory) -> None:
    write_rule(root, "a.yml", FIRST)
    write_rule(root, "b.yml", SECOND)
    registry = new_registry(root, factory)
    await registry.reload()

    assert await registry.set_enabled(FIRST, False) is True

    assert active_ids(registry) == {SECOND}
    state = registry.state_of(FIRST)
    assert state is not None
    assert state.enabled is False


async def test_enabling_an_unknown_rule_reports_that_it_is_unknown(
    root: Path, factory: Factory
) -> None:
    registry = new_registry(root, factory)
    await registry.reload()

    assert await registry.set_enabled(FIRST, False) is False


async def test_the_toggle_survives_a_reload_and_a_restart(root: Path, factory: Factory) -> None:
    write_rule(root, "a.yml", FIRST)
    registry = new_registry(root, factory)
    await registry.start()
    await registry.set_enabled(FIRST, False)
    await registry.reload()
    assert active_ids(registry) == set()
    await registry.stop()

    restarted = new_registry(root, factory)
    await restarted.start()

    assert active_ids(restarted) == set()
    state = restarted.state_of(FIRST)
    assert state is not None
    assert state.enabled is False
    await restarted.stop()


async def test_a_snapshot_taken_before_a_reload_does_not_change(
    root: Path, factory: Factory
) -> None:
    write_rule(root, "a.yml", FIRST)
    registry = new_registry(root, factory)
    await registry.reload()
    before = registry.active_rules()

    (root / "a.yml").unlink()
    await registry.reload()

    assert [rule.id for rule in before] == [FIRST]
    assert registry.active_rules() == []


@pytest.mark.usefixtures("existing_root")
async def test_a_rule_file_appearing_changing_breaking_and_disappearing_is_followed(
    root: Path, factory: Factory
) -> None:
    registry = new_registry(root, factory)
    await registry.start()
    try:
        path = write_rule(root, "custom/live.yml", FIRST, title="First title")
        await rewrite_until(path, lambda: active_ids(registry) == {FIRST})

        write_rule(root, "custom/live.yml", FIRST, title="Second title")
        await eventually(lambda: title_of(registry, FIRST) == "Second title")

        path.write_text("title: [unclosed", encoding="utf-8")
        await eventually(lambda: active_ids(registry) == set())
        assert any(s.rule.validity is Validity.INVALID for s in registry.states())

        path.unlink()
        await eventually(lambda: registry.states() == [])
    finally:
        await registry.stop()


async def test_the_watcher_waits_for_a_rules_directory_that_does_not_exist_yet(
    root: Path, factory: Factory
) -> None:
    registry = new_registry(root, factory)
    await registry.start()
    try:
        path = write_rule(root, "late.yml", FIRST)
        await rewrite_until(path, lambda: active_ids(registry) == {FIRST})
    finally:
        await registry.stop()


@pytest.mark.usefixtures("existing_root")
async def test_a_failed_reload_is_logged_and_the_watcher_keeps_going(
    root: Path,
    factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    real_load = registry_module.load_rules
    calls = iter(range(100))

    def flaky_load(path: Path) -> list[Rule]:
        if next(calls) == 1:  # the first reload after the initial load
            raise OSError("disk went away")
        return real_load(path)

    monkeypatch.setattr(registry_module, "load_rules", flaky_load)
    registry = new_registry(root, factory)
    caplog.set_level(logging.ERROR)
    await registry.start()
    try:
        first = write_rule(root, "a.yml", FIRST)
        await rewrite_until(first, lambda: "disk went away" in caplog.text)
        write_rule(root, "b.yml", SECOND)
        await eventually(lambda: active_ids(registry) == {FIRST, SECOND})
    finally:
        await registry.stop()


async def test_the_yaml_of_a_rule_is_read_from_its_file(root: Path, factory: Factory) -> None:
    path = write_rule(root, "a.yml", FIRST)
    registry = new_registry(root, factory)
    await registry.reload()

    assert await registry.rule_yaml(FIRST) == path.read_text(encoding="utf-8")


async def test_the_yaml_of_an_unknown_rule_is_unavailable(root: Path, factory: Factory) -> None:
    registry = new_registry(root, factory)
    await registry.reload()

    with pytest.raises(RuleFileUnavailable):
        await registry.rule_yaml(FIRST)


@pytest.mark.usefixtures("existing_root")
async def test_a_rule_file_that_links_outside_the_root_is_not_served(
    root: Path, factory: Factory, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.yml"
    secret.write_text(rule_yaml(SELECTION, rule_id=FIRST), encoding="utf-8")
    (root / "link.yml").symlink_to(secret)
    registry = new_registry(root, factory)
    await registry.reload()
    assert registry.state_of(FIRST) is not None

    with pytest.raises(RuleFileUnavailable):
        await registry.rule_yaml(FIRST)


async def test_a_rule_file_deleted_since_the_last_reload_is_unavailable(
    root: Path, factory: Factory
) -> None:
    path = write_rule(root, "a.yml", FIRST)
    registry = new_registry(root, factory)
    await registry.reload()

    path.unlink()

    with pytest.raises(RuleFileUnavailable):
        await registry.rule_yaml(FIRST)
