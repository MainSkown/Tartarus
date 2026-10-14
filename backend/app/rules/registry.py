import asyncio
import contextlib
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from watchfiles import awatch

from app.db import rule_repository
from app.rules.loader import load_rules
from app.rules.rule import Rule, Validity

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_MS = 500
DEFAULT_RETRY_INTERVAL_S = 2.0


class RuleFileUnavailable(Exception):  # noqa: N818 - a lookup that found nothing, not a failure of ours
    """The rule is unknown, or its file is gone or not inside the rules directory."""


@dataclass(frozen=True)
class RuleState:
    """A loaded rule with the analyst's enabled flag."""

    rule: Rule
    enabled: bool

    @property
    def active(self) -> bool:
        return self.enabled and self.rule.validity is Validity.VALID


class RuleRegistry:
    """The loaded Sigma rules and which of them the analyst has switched on.

    The files under `root` are the source of truth for the rules; the `sigma_rule` table keeps
    the analyst's `enabled` flags across restarts. Public interface for the collector and the
    ingester: `active_rules()`, a snapshot they can hold for as long as they like.

    The registry reloads when a file under `root` changes (debounced) and on `reload()`. A rule
    file that is broken is a rule with a verdict, never a reason for the registry to stop; a
    reload that fails for another reason is logged and the previous rules stay in force.
    """

    def __init__(
        self,
        root: Path,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        retry_interval_s: float = DEFAULT_RETRY_INTERVAL_S,
    ) -> None:
        self._root = root
        self._session_factory = session_factory
        self._debounce_ms = debounce_ms
        self._retry_interval_s = retry_interval_s
        # Replaced whole, never mutated, so a reader never sees a half-applied reload.
        self._states: dict[str, RuleState] = {}
        self._lock = asyncio.Lock()
        self._stopping = asyncio.Event()
        self._watcher: asyncio.Task[None] | None = None

    def active_rules(self) -> list[Rule]:
        """Valid, enabled rules: the ones that may match events."""
        return [state.rule for state in self._states.values() if state.active]

    def states(self) -> list[RuleState]:
        return list(self._states.values())

    def state_of(self, rule_id: str) -> RuleState | None:
        return self._states.get(rule_id)

    async def reload(self) -> None:
        """Re-reads the rules directory and syncs the table; raises if that fails."""
        async with self._lock:
            rules = await asyncio.to_thread(load_rules, self._root)
            async with self._session_factory() as session:
                enabled = await rule_repository.sync_rules(session, rules)
            self._states = {rule.id: RuleState(rule, enabled[rule.id]) for rule in rules}

    async def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        """Stores the analyst's choice; False when no loaded rule has that id."""
        async with self._lock:
            state = self._states.get(rule_id)
            if state is None:
                return False
            async with self._session_factory() as session:
                if not await rule_repository.set_enabled(session, rule_id, enabled):
                    return False
            self._states = {**self._states, rule_id: replace(state, enabled=enabled)}
            return True

    async def rule_yaml(self, rule_id: str) -> str:
        """The text of the rule's file, read only if it lies inside the rules directory."""
        state = self._states.get(rule_id)
        if state is None:
            raise RuleFileUnavailable(f"Rule {rule_id} not found")
        return await asyncio.to_thread(self._read_inside_root, state.rule.path)

    async def start(self) -> None:
        """Loads once, then follows the directory until `stop()`."""
        await self._reload_and_log()
        self._stopping.clear()
        self._watcher = asyncio.create_task(self._watch(synced=self._root.is_dir()))

    async def stop(self) -> None:
        self._stopping.set()
        if self._watcher is not None:
            await self._watcher
            self._watcher = None

    def _read_inside_root(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self._root.resolve()):
            raise RuleFileUnavailable(f"Rule file {path} is outside the rules directory")
        try:
            return resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise RuleFileUnavailable(f"Rule file {path} cannot be read: {error}") from error

    async def _reload_and_log(self) -> None:
        try:
            await self.reload()
        except Exception:
            logger.exception("Reloading the Sigma rules from %s failed", self._root)

    async def _watch(self, *, synced: bool) -> None:
        """`synced`: the rules in memory already reflect a directory that is being watched."""
        while not self._stopping.is_set():
            if self._root.is_dir():
                if not synced:
                    # Files may have appeared between the last load and the watch starting.
                    await self._reload_and_log()
                synced = await self._follow_changes()
            else:
                synced = False
            await self._pause()

    async def _follow_changes(self) -> bool:
        """Reloads on every change until stopped; False if the watch broke and must be redone."""
        try:
            async for _ in awatch(
                self._root, debounce=self._debounce_ms, stop_event=self._stopping
            ):
                await self._reload_and_log()
        except Exception:
            logger.exception("Watching %s for rule changes failed", self._root)
            return False
        return True

    async def _pause(self) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), self._retry_interval_s)
