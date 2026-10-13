"""`WS /ws/analyses/{id}/live`: the events, processes and status of an analysis as it runs.

There is no authentication: Tartarus has one local analyst and compose binds the backend to
127.0.0.1. Close codes: 1000 when the analysis has ended and everything was sent, 4404 for an
unknown analysis, 1011 when the database could not be read at connect. The socket is accepted
before any close so a browser can see the code.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, WebSocket
from fastapi.websockets import WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.analysis import AnalysisStatus
from app.live.hub import LiveFilter, LiveHub, Subscription
from app.live.messages import (
    BAD_MESSAGE,
    QUERY_UNSUPPORTED,
    ClientMessage,
    ErrorData,
    ErrorMessage,
    LiveMessage,
    PhaseData,
    PhaseMessage,
    PingMessage,
    PongMessage,
    StatusData,
    StatusMessage,
)
from app.live.progress import DbProgressSource, ProgressSource, is_finished

logger = logging.getLogger(__name__)

CLOSE_NORMAL = 1000
CLOSE_SERVER_ERROR = 1011
CLOSE_NOT_FOUND = 4404
STATUS_INTERVAL_S = 1.0

CLIENT_MESSAGES: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

router = APIRouter()


def get_live_hub(websocket: WebSocket) -> LiveHub:
    return cast(LiveHub, websocket.app.state.live_hub)


def get_progress_source(websocket: WebSocket) -> ProgressSource:
    return DbProgressSource(
        cast(async_sessionmaker[AsyncSession], websocket.app.state.session_factory)
    )


def get_status_interval_s() -> float:
    return STATUS_INTERVAL_S


@router.websocket("/ws/analyses/{analysis_id}/live")
async def live_feed(
    websocket: WebSocket,
    analysis_id: int,
    hub: Annotated[LiveHub, Depends(get_live_hub)],
    progress: Annotated[ProgressSource, Depends(get_progress_source)],
    status_interval_s: Annotated[float, Depends(get_status_interval_s)],
) -> None:
    """Streams `status`, `process`, `counts` and `events` messages until the analysis ends.

    Send `{type: "subscribe", data: {lanes?, pids?, include_api?}}` to filter the events (it
    replaces the previous filter), and `{type: "ping"}` to get a `pong`. `query` is refused with
    an `error` message (code `query_unsupported`). When the analysis ends the server sends the
    last `status`, then `phase: final` if it finished `done`, and closes with 1000.
    """
    await websocket.accept()
    code = await _serve(websocket, analysis_id, hub, progress, status_interval_s)
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close(code=code)


async def _serve(
    websocket: WebSocket,
    analysis_id: int,
    hub: LiveHub,
    progress: ProgressSource,
    status_interval_s: float,
) -> int:
    try:
        first = await progress.read(analysis_id)
    except Exception:
        logger.exception("Reading analysis %s for its live feed failed", analysis_id)
        return CLOSE_SERVER_ERROR
    if first is None:
        return CLOSE_NOT_FOUND
    connection = _Connection(websocket, analysis_id, hub, progress, status_interval_s)
    try:
        return await connection.run(first)
    except (WebSocketDisconnect, RuntimeError):
        return CLOSE_NORMAL
    finally:
        connection.release()


class _Connection:
    def __init__(
        self,
        websocket: WebSocket,
        analysis_id: int,
        hub: LiveHub,
        progress: ProgressSource,
        status_interval_s: float,
    ) -> None:
        self._websocket = websocket
        self._analysis_id = analysis_id
        self._hub = hub
        self._progress = progress
        self._status_interval_s = status_interval_s
        self._subscription: Subscription | None = None

    def release(self) -> None:
        if self._subscription is not None:
            self._subscription.close()

    async def run(self, first: StatusData) -> int:
        await self._send(_status_message(first))
        if is_finished(first.status):
            await self._send_phase_if_done(first)
            return CLOSE_NORMAL
        subscription = self._hub.subscribe(self._analysis_id, LiveFilter())
        self._subscription = subscription
        return await _first_to_finish(self._stream(subscription, first), self._listen(subscription))

    async def _stream(self, subscription: Subscription, last: StatusData) -> int:
        next_status_at = time.monotonic() + self._status_interval_s
        while True:
            wait_s = max(0.0, next_status_at - time.monotonic())
            await self._send_all(await subscription.next_messages(timeout_s=wait_s))
            if time.monotonic() < next_status_at:
                continue
            next_status_at = time.monotonic() + self._status_interval_s
            current = await self._read_status(last)
            if current is None:
                return CLOSE_NOT_FOUND
            if is_finished(current.status):
                await self._send_all(subscription.flush())
                await self._send(_status_message(current))
                await self._send_phase_if_done(current)
                return CLOSE_NORMAL
            if _moved_on(last, current) or current.status is AnalysisStatus.RUNNING:
                await self._send(_status_message(current))
            last = current

    async def _read_status(self, last: StatusData) -> StatusData | None:
        try:
            return await self._progress.read(self._analysis_id)
        except Exception:
            logger.exception("Reading analysis %s for its live feed failed", self._analysis_id)
            return last

    async def _send_phase_if_done(self, final: StatusData) -> None:
        if final.status is AnalysisStatus.DONE:
            await self._send(PhaseMessage(ts=_now(), data=PhaseData()))

    async def _listen(self, subscription: Subscription) -> int:
        while True:
            message = await self._websocket.receive()
            if message["type"] == "websocket.disconnect":
                return CLOSE_NORMAL
            _answer(subscription, message.get("text"))

    async def _send_all(self, messages: list[LiveMessage]) -> None:
        for message in messages:
            await self._send(message)

    async def _send(self, message: LiveMessage) -> None:
        await self._websocket.send_text(message.model_dump_json())


async def _first_to_finish[Result](*work: Coroutine[Any, Any, Result]) -> Result:
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(item) for item in work]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        result = next(iter(done)).result()
        for task in tasks:
            task.cancel()
    return result


def _answer(subscription: Subscription, text: str | None) -> None:
    try:
        message = CLIENT_MESSAGES.validate_json(text or "")
    except ValidationError:
        subscription.push(_error(BAD_MESSAGE, "Not a message the live feed understands"))
        return
    if isinstance(message, PingMessage):
        subscription.push(PongMessage(ts=_now()))
    elif message.data.query is not None:
        subscription.push(_error(QUERY_UNSUPPORTED, "Queries arrive with the query language"))
    else:
        subscription.set_filters(LiveFilter.from_subscribe(message.data))


def _error(code: str, message: str) -> ErrorMessage:
    return ErrorMessage(ts=_now(), data=ErrorData(code=code, message=message))


def _status_message(status: StatusData) -> StatusMessage:
    return StatusMessage(ts=_now(), data=status)


def _moved_on(before: StatusData, after: StatusData) -> bool:
    return (before.status, before.phase) != (after.status, after.phase)


def _now() -> datetime:
    return datetime.now(UTC)
