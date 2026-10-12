import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from fastapi.websockets import WebSocketDisconnect

from app.health import HealthCheck, collect_health
from app.ws.messages import HealthMessage

logger = logging.getLogger(__name__)

HEALTH_PUSH_INTERVAL_S = 5.0

router = APIRouter()


def get_health_checks(websocket: WebSocket) -> Mapping[str, HealthCheck]:
    return cast(Mapping[str, HealthCheck], websocket.app.state.health_checks)


def get_health_push_interval_s() -> float:
    return HEALTH_PUSH_INTERVAL_S


async def _build_health_message(checks: Mapping[str, HealthCheck]) -> HealthMessage:
    return HealthMessage(ts=datetime.now(UTC), data=await collect_health(checks))


@router.websocket("/ws/system")
async def system_health_feed(
    websocket: WebSocket,
    checks: Annotated[Mapping[str, HealthCheck], Depends(get_health_checks)],
    interval_s: Annotated[float, Depends(get_health_push_interval_s)],
) -> None:
    """Pushes a `health` message on connect and every `interval_s` seconds until the client
    disconnects. `queue`, `disk` and `job` (from the backend spec's `/ws/system` row) have no
    backing subsystem yet in this phase (no queue runner, no job runner), so this feed only
    ever sends `health`; likewise there's no event bus yet to push on change, so polling is the
    only trigger.
    """
    await websocket.accept()
    try:
        while True:
            message = await _build_health_message(checks)
            await websocket.send_text(message.model_dump_json())
            await asyncio.sleep(interval_s)
    except WebSocketDisconnect:
        logger.info("client disconnected from /ws/system")


@router.get(
    "/api/system/ws-schema",
    tags=["system"],
    response_model=HealthMessage,
    include_in_schema=True,
)
async def ws_message_schemas() -> HealthMessage:
    """Not a real endpoint — never called by the frontend.

    FastAPI only adds a Pydantic model to `/openapi.json`'s `components.schemas` for models
    attached to an HTTP route it documents; it never introspects WebSocket handlers. Giving this
    route `HealthMessage` as its response model is the only way to get that type (and `queue`/
    `disk`/`job` once they exist) into the generated OpenAPI schema, so `@hey-api/openapi-ts`
    emits a TypeScript type for it (see backend spec, "API client").
    """
    raise HTTPException(501, "schema export route only; not a real endpoint")
