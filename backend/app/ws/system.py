import asyncio
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from fastapi.websockets import WebSocketDisconnect

from app.health import HealthCheck, collect_health
from app.jobs.feed import JobFeed, Subscription
from app.ws.messages import HealthMessage, JobMessage

logger = logging.getLogger(__name__)

HEALTH_PUSH_INTERVAL_S = 5.0

router = APIRouter()


def get_health_checks(websocket: WebSocket) -> Mapping[str, HealthCheck]:
    return cast(Mapping[str, HealthCheck], websocket.app.state.health_checks)


def get_job_feed(websocket: WebSocket) -> JobFeed:
    return cast(JobFeed, websocket.app.state.job_runner.feed)


def get_health_push_interval_s() -> float:
    return HEALTH_PUSH_INTERVAL_S


async def _build_health_message(checks: Mapping[str, HealthCheck]) -> HealthMessage:
    return HealthMessage(ts=datetime.now(UTC), data=await collect_health(checks))


@router.websocket("/ws/system")
async def system_feed(
    websocket: WebSocket,
    checks: Annotated[Mapping[str, HealthCheck], Depends(get_health_checks)],
    interval_s: Annotated[float, Depends(get_health_push_interval_s)],
    jobs: Annotated[JobFeed, Depends(get_job_feed)],
) -> None:
    """Pushes a `health` message on connect and every `interval_s` seconds, and a `job` message
    whenever a job changes (on connect, one per job still active), until the client disconnects.
    `queue` and `disk` (from the backend spec's `/ws/system` row) have no backing subsystem yet.
    """
    await websocket.accept()
    try:
        with jobs.subscribe() as subscription:
            await _send_health_then_jobs(websocket, checks, interval_s, subscription)
    except WebSocketDisconnect:
        logger.info("client disconnected from /ws/system")


async def _send_health_then_jobs(
    websocket: WebSocket,
    checks: Mapping[str, HealthCheck],
    interval_s: float,
    subscription: Subscription,
) -> None:
    await _send_health(websocket, checks)
    for message in subscription.snapshot:
        await websocket.send_text(message.model_dump_json())
    next_health_at = time.monotonic() + interval_s
    while True:
        wait_s = next_health_at - time.monotonic()
        if wait_s <= 0:
            await _send_health(websocket, checks)
            next_health_at = time.monotonic() + interval_s
            continue
        try:
            message = await asyncio.wait_for(subscription.inbox.get(), wait_s)
        except TimeoutError:
            continue
        await websocket.send_text(message.model_dump_json())


async def _send_health(websocket: WebSocket, checks: Mapping[str, HealthCheck]) -> None:
    await websocket.send_text((await _build_health_message(checks)).model_dump_json())


@router.get(
    "/api/system/ws-schema",
    tags=["system"],
    response_model=HealthMessage | JobMessage,
    include_in_schema=True,
)
async def ws_message_schemas() -> HealthMessage | JobMessage:
    """Not a real endpoint — never called by the frontend.

    FastAPI only adds a Pydantic model to `/openapi.json`'s `components.schemas` for models
    attached to an HTTP route it documents; it never introspects WebSocket handlers. Giving this
    route the message types as its response model is the only way to get them (and `queue`/
    `disk` once they exist) into the generated OpenAPI schema, so `@hey-api/openapi-ts`
    emits a TypeScript type for it (see backend spec, "API client").
    """
    raise HTTPException(501, "schema export route only; not a real endpoint")
