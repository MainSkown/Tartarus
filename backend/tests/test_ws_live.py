import asyncio
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.websockets import WebSocketDisconnect
from starlette.testclient import TestClient, WebSocketTestSession

from app.db.models.analysis import AnalysisPhase, AnalysisStatus
from app.live.hub import LiveHub
from app.live.messages import StatusData
from app.ws.live import (
    get_live_hub,
    get_progress_source,
    get_status_interval_s,
    router,
)
from tests.live.events import make_event

ANALYSIS_ID = 3
URL = f"/ws/analyses/{ANALYSIS_ID}/live"
STATUS_INTERVAL_S = 0.01
PATIENCE_S = 3.0
NORMAL_CLOSE = 1000
NOT_FOUND = 4404


def status_data(
    status: AnalysisStatus = AnalysisStatus.RUNNING,
    phase: AnalysisPhase = AnalysisPhase.LIVE,
    elapsed_s: float | None = 12.5,
    remaining_s: float | None = 167.5,
) -> StatusData:
    return StatusData(status=status, phase=phase, elapsed_s=elapsed_s, remaining_s=remaining_s)


class StubProgress:
    """Answers what the test says the analysis looks like; can fail a few reads."""

    def __init__(self, current: StatusData | None = None) -> None:
        self.current = current
        self.failing_reads = 0
        self.reads = 0

    async def read(self, analysis_id: int) -> StatusData | None:
        assert analysis_id == ANALYSIS_ID
        self.reads += 1
        if self.failing_reads > 0:
            self.failing_reads -= 1
            raise ConnectionError("database hiccup")
        return self.current


class Wire:
    """A WebSocket test session whose reads give up instead of hanging the test."""

    def __init__(self, session: WebSocketTestSession) -> None:
        self._session = session
        self._reader = ThreadPoolExecutor(max_workers=1)

    def next(self) -> dict[str, Any]:
        future = self._reader.submit(self._session.receive_json)
        try:
            message: dict[str, Any] = future.result(PATIENCE_S)
        except FutureTimeout:
            pytest.fail("the server sent nothing within the patience")
        return message

    def next_of(self, kind: str, limit: int = 100) -> dict[str, Any]:
        for _ in range(limit):
            if (message := self.next())["type"] == kind:
                return message
        pytest.fail(f"no {kind} message in {limit} messages")

    def types(self, count: int) -> list[str]:
        return [self.next()["type"] for _ in range(count)]

    def send(self, message: dict[str, Any]) -> None:
        self._session.send_json(message)

    def sync(self) -> None:
        """Returns once the server has handled everything sent so far (it answers in order)."""
        self.send({"type": "ping"})
        self.next_of("pong")

    def until_close(self) -> tuple[list[str], int]:
        """The types of the messages still to come, and the code the server closes with."""
        kinds: list[str] = []
        for _ in range(100):
            future = self._reader.submit(self._session.receive_json)
            try:
                kinds.append(future.result(PATIENCE_S)["type"])
            except WebSocketDisconnect as closed:
                return kinds, closed.code
            except FutureTimeout:
                pytest.fail("the server did not close the connection")
        pytest.fail("the server kept sending instead of closing")

    def close_code(self) -> int:
        return self.until_close()[1]


@dataclass
class Setup:
    app: FastAPI
    client: TestClient
    hub: LiveHub
    progress: StubProgress

    def publish(self, *events: dict[str, Any]) -> None:
        self.client.portal.call(self.hub.publish, ANALYSIS_ID, list(events))

    def wait_until_idle(self) -> None:
        async def settle() -> None:
            for _ in range(500):
                if not self.hub.is_tracking(ANALYSIS_ID):
                    return
                await asyncio.sleep(0.01)
            pytest.fail("the connection's subscription was never released")

        self.client.portal.call(settle)


@pytest.fixture
def hub(request: pytest.FixtureRequest) -> LiveHub:
    return LiveHub(batch_interval_s=getattr(request, "param", 0.01))


@pytest.fixture
def progress() -> StubProgress:
    return StubProgress(status_data())


@pytest.fixture
def setup(hub: LiveHub, progress: StubProgress) -> Iterator[Setup]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_live_hub] = lambda: hub
    app.dependency_overrides[get_progress_source] = lambda: progress
    app.dependency_overrides[get_status_interval_s] = lambda: STATUS_INTERVAL_S
    with TestClient(app) as client:
        yield Setup(app, client, hub, progress)


def test_an_unknown_analysis_is_closed_with_4404(setup: Setup) -> None:
    setup.progress.current = None

    with setup.client.websocket_connect(URL) as session:
        assert Wire(session).close_code() == NOT_FOUND


def test_connecting_sends_the_status_then_the_process_tree_then_the_counts(setup: Setup) -> None:
    setup.hub.open(ANALYSIS_ID)
    setup.hub.publish(
        ANALYSIS_ID,
        [make_event("file", pid=10), make_event("file", pid=11), make_event("api", pid=10)],
    )

    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        first = [wire.next() for _ in range(4)]

    assert [m["type"] for m in first] == ["status", "process", "process", "counts"]
    assert first[0]["data"] == {
        "status": "running",
        "phase": "live",
        "elapsed_s": 12.5,
        "remaining_s": 167.5,
    }
    assert [(m["data"]["op"], m["data"]["node"]["pid"]) for m in first[1:3]] == [
        ("add", 10),
        ("add", 11),
    ]
    assert first[3]["data"]["total"] == 3


def test_events_published_after_connecting_arrive_without_tartarus_raw(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.sync()
        event = make_event("file", pid=21)

        setup.publish(event)
        message = wire.next_of("events")

    [received] = message["data"]["events"]
    assert received["event"]["id"] == event["event"]["id"]
    assert "raw" not in received["tartarus"]
    assert message["data"]["dropped"] == 0


def test_history_before_the_connection_is_not_replayed(setup: Setup) -> None:
    setup.hub.open(ANALYSIS_ID)
    setup.hub.publish(ANALYSIS_ID, [make_event("file")])

    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.sync()
        later = make_event("registry")
        setup.publish(later)
        message = wire.next_of("events")

    assert [e["event"]["id"] for e in message["data"]["events"]] == [later["event"]["id"]]


def test_the_api_lane_is_only_sent_after_asking_for_it(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.sync()
        api_event, file_event = make_event("api"), make_event("file")
        setup.publish(api_event, file_event)
        quiet = wire.next_of("events")

        wire.send({"type": "subscribe", "data": {"include_api": True}})
        wire.sync()
        setup.publish(api_event)
        noisy = wire.next_of("events")

    assert [e["tartarus"]["lane"] for e in quiet["data"]["events"]] == ["file"]
    assert [e["tartarus"]["lane"] for e in noisy["data"]["events"]] == ["api"]


def test_subscribe_narrows_by_lane_and_pid_and_can_be_resent(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.send({"type": "subscribe", "data": {"lanes": ["registry"], "pids": [5]}})
        wire.sync()
        wanted = make_event("registry", pid=5)
        setup.publish(make_event("file", pid=5), make_event("registry", pid=6), wanted)
        first = wire.next_of("events")

        wire.send({"type": "subscribe", "data": {"lanes": ["file"]}})
        wire.sync()
        other = make_event("file", pid=9)
        setup.publish(wanted, other)
        second = wire.next_of("events")

    assert [e["event"]["id"] for e in first["data"]["events"]] == [wanted["event"]["id"]]
    assert [e["event"]["id"] for e in second["data"]["events"]] == [other["event"]["id"]]


def test_a_query_is_refused_and_the_filter_stays_as_it_was(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.send({"type": "subscribe", "data": {"lanes": ["file"]}})
        wire.sync()

        wire.send({"type": "subscribe", "data": {"lanes": ["registry"], "query": "process.pid:4"}})
        error = wire.next_of("error")
        wire.sync()
        kept, dropped = make_event("file"), make_event("registry")
        setup.publish(dropped, kept)
        message = wire.next_of("events")

    assert error["data"]["code"] == "query_unsupported"
    assert [e["event"]["id"] for e in message["data"]["events"]] == [kept["event"]["id"]]


@pytest.mark.parametrize(
    "garbage",
    ["not json", '{"type": "nonsense"}', '{"type": "subscribe", "data": {"pids": "four"}}'],
)
def test_a_message_that_cannot_be_understood_gets_an_error_and_the_connection_lives(
    setup: Setup, garbage: str
) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        session.send_text(garbage)

        error = wire.next_of("error")
        wire.sync()

    assert error["data"]["code"] == "bad_message"


def test_ping_is_answered_with_pong(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.send({"type": "ping"})

        pong = wire.next_of("pong")

    assert set(pong) == {"type", "ts", "data"}


def test_the_status_is_repeated_while_the_analysis_runs(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)

        statuses = [wire.next_of("status") for _ in range(3)]

    assert {s["data"]["status"] for s in statuses} == {"running"}


def test_the_status_is_sent_when_it_changes_and_not_repeated_after_the_run(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.next_of("status")
        setup.progress.current = status_data(
            AnalysisStatus.PROCESSING, elapsed_s=200, remaining_s=0
        )
        while wire.next_of("status")["data"]["status"] != "processing":
            pass

        reads_before = setup.progress.reads
        while setup.progress.reads < reads_before + 5:
            time.sleep(STATUS_INTERVAL_S)
        setup.publish(make_event("file"))
        between: list[str] = []
        while (kind := wire.next()["type"]) != "events":
            between.append(kind)

    assert "status" not in between


def test_an_analysis_that_is_done_hands_over_with_a_final_status_and_phase(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.next_of("status")

        setup.progress.current = status_data(
            AnalysisStatus.DONE, AnalysisPhase.FINAL, elapsed_s=95, remaining_s=0
        )
        done = wire.next_of("status")
        while done["data"]["status"] != "done":
            done = wire.next_of("status")
        phase = wire.next()

        assert phase["type"] == "phase"
        assert phase["data"] == {"phase": "final"}
        assert wire.close_code() == NORMAL_CLOSE

    assert done["data"]["phase"] == "final"


def test_a_failed_analysis_hands_over_without_a_final_phase(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.next_of("status")

        setup.progress.current = status_data(AnalysisStatus.FAILED, elapsed_s=20, remaining_s=0)
        failed = wire.next_of("status")
        while failed["data"]["status"] != "failed":
            failed = wire.next_of("status")
        after, code = wire.until_close()

    assert after == []
    assert code == NORMAL_CLOSE


@pytest.mark.parametrize("hub", [3600.0], indirect=True)
def test_events_still_queued_when_the_analysis_ends_arrive_before_the_final_status(
    setup: Setup,
) -> None:
    first, waiting = make_event("file", pid=76), make_event("file", pid=77)
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.sync()
        setup.publish(first)
        wire.next_of("events")
        setup.publish(waiting)

        setup.progress.current = status_data(
            AnalysisStatus.DONE, AnalysisPhase.FINAL, elapsed_s=95, remaining_s=0
        )
        events = wire.next_of("events")
        final = wire.next_of("status")
        while final["data"]["status"] != "done":
            final = wire.next_of("status")

    assert [e["event"]["id"] for e in events["data"]["events"]] == [waiting["event"]["id"]]


def test_an_analysis_already_done_gets_status_phase_and_a_normal_close(setup: Setup) -> None:
    setup.progress.current = status_data(
        AnalysisStatus.DONE, AnalysisPhase.FINAL, elapsed_s=95, remaining_s=0
    )

    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        status, phase = wire.next(), wire.next()
        code = wire.close_code()

    assert (status["type"], status["data"]["status"]) == ("status", "done")
    assert phase["type"] == "phase"
    assert code == NORMAL_CLOSE


def test_an_analysis_already_failed_gets_its_status_and_a_normal_close(setup: Setup) -> None:
    setup.progress.current = status_data(AnalysisStatus.CANCELLED, elapsed_s=None, remaining_s=None)

    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        status = wire.next()
        code = wire.close_code()

    assert (status["type"], status["data"]["status"]) == ("status", "cancelled")
    assert code == NORMAL_CLOSE


def test_a_queued_analysis_is_waited_for_with_no_clock(setup: Setup) -> None:
    setup.progress.current = status_data(AnalysisStatus.QUEUED, elapsed_s=None, remaining_s=None)

    with setup.client.websocket_connect(URL) as session:
        status = Wire(session).next()

    assert status["data"]["elapsed_s"] is None
    assert status["data"]["remaining_s"] is None


def test_a_database_hiccup_does_not_end_the_connection(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.next_of("status")
        setup.progress.failing_reads = 3
        setup.progress.current = status_data(
            AnalysisStatus.PROCESSING, elapsed_s=200, remaining_s=0
        )

        while wire.next_of("status")["data"]["status"] != "processing":
            pass


def test_counts_are_pushed_periodically(hub: LiveHub, progress: StubProgress) -> None:
    app = FastAPI()
    app.include_router(router)
    fast_counts = LiveHub(batch_interval_s=0.01, counts_interval_s=0.05)
    app.dependency_overrides[get_live_hub] = lambda: fast_counts
    app.dependency_overrides[get_progress_source] = lambda: progress
    app.dependency_overrides[get_status_interval_s] = lambda: STATUS_INTERVAL_S

    with TestClient(app) as client, client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.next_of("counts")
        client.portal.call(fast_counts.publish, ANALYSIS_ID, [make_event("file")])

        totals = [wire.next_of("counts")["data"]["total"] for _ in range(3)]

    assert totals[-1] == 1


def test_leaving_releases_the_subscription(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        Wire(session).sync()
        assert setup.hub.is_tracking(ANALYSIS_ID)

    setup.wait_until_idle()


def test_a_hand_over_releases_the_subscription_too(setup: Setup) -> None:
    with setup.client.websocket_connect(URL) as session:
        wire = Wire(session)
        wire.sync()
        setup.progress.current = status_data(AnalysisStatus.FAILED, elapsed_s=1, remaining_s=0)
        assert wire.close_code() == NORMAL_CLOSE

    setup.wait_until_idle()


def test_a_connection_that_cannot_reach_the_database_is_closed_with_a_server_error(
    setup: Setup,
) -> None:
    setup.progress.failing_reads = 1

    with setup.client.websocket_connect(URL) as session:
        assert Wire(session).close_code() == 1011
