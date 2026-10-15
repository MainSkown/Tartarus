"""What differs between the desktops the tunnel serves: who may open one and where `guacd` goes.

An analysis's desktop and a guest build's desktop share the whole tunnel (`app.ws.desktop`); each
has a resolver that admits the viewer and names the VNC address, and nothing else.
"""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.desktop.admission import (
    AnalysisLookup,
    CloseRequest,
    TaskViewer,
    check_admission,
    wait_for_vnc_port,
)
from app.desktop.tunnel import VNC_HOST


class CheckUnavailableError(Exception):
    """Whether the desktop may be open could not be found out right now; `reason` is for the
    browser."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VncTarget:
    host: str
    port: int


class DesktopResolver(Protocol):
    label: str
    ended_reason: str

    async def refusal(self) -> CloseRequest | None:
        """Why the desktop may not be open, or None. Raises `CheckUnavailableError`."""
        ...

    async def wait_for_target(
        self, *, poll_interval_s: float, patience_s: float
    ) -> VncTarget | CloseRequest: ...


class AnalysisResolver:
    ended_reason = "analysis is no longer running"

    def __init__(self, lookup: AnalysisLookup, viewer: TaskViewer, analysis_id: int) -> None:
        self._lookup = lookup
        self._viewer = viewer
        self._analysis_id = analysis_id
        self.label = f"analysis {analysis_id}"

    async def refusal(self) -> CloseRequest | None:
        try:
            return check_admission(await self._lookup.snapshot(self._analysis_id))
        except SQLAlchemyError as error:
            raise CheckUnavailableError("analysis lookup unavailable") from error

    async def wait_for_target(
        self, *, poll_interval_s: float, patience_s: float
    ) -> VncTarget | CloseRequest:
        port = await wait_for_vnc_port(
            self._lookup,
            self._viewer,
            self._analysis_id,
            poll_interval_s=poll_interval_s,
            patience_s=patience_s,
        )
        return port if isinstance(port, CloseRequest) else VncTarget(VNC_HOST, port)
