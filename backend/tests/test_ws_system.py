import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.websockets import WebSocketDisconnect
from starlette.testclient import TestClient

from app.db.models.analysis import AnalysisStatus
from app.db.models.job import JobStatus, JobType
from app.health import ComponentHealth, HealthCheck, HealthStatus
from app.jobs.feed import JobFeed
from app.schemas.system import QueueSnapshot, RunningAnalysis
from app.ws.messages import HealthMessage, JobMessage, JobProgress, QueueMessage
from app.ws.system import (
    QueuePush,
    get_health_checks,
    get_health_push_interval_s,
    get_job_feed,
    get_queue_push_interval_s,
    get_queue_source,
    router,
    system_feed,
)

FAST_INTERVAL_S = 0.01


class OkCheck:
    async def check(self) -> ComponentHealth:
        return ComponentHealth(status=HealthStatus.OK)


class FlakyCheck:
    """Reports `ok` on its first call and `down` on every call after that, so a test can see a
    pushed message change state across two poll intervals without a real 5 s wait.
    """

    def __init__(self) -> None:
        self._calls = 0

    async def check(self) -> ComponentHealth:
        self._calls += 1
        if self._calls == 1:
            return ComponentHealth(status=HealthStatus.OK)
        return ComponentHealth(status=HealthStatus.DOWN, message="connection lost")


def healthy_checks() -> dict[str, HealthCheck]:
    return {
        "postgres": OkCheck(),
        "opensearch": OkCheck(),
        "cape": OkCheck(),
        "guest": OkCheck(),
    }


@pytest.fixture
def ws_app(app: FastAPI) -> FastAPI:
    # Mounted here, not in app/main.py: wiring the real app is a separate subtask's job (see
    # this subtask's report for the exact snippet to add there).
    app.include_router(router)
    app.dependency_overrides[get_queue_source] = lambda: FakeQueue(
        QueueSnapshot(running=[], queued_count=0, queued=[])
    )
    return app


@pytest.fixture
def client(ws_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(ws_app) as test_client:
        yield test_client


def use_checks(app: FastAPI, checks: dict[str, HealthCheck]) -> None:
    app.dependency_overrides[get_health_checks] = lambda: checks


def use_fast_interval(app: FastAPI) -> None:
    app.dependency_overrides[get_health_push_interval_s] = lambda: FAST_INTERVAL_S


def test_connecting_receives_a_health_message_immediately(
    ws_app: FastAPI, client: TestClient
) -> None:
    use_checks(ws_app, healthy_checks())
    use_fast_interval(ws_app)

    with client.websocket_connect("/ws/system") as websocket:
        payload = websocket.receive_json()

    message = HealthMessage.model_validate(payload)
    assert message.type == "health"
    assert message.data.postgres.status is HealthStatus.OK
    assert message.data.cape.status is HealthStatus.OK


def test_envelope_has_exactly_type_ts_and_data(ws_app: FastAPI, client: TestClient) -> None:
    use_checks(ws_app, healthy_checks())
    use_fast_interval(ws_app)

    with client.websocket_connect("/ws/system") as websocket:
        payload = websocket.receive_json()

    assert payload.keys() == {"type", "ts", "data"}
    assert payload["type"] == "health"
    datetime.fromisoformat(payload["ts"])
    assert payload["data"].keys() == {"postgres", "opensearch", "cape", "guest"}


def test_a_store_going_down_is_reflected_within_one_interval(
    ws_app: FastAPI, client: TestClient
) -> None:
    use_checks(ws_app, {**healthy_checks(), "opensearch": FlakyCheck()})
    use_fast_interval(ws_app)

    with client.websocket_connect("/ws/system") as websocket:
        first = receive_health(websocket)
        second = receive_health(websocket)

    assert first.data.opensearch.status is HealthStatus.OK
    assert second.data.opensearch.status is HealthStatus.DOWN


class DisconnectingWebSocket:
    """A fake transport whose `send_text` raises, as the real one does once the client has
    gone away. `TestClient`'s own disconnect (closing the `with websocket_connect` block)
    cancels the handler's task directly instead of raising through `send_text`, which would
    make a test built on it pass whether or not the handler's `except WebSocketDisconnect`
    exists; calling the handler directly against this fake is what actually exercises it.
    """

    async def accept(self) -> None:
        pass

    async def send_text(self, _: str) -> None:
        raise WebSocketDisconnect(code=1000)


async def test_disconnect_mid_stream_logs_no_unhandled_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        await system_feed(
            DisconnectingWebSocket(),  # type: ignore[arg-type]
            checks=healthy_checks(),
            interval_s=0.0,
            jobs=JobFeed(),
            queue=QueuePush(FakeQueue(QueueSnapshot(running=[], queued_count=0, queued=[])), 0.0),
        )

    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    assert not any(record.exc_info for record in caplog.records)


def test_health_message_appears_in_the_openapi_schema() -> None:
    schema_app = FastAPI()
    schema_app.include_router(router)

    schema = schema_app.openapi()

    assert "HealthMessage" in schema["components"]["schemas"]
    component_health_refs = [
        name for name in schema["components"]["schemas"] if "ComponentHealth" in name
    ]
    assert component_health_refs, "nested ComponentHealth model should also be hoisted"


def job_message(
    job_id: int = 1,
    status: JobStatus = JobStatus.RUNNING,
    progress: int = 0,
    step: str = "",
    result: dict[str, Any] | None = None,
) -> JobMessage:
    return JobMessage(
        job=JobProgress(
            id=job_id,
            type=JobType.EXPORT_REPORT,
            analysis_id=None,
            status=status,
            step=step,
            progress=progress,
            result=result,
        )
    )


def publish(client: TestClient, feed: JobFeed, message: JobMessage) -> None:
    # The feed's queues belong to the app's event loop, which the test client runs in a thread.
    assert client.portal is not None
    client.portal.call(feed.publish, message)


def receive_job(websocket: Any) -> JobMessage:
    while True:
        payload = websocket.receive_json()
        if payload["type"] == "job":
            return JobMessage.model_validate(payload)


def test_a_connected_client_receives_a_jobs_changes_in_order(
    ws_app: FastAPI, client: TestClient
) -> None:
    feed = JobFeed()
    use_checks(ws_app, healthy_checks())
    ws_app.dependency_overrides[get_job_feed] = lambda: feed

    with client.websocket_connect("/ws/system") as websocket:
        websocket.receive_json()
        for message in (
            job_message(status=JobStatus.PENDING),
            job_message(status=JobStatus.RUNNING),
            job_message(status=JobStatus.RUNNING, progress=50, step="Rendering"),
            job_message(status=JobStatus.DONE, progress=100, step="Rendering"),
        ):
            publish(client, feed, message)
        received = [receive_job(websocket) for _ in range(4)]

    assert [(m.job.status, m.job.progress) for m in received] == [
        (JobStatus.PENDING, 0),
        (JobStatus.RUNNING, 0),
        (JobStatus.RUNNING, 50),
        (JobStatus.DONE, 100),
    ]


def test_a_job_message_carries_the_job_under_a_job_key(ws_app: FastAPI, client: TestClient) -> None:
    feed = JobFeed()
    ws_app.dependency_overrides[get_job_feed] = lambda: feed
    use_checks(ws_app, healthy_checks())

    with client.websocket_connect("/ws/system") as websocket:
        websocket.receive_json()
        publish(client, feed, job_message(job_id=9, step="Rendering", progress=30))
        while (payload := websocket.receive_json())["type"] != "job":
            pass

    assert payload == {
        "type": "job",
        "job": {
            "id": 9,
            "type": "export_report",
            "analysis_id": None,
            "status": "running",
            "step": "Rendering",
            "progress": 30,
            "result": None,
        },
    }


def test_a_paused_job_message_carries_the_pause_instructions_in_its_result(
    ws_app: FastAPI, client: TestClient
) -> None:
    feed = JobFeed()
    ws_app.dependency_overrides[get_job_feed] = lambda: feed
    use_checks(ws_app, healthy_checks())
    pause = {"pause": {"instructions": "Switch Tamper Protection off"}}

    with client.websocket_connect("/ws/system") as websocket:
        websocket.receive_json()
        publish(client, feed, job_message(status=JobStatus.PAUSED, progress=62, result=pause))
        received = receive_job(websocket)

    assert (received.job.status, received.job.result) == (JobStatus.PAUSED, pause)


def test_a_client_connecting_while_a_job_is_paused_is_told_about_it(
    ws_app: FastAPI, client: TestClient
) -> None:
    feed = JobFeed()
    feed.publish(job_message(job_id=4, status=JobStatus.PAUSED, progress=62))
    use_checks(ws_app, healthy_checks())
    ws_app.dependency_overrides[get_job_feed] = lambda: feed

    with client.websocket_connect("/ws/system") as websocket:
        websocket.receive_json()
        initial = receive_job(websocket)

    assert (initial.job.id, initial.job.status) == (4, JobStatus.PAUSED)


def test_a_client_connecting_mid_job_is_told_about_the_active_jobs(
    ws_app: FastAPI, client: TestClient
) -> None:
    feed = JobFeed()
    feed.publish(job_message(job_id=4, progress=60))
    feed.publish(job_message(job_id=5, status=JobStatus.DONE, progress=100))
    use_checks(ws_app, healthy_checks())
    ws_app.dependency_overrides[get_job_feed] = lambda: feed

    with client.websocket_connect("/ws/system") as websocket:
        assert websocket.receive_json()["type"] == "health"
        initial = receive_job(websocket)

    assert (initial.job.id, initial.job.progress) == (4, 60)


def test_job_messages_appear_in_the_openapi_schema() -> None:
    schema_app = FastAPI()
    schema_app.include_router(router)

    schemas = schema_app.openapi()["components"]["schemas"]

    assert {"JobMessage", "JobProgress"} <= schemas.keys()


class FakeQueue:
    """Answers with whatever snapshot the test has set last, so a test decides when the queue
    changes without a database.
    """

    def __init__(self, snapshot: QueueSnapshot) -> None:
        self.current = snapshot

    async def __call__(self) -> QueueSnapshot:
        return self.current


def running_analysis(analysis_id: int) -> RunningAnalysis:
    return RunningAnalysis(
        id=analysis_id,
        filename=f"sample-{analysis_id}.exe",
        guest="lab3",
        status=AnalysisStatus.RUNNING,
        started_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
        elapsed_s=0,
    )


def queue_of(*running: RunningAnalysis) -> QueueSnapshot:
    return QueueSnapshot(running=list(running), queued_count=0, queued=[])


def use_queue(app: FastAPI, queue: FakeQueue) -> None:
    app.dependency_overrides[get_queue_source] = lambda: queue
    app.dependency_overrides[get_queue_push_interval_s] = lambda: FAST_INTERVAL_S


def receive_queue(websocket: Any) -> QueueMessage:
    while True:
        payload = websocket.receive_json()
        if payload["type"] == "queue":
            return QueueMessage.model_validate(payload)


def receive_health(websocket: Any) -> HealthMessage:
    while True:
        payload = websocket.receive_json()
        if payload["type"] == "health":
            return HealthMessage.model_validate(payload)


def test_a_connected_client_is_sent_the_queue(ws_app: FastAPI, client: TestClient) -> None:
    use_checks(ws_app, healthy_checks())
    use_fast_interval(ws_app)
    use_queue(ws_app, FakeQueue(queue_of(running_analysis(7))))

    with client.websocket_connect("/ws/system") as websocket:
        message = receive_queue(websocket)

    assert message.type == "queue"
    assert [analysis.id for analysis in message.data.running] == [7]


def test_a_queue_change_is_pushed_and_an_unchanged_queue_is_not(
    ws_app: FastAPI, client: TestClient
) -> None:
    queue = FakeQueue(queue_of(running_analysis(1)))
    use_checks(ws_app, healthy_checks())
    use_fast_interval(ws_app)
    use_queue(ws_app, queue)

    with client.websocket_connect("/ws/system") as websocket:
        first = receive_queue(websocket)
        queue.current = queue_of(running_analysis(1), running_analysis(2))
        second = receive_queue(websocket)

    assert [analysis.id for analysis in first.data.running] == [1]
    assert [analysis.id for analysis in second.data.running] == [1, 2]


def test_queue_message_appears_in_the_openapi_schema() -> None:
    schema_app = FastAPI()
    schema_app.include_router(router)

    schemas = schema_app.openapi()["components"]["schemas"]

    assert {"QueueMessage", "QueueSnapshot", "RunningAnalysis", "QueuedAnalysis"} <= schemas.keys()
