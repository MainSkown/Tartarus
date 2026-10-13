"""`WS /ws/analyses/{id}/desktop`: a Guacamole tunnel from the browser to `guacd`.

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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.desktop.admission import (
    AnalysisLookup,
    CloseRequest,
    DbAnalysisLookup,
    TaskViewer,
    check_admission,
    wait_for_vnc_port,
)
from app.desktop.guacamole import (
    INTERNAL_OPCODE,
    Instruction,
    InstructionDecoder,
    ProtocolError,
    encode,
)
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
CLOSE_SERVER_ERROR = 1011

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
    offered = websocket.scope.get("subprotocols", [])
    await websocket.accept(subprotocol=SUBPROTOCOL if SUBPROTOCOL in offered else None)
    outcome = await _DesktopSession(websocket, analysis_id, lookup, viewer, config).serve()
    if outcome is not None:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=outcome.code, reason=outcome.reason)


class _DesktopSession:
    def __init__(
        self,
        websocket: WebSocket,
        analysis_id: int,
        lookup: AnalysisLookup,
        viewer: TaskViewer,
        config: DesktopConfig,
    ) -> None:
        self._websocket = websocket
        self._analysis_id = analysis_id
        self._lookup = lookup
        self._viewer = viewer
        self._config = config
        self._browser = _BrowserInput(websocket)

    async def serve(self) -> CloseRequest | None:
        """What to close the socket with, or None when the browser is already gone."""
        refusal = check_admission(await self._lookup.snapshot(self._analysis_id))
        if refusal is not None:
            return refusal
        try:
            await self._websocket.send_text(encode(INTERNAL_OPCODE, str(uuid.uuid4())))
        except WebSocketDisconnect:
            return None
        return await _first_to_finish(self._browser.pump(), self._run_desktop())

    async def _run_desktop(self) -> CloseRequest | None:
        port = await wait_for_vnc_port(
            self._lookup,
            self._viewer,
            self._analysis_id,
            poll_interval_s=self._config.port_poll_interval_s,
            patience_s=self._config.port_wait_timeout_s,
        )
        if isinstance(port, CloseRequest):
            return port
        try:
            tunnel = await GuacdTunnel.open(
                self._config.guacd_host,
                self._config.guacd_port,
                vnc_port=port,
                handshake_timeout_s=self._config.handshake_timeout_s,
            )
        except TunnelError as error:
            logger.warning("analysis %s: no desktop: %s", self._analysis_id, error)
            return CloseRequest(CLOSE_SERVER_ERROR, "desktop service unavailable")
        self._browser.tunnel = tunnel
        try:
            return await _first_to_finish(
                self._relay_to_browser(tunnel), self._close_when_analysis_ends()
            )
        finally:
            self._browser.tunnel = None
            await tunnel.close()

    async def _relay_to_browser(self, tunnel: GuacdTunnel) -> CloseRequest | None:
        try:
            while (instruction := await tunnel.receive()) is not None:
                await self._websocket.send_text(encode(instruction.opcode, *instruction.args))
                if instruction.opcode == "error":
                    logger.info(
                        "analysis %s: desktop not available: %s",
                        self._analysis_id,
                        instruction.args,
                    )
                    return CloseRequest(CLOSE_NORMAL, "desktop reported an error")
        except TunnelError:
            return CloseRequest(CLOSE_SERVER_ERROR, "desktop sent malformed data")
        except WebSocketDisconnect:
            return None
        return CloseRequest(CLOSE_NORMAL, "desktop closed")

    async def _close_when_analysis_ends(self) -> CloseRequest:
        while True:
            await asyncio.sleep(self._config.status_check_interval_s)
            try:
                snapshot = await self._lookup.snapshot(self._analysis_id)
            except SQLAlchemyError:
                logger.warning(
                    "analysis %s: could not check its status", self._analysis_id, exc_info=True
                )
                continue
            if check_admission(snapshot) is not None:
                return CloseRequest(CLOSE_NORMAL, "analysis is no longer running")


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
