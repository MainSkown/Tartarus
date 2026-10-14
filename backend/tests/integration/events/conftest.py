from datetime import datetime
from typing import Any

from tests.integration.views.conftest import ViewStack
from tests.integration.views.conftest import view_stack as view_stack  # noqa: PLC0414
from tests.integration.views.helpers import indexed_events

Event = dict[str, Any]


def events_url(stack: ViewStack, tail: str, analysis_id: int | None = None) -> str:
    target = stack.analysis_id if analysis_id is None else analysis_id
    return f"/api/analyses/{target}/events/{tail}"


async def post_ok(stack: ViewStack, tail: str, body: dict[str, Any]) -> Any:
    response = await stack.client.post(events_url(stack, tail), json=body)
    assert response.status_code == 200, response.text
    return response.json()


def moment(event: Event) -> datetime:
    return datetime.fromisoformat(event["@timestamp"])


def in_time_order(events: list[Event], descending: bool = False) -> list[Event]:
    return sorted(
        events,
        key=lambda event: (moment(event), event["event"]["sequence"], event["event"]["id"]),
        reverse=descending,
    )


async def all_events(stack: ViewStack) -> list[Event]:
    return list((await indexed_events(stack)).values())
