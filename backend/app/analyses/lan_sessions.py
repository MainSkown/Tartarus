"""The fake local network of an analysis: a session of the control service, opened before the
sample is submitted and closed whenever the analysis ends.

Opening fails closed (the analysis does not run "half simulated"); closing is best effort and
never turns a good analysis into a failed one, so a close that fails is retried by `reconcile`.
"""

import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from app.db.models import Analysis
from app.db.models.analysis import ACTIVE_STATUSES
from app.guest.errors import GuestControlError, GuestControlRejected
from app.guest.lan_schemas import LanPreset
from app.ingest.protocol import LanHost

logger = logging.getLogger(__name__)

KEY_PREFIX = "analysis-"
_OUR_KEY = re.compile(rf"{KEY_PREFIX}([1-9][0-9]*)")


class LanControl(Protocol):
    """The fake-LAN session routes of the guest control service."""

    async def lan_presets(self) -> list[LanPreset]: ...

    async def lan_sessions(self) -> list[str]: ...

    async def open_lan_session(self, key: str, guest: str, preset: str) -> None: ...

    async def close_lan_session(self, key: str, task_id: int | None = None) -> bool: ...


class LanStartError(Exception):
    """The fake local network could not start; the message says why. The analysis is not run."""


def session_key(analysis_id: int) -> str:
    return f"{KEY_PREFIX}{analysis_id}"


def analysis_id_of(key: str) -> int | None:
    """The analysis a session key names; None for a key that is not one of ours."""
    matched = _OUR_KEY.fullmatch(key)
    return None if matched is None else int(matched.group(1))


def lan_preset_of(analysis: Analysis) -> str | None:
    preset = analysis.options.get("lan_preset")
    return preset if isinstance(preset, str) else None


class LanSessions:
    def __init__(self, control: LanControl) -> None:
        self._control = control
        # Analyses whose session is closed already, so ending them has nothing left to close.
        self._closed: set[int] = set()
        # The first listing after a start finds what a previous backend left; a later one is only
        # needed while a session of an active analysis is open or after a close failed, so an
        # installation that never uses the feature asks once.
        self._listing_due = True

    async def open(self, analysis: Analysis, guest: str) -> None:
        """Opens the analysis's session when it asked for a preset; raises `LanStartError`."""
        preset = lan_preset_of(analysis)
        if preset is None:
            return
        self._closed.discard(analysis.id)
        try:
            await self._control.open_lan_session(session_key(analysis.id), guest, preset)
        except GuestControlRejected as refused:
            self._closed.add(analysis.id)
            raise LanStartError(_start_failure(refused.message)) from None
        except GuestControlError as error:
            await self.close(analysis, task_id=None)
            raise LanStartError(_start_failure(str(error))) from None

    async def hosts_of(self, analysis: Analysis) -> tuple[Mapping[str, LanHost], list[str]]:
        """The fake hosts the analysis's preset has, by address, for the ingest to flag them; and
        the warnings for the analyst. A preset that cannot be looked up gives no hosts and a
        warning: the run is still ingested, only without the fake-LAN flags and events.
        """
        preset_id = lan_preset_of(analysis)
        if preset_id is None:
            return {}, []
        try:
            presets = await self._control.lan_presets()
        except GuestControlError as error:
            logger.warning(
                "The fake-LAN presets could not be read for analysis %s: %s", analysis.id, error
            )
            return {}, [_lookup_warning(preset_id, "the control service could not be asked")]
        preset = next((offered for offered in presets if offered.id == preset_id), None)
        if preset is None:
            return {}, [_lookup_warning(preset_id, "the control service no longer offers it")]
        return {
            host.address: LanHost(
                host.fqdn,
                host.role,
                preset.id,
                {service.port: service.kind for service in host.services},
            )
            for host in preset.hosts
        }, []

    async def close(self, analysis: Analysis, task_id: int | None) -> None:
        """Copies the session's log into the task's folder and closes it. The ingest reads that
        folder, so it closes first; `close_at_end` then has nothing left to do.
        """
        if lan_preset_of(analysis) is None:
            return
        if await self._close_key(session_key(analysis.id), task_id):
            self._closed.add(analysis.id)

    async def close_at_end(self, analysis: Analysis) -> None:
        """Closes what the ingest did not, for every other way an analysis ends."""
        if lan_preset_of(analysis) is None:
            return
        if analysis.id in self._closed:
            self._closed.discard(analysis.id)
            return
        await self._close_key(session_key(analysis.id), analysis.cape_task_id)

    async def reconcile(self, find: Callable[[int], Awaitable[Analysis | None]]) -> None:
        """Closes the open sessions of analyses that are no longer active (a restart in the middle
        of a run, a close that failed). A key that is not `analysis-<id>` is not ours.
        """
        if not self._listing_due:
            return
        # Cleared before the call: a close that fails while the listing is in flight asks for the
        # next one, and that request must not be lost.
        self._listing_due = False
        try:
            keys = await self._control.lan_sessions()
        except GuestControlError as error:
            logger.warning("The fake-LAN sessions could not be listed, trying again: %s", error)
            self._listing_due = True
            return
        for key in keys:
            analysis_id = analysis_id_of(key)
            if analysis_id is None:
                continue
            analysis = await find(analysis_id)
            if analysis is not None and analysis.status in ACTIVE_STATUSES:
                # Its own end closes it, but that close may fail after this listing was read.
                self._listing_due = True
                continue
            await self._close_key(key, None if analysis is None else analysis.cape_task_id)

    async def _close_key(self, key: str, task_id: int | None) -> bool:
        try:
            await self._control.close_lan_session(key, task_id)
        except GuestControlError as error:
            logger.warning("Closing the fake-LAN session %s failed, retrying: %s", key, error)
            self._listing_due = True
            return False
        return True


def _lookup_warning(preset_id: str, why: str) -> str:
    return (
        f"The hosts of the fake local network {preset_id!r} could not be looked up ({why}), so "
        "the Network tab does not mark them and the events of their log were not indexed."
    )


def _start_failure(why: str) -> str:
    return f"The fake local network could not start: {why}"
