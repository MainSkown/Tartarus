"""`WS /ws/analyses/{id}/desktop` and `WS /ws/guests/{name}/desktop`: a Guacamole tunnel from the
browser to `guacd`. The two routes differ only in their resolver (`app.desktop.resolver`): who may
open the desktop, and the VNC address `guacd` is sent to.

There is no authentication: Tartarus has one local analyst and compose binds the whole backend
to 127.0.0.1. What protects the guest instead is that nothing the browser sends decides where
`guacd` connects, and that only an allowlist of its instructions reaches `guacd`
(`app.desktop.tunnel`).

The browser side is `guacamole-common-js`'s `WebSocketTunnel`, which expects the subprotocol
`guacamole`, an internal instruction `0.,36.<uuid>;` as the first frame, and answers with internal
`ping` instructions. That is written from the library's documented behaviour and has not been run
against the real client.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, WebSocket
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.desktop.admission import (
    CLOSE_SERVER_ERROR,
    AnalysisLookup,
    CloseRequest,
    DbAnalysisLookup,
    TaskViewer,
)
from app.desktop.guacamole import (
    INTERNAL_OPCODE,
    Instruction,
    InstructionDecoder,
    ProtocolError,
    encode,
)
from app.desktop.guest_build import BuildControl, GuestBuildResolver
from app.desktop.resolver import AnalysisResolver, CheckUnavailableError, DesktopResolver, VncTarget
from app.desktop.tunnel import (
    HANDSHAKE_TIMEOUT_S,
    GuacdTunnel,
    TunnelError,
    forwardable_from_browser,
)

logger = logging.getLogger(__name__)

SUBPROTOCOL = "guacamole"
PING = "ping"

CLOSE_NORMAL = 1000
CLOSE_PROTOCOL_ERROR = 1002

router = APIRouter()


@dataclass(frozen=True)
class DesktopConfig:
    guacd_host: str
    guacd_port: int
    port_poll_interval_s: float = 1.0
    port_wait_timeout_s: float = 90.0
    status_check_interval_s: float = 2.0
    handshake_timeout_s: float = HANDSHAKE_TIMEOUT_S


def get_analysis_lookup(websocket: WebSocket) -> AnalysisLookup:
    return DbAnalysisLookup(
        cast(async_sessionmaker[AsyncSession], websocket.app.state.session_factory)
    )


def get_task_viewer(websocket: WebSocket) -> TaskViewer:
    return cast(TaskViewer, websocket.app.state.cape)


def get_guest_build_control(websocket: WebSocket) -> BuildControl:
    return cast(BuildControl, websocket.app.state.guest_control)


def get_desktop_config() -> DesktopConfig:
    settings = get_settings()
    return DesktopConfig(guacd_host=settings.guacd_host, guacd_port=settings.guacd_port)


@router.websocket("/ws/analyses/{analysis_id}/desktop")
async def desktop_tunnel(
    websocket: WebSocket,
    analysis_id: int,
    lookup: Annotated[AnalysisLookup, Depends(get_analysis_lookup)],
    viewer: Annotated[TaskViewer, Depends(get_task_viewer)],
    config: Annotated[DesktopConfig, Depends(get_desktop_config)],
) -> None:
    """Tunnels Guacamole instructions between the browser and `guacd`, one per text frame.

    Closes with `4404` for an unknown analysis, `4409` unless it is starting or running and was
    submitted interactive, and `4408` when the guest's desktop does not come up in time. The
    socket is accepted first because a browser only sees a close code on an accepted socket.
    """
    await _serve_socket(websocket, AnalysisResolver(lookup, viewer, analysis_id), config)


@router.websocket("/ws/guests/{name}/desktop")
async def guest_build_desktop_tunnel(
    websocket: WebSocket,
    name: str,
    control: Annotated[BuildControl, Depends(get_guest_build_control)],
    config: Annotated[DesktopConfig, Depends(get_desktop_config)],
) -> None:
    """Tunnels the screen of a guest while its build is at a step that shows a desktop (the
    install, the provisioning, a pause for the analyst), as `desktop_tunnel` does for an analysis.

    Closes with `4404` for an unknown guest or a name that is not a guest name, `4409` unless the
    guest has a running or paused build whose current step shows a desktop, and `4408` when the
    guest's screen does not come up in time. A ready guest's desktop is not served here.
    """
    await _serve_socket(websocket, GuestBuildResolver(control, name), config)


async def _serve_socket(
    websocket: WebSocket, resolver: DesktopResolver, config: DesktopConfig
) -> None:
    offered = websocket.scope.get("subprotocols", [])
    await websocket.accept(subprotocol=SUBPROTOCOL if SUBPROTOCOL in offered else None)
    outcome = await _DesktopSession(websocket, resolver, config).serve()
    if outcome is not None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=outcome.code, reason=outcome.reason)


class _DesktopSession:
    def __init__(
        self, websocket: WebSocket, resolver: DesktopResolver, config: DesktopConfig
    ) -> None:
        self._websocket = websocket
        self._resolver = resolver
        self._config = config
        self._browser = _BrowserInput(websocket)

    async def serve(self) -> CloseRequest | None:
        """What to close the socket with, or None when the browser is already gone."""
        try:
            refusal = await self._resolver.refusal()
        except CheckUnavailableError as error:
            logger.warning("%s: could not check the desktop", self._resolver.label, exc_info=True)
            return CloseRequest(CLOSE_SERVER_ERROR, error.reason)
        if refusal is not None:
            return refusal
        try:
            await self._websocket.send_text(encode(INTERNAL_OPCODE, str(uuid.uuid4())))
        except WebSocketDisconnect:
            return None
        return await _first_to_finish(self._browser.pump(), self._run_desktop())

    async def _run_desktop(self) -> CloseRequest | None:
        target = await self._resolver.wait_for_target(
            poll_interval_s=self._config.port_poll_interval_s,
            patience_s=self._config.port_wait_timeout_s,
        )
        if isinstance(target, CloseRequest):
            return target
        try:
            tunnel = await self._open_tunnel(target)
        except TunnelError as error:
            logger.warning("%s: no desktop: %s", self._resolver.label, error)
            return CloseRequest(CLOSE_SERVER_ERROR, "desktop service unavailable")
        self._browser.tunnel = tunnel
        try:
            return await _first_to_finish(
                self._relay_to_browser(tunnel), self._close_when_refused()
            )
        finally:
            self._browser.tunnel = None
            await tunnel.close()

    async def _open_tunnel(self, target: VncTarget) -> GuacdTunnel:
        return await GuacdTunnel.open(
            self._config.guacd_host,
            self._config.guacd_port,
            vnc_host=target.host,
            vnc_port=target.port,
            handshake_timeout_s=self._config.handshake_timeout_s,
        )

    async def _relay_to_browser(self, tunnel: GuacdTunnel) -> CloseRequest | None:
        try:
            while (instruction := await tunnel.receive()) is not None:
                await self._websocket.send_text(encode(instruction.opcode, *instruction.args))
                if instruction.opcode == "error":
                    logger.info(
                        "%s: desktop not available: %s", self._resolver.label, instruction.args
                    )
                    return CloseRequest(CLOSE_NORMAL, "desktop reported an error")
        except TunnelError:
            return CloseRequest(CLOSE_SERVER_ERROR, "desktop sent malformed data")
        except WebSocketDisconnect:
            return None
        return CloseRequest(CLOSE_NORMAL, "desktop closed")

    async def _close_when_refused(self) -> CloseRequest:
        while True:
            await asyncio.sleep(self._config.status_check_interval_s)
            try:
                refusal = await self._resolver.refusal()
            except CheckUnavailableError:
                logger.warning(
                    "%s: could not check whether the desktop may stay open",
                    self._resolver.label,
                    exc_info=True,
                )
                continue
            if refusal is not None:
                return CloseRequest(CLOSE_NORMAL, self._resolver.ended_reason)


class _BrowserInput:
    """Reads the browser's frames for the whole life of the socket: it answers pings and notices
    a disconnect even while the port is still being waited for.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self.tunnel: GuacdTunnel | None = None

    async def pump(self) -> CloseRequest | None:
        decoder = InstructionDecoder()
        while True:
            message = await self._websocket.receive()
            if message["type"] == "websocket.disconnect":
                return None
            text = message.get("text")
            if text is None:
                continue
            try:
                instructions = decoder.feed(text)
            except ProtocolError:
                return CloseRequest(CLOSE_PROTOCOL_ERROR, "malformed instruction")
            for instruction in instructions:
                await self._handle(instruction)

    async def _handle(self, instruction: Instruction) -> None:
        if instruction.opcode == INTERNAL_OPCODE:
            if instruction.args[:1] == (PING,):
                await self._websocket.send_text(encode(INTERNAL_OPCODE, *instruction.args))
            return
        if self.tunnel is None or not forwardable_from_browser(instruction):
            logger.debug("dropped %r from the browser", instruction.opcode)
            return
        try:
            await self.tunnel.send(instruction)
        except TunnelError:
            logger.debug("guacd is gone; the relay will close the tunnel")


async def _first_to_finish[Result](*work: Coroutine[Any, Any, Result]) -> Result:
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(item) for item in work]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        result = next(iter(done)).result()
        for task in tasks:
            task.cancel()
    return result
