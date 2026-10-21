import asyncio
import json
import random
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ingest.live_capemon import LiveCapemon
from app.ingest.protocol import IngestContext
from app.live.bson_log import BsonLogParser, EnvironRecord
from app.search.index import IndexingError
from tests.live.conftest import FIXTURES, PIDS

Event = dict[str, Any]

ANALYSIS_ID = 45
STARTED_AT = datetime(2026, 10, 13, 11, 39, 48, tzinfo=UTC)
POLL_S = 0.005


def fixture_logs() -> dict[str, bytes]:
    return {f"{pid}.bson": (FIXTURES / f"{pid}.bson").read_bytes() for pid in sorted(PIDS)}


def reference_events(
    logs: dict[str, bytes] | None = None, analysis_id: int = ANALYSIS_ID
) -> list[Event]:
    """What feeding each whole file once through the parser and `LiveCapemon` gives."""
    live = LiveCapemon(IngestContext(analysis_id, STARTED_AT))
    events: list[Event] = []
    for name, data in (fixture_logs() if logs is None else logs).items():
        events += live.update(name, BsonLogParser().feed(data))
    return events + live.flush()


def comparable(event: Event) -> Event:
    """The event minus what legitimately depends on the order the logs were read in: the
    sequence counter, and the name of a parent, which only shows once its log has been read."""
    process = event.get("process", {})
    parent = {k: v for k, v in process.get("parent", {}).items() if k != "name"}
    return {
        **event,
        "event": {k: v for k, v in event["event"].items() if k != "sequence"},
        "process": {**process, "parent": parent},
    }


def by_id(events: Iterable[Event]) -> dict[str, Event]:
    return {event["event"]["id"]: comparable(event) for event in events}


class FakeSink:
    """Stands in for the hub: remembers every batch and every error it was handed."""

    def __init__(self) -> None:
        self.batches: list[list[Event]] = []
        self.errors: list[tuple[str, str]] = []

    @property
    def events(self) -> list[Event]:
        return [event for batch in self.batches for event in batch]

    def publish(self, analysis_id: int, events: list[Event]) -> None:
        assert analysis_id == ANALYSIS_ID
        self.batches.append(list(events))

    def report_error(self, analysis_id: int, code: str, message: str) -> None:
        assert analysis_id == ANALYSIS_ID
        self.errors.append((code, message))

    def error_codes(self) -> list[str]:
        return [code for code, _ in self.errors]


class FakeStore:
    """An event store keyed by event id, like the real index."""

    def __init__(self) -> None:
        self.documents: dict[str, Event] = {}
        self.templates = 0
        self.indexes_ensured = 0
        self.bulk_calls = 0
        self.failures_left = 0

    async def ensure_template(self) -> None:
        self.templates += 1

    async def ensure_index(self, analysis_id: int) -> None:
        assert analysis_id == ANALYSIS_ID
        self.indexes_ensured += 1

    async def bulk_index(self, analysis_id: int, events: Iterable[Event]) -> int:
        assert analysis_id == ANALYSIS_ID
        self.bulk_calls += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            raise IndexingError("OpenSearch said no")
        batch = list(events)
        for event in batch:
            self.documents[event["event"]["id"]] = event
        return len(batch)


def _append(path: Path, data: bytes) -> None:
    with path.open("ab") as handle:
        handle.write(data)


async def append(directory: Path, name: str, data: bytes) -> None:
    await asyncio.to_thread(_append, directory / name, data)


async def write_in_slices(
    directory: Path,
    logs: dict[str, bytes],
    seed: int,
    *,
    max_slice: int = 2500,
    pause_s: float = 0.002,
) -> None:
    """Appends the logs to `directory` in random slices, interleaving the files and cutting
    inside records, as CAPE's ResultServer does while the guest runs."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible test schedule, not security
    written = dict.fromkeys(logs, 0)
    while remaining := [name for name in logs if written[name] < len(logs[name])]:
        name = rng.choice(remaining)
        size = rng.randint(1, max_slice)
        await append(directory, name, logs[name][written[name] : written[name] + size])
        written[name] += size
        await asyncio.sleep(pause_s)


async def wait_until(condition: Callable[[], bool], timeout_s: float = 5.0) -> None:
    async def poll() -> None:
        while not condition():  # noqa: ASYNC110 - polling a plain predicate
            await asyncio.sleep(0.002)

    await asyncio.wait_for(poll(), timeout_s)


async def wait_for_quiet(sink: FakeSink, quiet_s: float = 0.05) -> None:
    """Waits until nothing new was published for `quiet_s`."""
    count = -1
    while count != len(sink.events):
        count = len(sink.events)
        await asyncio.sleep(quiet_s)


type Awaiting = Callable[[], Awaitable[None]]


def write_final_report(directory: Path) -> Path:
    """A CAPE report built from the fixture logs, starting when the live tests say they did.

    The trimmed fixture lacks the `environ` records, where the command line comes from.
    """
    report = json.loads((FIXTURES / "report_calls.json").read_text())
    report["info"]["started"] = STARTED_AT.strftime("%Y-%m-%d %H:%M:%S")
    for entry in report["behavior"]["processes"]:
        records = BsonLogParser().feed((FIXTURES / f"{entry['process_id']}.bson").read_bytes())
        [environ] = [r for r in records if isinstance(r, EnvironRecord)]
        entry["environ"] = {"CommandLine": environ.values["CommandLine"]}
    path = directory / "report.json"
    path.write_text(json.dumps(report))
    return path
