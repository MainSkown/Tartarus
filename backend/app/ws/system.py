import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from fastapi.websockets import WebSocketDisconnect

from app.analyses.queue_view import queue_snapshot
from app.db.base import utc_now
from app.health import HealthCheck, collect_health
from app.jobs.feed import JobFeed, Subscription
from app.schemas.system import QueueSnapshot
from app.ws.messages import HealthMessage, JobMessage, QueueMessage

logger = logging.getLogger(__name__)

HEALTH_PUSH_INTERVAL_S = 5.0
QUEUE_PUSH_INTERVAL_S = 1.0

QueueSource = Callable[[], Awaitable[QueueSnapshot]]


@dataclass(frozen=True)
class QueuePush:
    read: QueueSource
    interval_s: float


router = APIRouter()


def get_health_checks(websocket: WebSocket) -> Mapping[str, HealthCheck]:
    return cast(Mapping[str, HealthCheck], websocket.app.state.health_checks)


def get_job_feed(websocket: WebSocket) -> JobFeed:
    return cast(JobFeed, websocket.app.state.job_runner.feed)


def get_queue_source(websocket: WebSocket) -> QueueSource:
    session_factory = websocket.app.state.session_factory

    async def read_queue() -> QueueSnapshot:
        async with session_factory() as session:
            return await queue_snapshot(session, utc_now())

    return read_queue


def get_health_push_interval_s() -> float:
    return HEALTH_PUSH_INTERVAL_S


def get_queue_push_interval_s() -> float:
    return QUEUE_PUSH_INTERVAL_S


def get_queue_push(
    source: Annotated[QueueSource, Depends(get_queue_source)],
    interval_s: Annotated[float, Depends(get_queue_push_interval_s)],
) -> QueuePush:
    return QueuePush(source, interval_s)


async def _build_health_message(checks: Mapping[str, HealthCheck]) -> HealthMessage:
    return HealthMessage(ts=datetime.now(UTC), data=await collect_health(checks))


@router.websocket("/ws/system")
async def system_feed(
    websocket: WebSocket,
    checks: Annotated[Mapping[str, HealthCheck], Depends(get_health_checks)],
    interval_s: Annotated[float, Depends(get_health_push_interval_s)],
    jobs: Annotated[JobFeed, Depends(get_job_feed)],
    queue: Annotated[QueuePush, Depends(get_queue_push)],
) -> None:
    """Pushes a `health` message on connect and every `interval_s` seconds, a `queue` message on
    connect and whenever the running or queued analyses change (checked every `queue.interval_s`),
    and a `job` message whenever a job changes (on connect, one per job still active), until the
    client disconnects. `disk` (from the backend spec's `/ws/system` row) has no backing subsystem
    yet.
    """
    await websocket.accept()
    try:
        with jobs.subscribe() as subscription:
            await _send_pushes(websocket, checks, interval_s, subscription, queue)
    except WebSocketDisconnect:
        logger.info("client disconnected from /ws/system")


async def _send_pushes(
    websocket: WebSocket,
    checks: Mapping[str, HealthCheck],
    interval_s: float,
    subscription: Subscription,
    queue: QueuePush,
) -> None:
    await _send_health(websocket, checks)
    for message in subscription.snapshot:
        await websocket.send_text(message.model_dump_json())
    last_queue = await _send_queue(websocket, queue.read)
    next_health_at = time.monotonic() + interval_s
    next_queue_at = time.monotonic() + queue.interval_s
    while True:
        now = time.monotonic()
        if now >= next_health_at:
            await _send_health(websocket, checks)
            next_health_at = now + interval_s
        if now >= next_queue_at:
            last_queue = await _send_queue_if_changed(websocket, queue.read, last_queue)
            next_queue_at = now + queue.interval_s
        wait_s = min(next_health_at, next_queue_at) - time.monotonic()
        if wait_s <= 0:
            continue
        try:
            message = await asyncio.wait_for(subscription.inbox.get(), wait_s)
        except TimeoutError:
            continue
        await websocket.send_text(message.model_dump_json())


async def _send_health(websocket: WebSocket, checks: Mapping[str, HealthCheck]) -> None:
    await websocket.send_text((await _build_health_message(checks)).model_dump_json())


async def _send_queue(websocket: WebSocket, queue: QueueSource) -> QueueSnapshot:
    snapshot = await queue()
    await websocket.send_text(_queue_message(snapshot).model_dump_json())
    return snapshot


async def _send_queue_if_changed(
    websocket: WebSocket, queue: QueueSource, last_sent: QueueSnapshot
) -> QueueSnapshot:
    snapshot = await queue()
    if _queue_shape(snapshot) == _queue_shape(last_sent):
        return last_sent
    await websocket.send_text(_queue_message(snapshot).model_dump_json())
    return snapshot


def _queue_message(snapshot: QueueSnapshot) -> QueueMessage:
    return QueueMessage(ts=datetime.now(UTC), data=snapshot)


def _queue_shape(snapshot: QueueSnapshot) -> dict[str, object]:
    # `elapsed_s` moves every second while an analysis runs; it is not a change to the queue.
    return snapshot.model_dump(exclude={"running": {"__all__": {"elapsed_s"}}})


@router.get(
    "/api/system/ws-schema",
    tags=["system"],
    response_model=HealthMessage | JobMessage | QueueMessage,
    include_in_schema=True,
)
async def ws_message_schemas() -> HealthMessage | JobMessage | QueueMessage:
    """Not a real endpoint — never called by the frontend.

    FastAPI only adds a Pydantic model to `/openapi.json`'s `components.schemas` for models
    attached to an HTTP route it documents; it never introspects WebSocket handlers. Giving this
    route the message types as its response model is the only way to get them (and `disk` once
    it exists) into the generated OpenAPI schema, so `@hey-api/openapi-ts`
    emits a TypeScript type for it (see backend spec, "API client").
    """
    raise HTTPException(501, "schema export route only; not a real endpoint")
