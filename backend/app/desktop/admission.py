"""Who may open the desktop, and when the guest's VNC port is known."""

import asyncio
import logging
from dataclasses import dataclass
from typing import NamedTuple, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.guest_choice import recorded_guest
from app.cape.errors import CapeError
from app.cape.models import TaskView
from app.db.analysis_repository import get_analysis
from app.db.models.analysis import AnalysisStatus
from app.desktop.vnc import vnc_port

logger = logging.getLogger(__name__)

CLOSE_SERVER_ERROR = 1011
CLOSE_NOT_FOUND = 4404
CLOSE_NOT_AVAILABLE_YET = 4408
CLOSE_CONFLICT = 4409
REASON_MACHINE_MISMATCH = "desktop_machine_mismatch"

DESKTOP_STATUSES = frozenset({AnalysisStatus.STARTING, AnalysisStatus.RUNNING})


class CloseRequest(NamedTuple):
    code: int
    reason: str


@dataclass(frozen=True)
class AnalysisSnapshot:
    status: AnalysisStatus
    interactive: bool
    cape_task_id: int | None
    guest: str | None


class AnalysisLookup(Protocol):
    async def snapshot(self, analysis_id: int) -> AnalysisSnapshot | None: ...


class TaskViewer(Protocol):
    """The part of `CapeClient` the desktop uses."""

    async def task_view(self, task_id: int) -> TaskView: ...


class DbAnalysisLookup:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def snapshot(self, analysis_id: int) -> AnalysisSnapshot | None:
        async with self._session_factory() as session:
            analysis = await get_analysis(session, analysis_id)
        if analysis is None:
            return None
        return AnalysisSnapshot(
            status=analysis.status,
            interactive=analysis.options.get("interactive") is True,
            cape_task_id=analysis.cape_task_id,
            guest=recorded_guest(analysis.options),
        )


def check_admission(snapshot: AnalysisSnapshot | None) -> CloseRequest | None:
    if snapshot is None:
        return CloseRequest(CLOSE_NOT_FOUND, "analysis not found")
    if snapshot.status not in DESKTOP_STATUSES:
        return CloseRequest(CLOSE_CONFLICT, f"analysis is {snapshot.status.value}, not running")
    if not snapshot.interactive:
        return CloseRequest(CLOSE_CONFLICT, "analysis was not submitted as interactive")
    return None


async def wait_for_vnc_port(
    lookup: AnalysisLookup,
    viewer: TaskViewer,
    analysis_id: int,
    *,
    poll_interval_s: float,
    patience_s: float,
) -> int | CloseRequest:
    """The port appears in the task's options only once CAPE has started the guest, which is
    later than the task being `running`; keep asking until it does or the patience runs out.
    """
    deadline = asyncio.get_running_loop().time() + patience_s
    while True:
        snapshot = await lookup.snapshot(analysis_id)
        if (refusal := check_admission(snapshot)) is not None:
            return refusal
        if snapshot is not None and snapshot.cape_task_id is not None:
            found = await _recorded_port(viewer, snapshot.cape_task_id, snapshot)
            if found is not None:
                return found
        if asyncio.get_running_loop().time() >= deadline:
            return CloseRequest(CLOSE_NOT_AVAILABLE_YET, "desktop not available yet")
        await asyncio.sleep(poll_interval_s)


async def _recorded_port(
    viewer: TaskViewer, task_id: int, snapshot: AnalysisSnapshot
) -> int | CloseRequest | None:
    """The VNC port of the analysis' task, or a refusal when CAPE ran that task on another guest:
    its port then shows that guest's screen. None while the task or its port is not known yet."""
    try:
        view = await viewer.task_view(task_id)
    except CapeError as error:
        logger.debug("could not read the options of CAPE task %s: %s", task_id, error)
        return None
    if view.machine != snapshot.guest:
        return CloseRequest(CLOSE_CONFLICT, REASON_MACHINE_MISMATCH)
    return vnc_port(view.options)
