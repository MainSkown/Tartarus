"""What the real fixture report normalises to, computed without the index, as a test oracle."""

import json
from collections.abc import Callable
from datetime import datetime
from functools import cache
from typing import Any

from app.ingest.clock import analysis_started
from app.ingest.ingester import default_normalizers
from app.ingest.protocol import IngestContext
from tests.ingest.conftest import FULL_REPORT

BENIGN_PID = 10116
CMD_PID = 9632


@cache
def fixture_events() -> list[dict[str, Any]]:
    report = json.loads(FULL_REPORT.read_text())
    started_at = analysis_started(report)
    assert started_at is not None
    context = IngestContext(analysis_id=6, started_at=started_at)
    return [event for n in default_normalizers() for event in n.normalise(report, context)]


def events_where(predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    return [event for event in fixture_events() if predicate(event)]


def of_pid(pid: int) -> Callable[[dict[str, Any]], bool]:
    return lambda event: event.get("process", {}).get("pid") == pid


def action_is(action: str) -> Callable[[dict[str, Any]], bool]:
    return lambda event: event["event"]["action"] == action


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
