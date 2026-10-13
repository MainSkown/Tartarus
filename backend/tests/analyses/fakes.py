import asyncio
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.analyses.ports import IngestFailedError, IngestResult, ReportOutcome
from app.cape.models import TaskView

FIRST_TASK_ID = 100
CAPE_STARTED_ON = datetime(2026, 5, 1, 12, 0, 5, tzinfo=UTC)

type Step = str | Exception


class FakeCape:
    """Answers `task_status` from a script per task; the last step repeats once it runs out."""

    def __init__(self) -> None:
        self.scripts: dict[int, list[Step]] = {}
        self.script_for_new_tasks: list[Step] = ["pending"]
        self.create_errors: list[Exception] = []
        self.calls: list[tuple[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.create_gate: asyncio.Event | None = None
        self.uploaded_bytes: list[bytes] = []
        self._next_task_id = FIRST_TASK_ID

    async def create_file_task(  # noqa: PLR0913 - mirrors CapeClient.create_file_task
        self,
        source: Path,
        filename: str,
        *,
        machine: str,
        route: str,
        timeout: int,  # noqa: ASYNC109
        package: str = "auto",
        interactive: bool = False,
    ) -> int:
        self.calls.append(("create", filename))
        if self.create_gate is not None:
            await self.create_gate.wait()
        if self.create_errors:
            raise self.create_errors.pop(0)
        task_id = self._next_task_id
        self._next_task_id += 1
        self.uploaded_bytes.append(source.read_bytes())  # noqa: ASYNC240 - a tiny local file
        self.scripts[task_id] = list(self.script_for_new_tasks)
        self.created.append(
            {
                "task_id": task_id,
                "filename": filename,
                "machine": machine,
                "route": route,
                "timeout": timeout,
                "package": package,
                "interactive": interactive,
            }
        )
        return task_id

    async def task_status(self, task_id: int) -> str:
        self.calls.append(("status", task_id))
        script = self.scripts[task_id]
        step = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(step, Exception):
            raise step
        return step

    async def task_view(self, task_id: int) -> TaskView:
        self.calls.append(("view", task_id))
        return TaskView(id=task_id, status="running", started_on=CAPE_STARTED_ON)

    def status_calls(self) -> int:
        return sum(1 for name, _ in self.calls if name == "status")


class FakeSamples:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self.missing = False
        self.opened: list[str] = []
        self.open_now = 0

    @asynccontextmanager
    async def open_plain(self, sha256: str) -> AsyncIterator[Path]:
        self.opened.append(sha256)
        if self.missing:
            raise FileNotFoundError(sha256)
        path = self._directory / sha256
        path.write_bytes(b"MZ plain sample")
        self.open_now += 1
        try:
            yield path
        finally:
            self.open_now -= 1


class FakeReports:
    """A `ReportReader` that remembers what it was asked to read and on which thread."""

    def __init__(self) -> None:
        self.outcome: ReportOutcome | Exception | None = None
        self.paths: list[Path] = []
        self.thread_ids: list[int] = []

    def __call__(self, path: Path) -> ReportOutcome:
        self.paths.append(path)
        self.thread_ids.append(threading.get_ident())
        if isinstance(self.outcome, Exception):
            raise self.outcome
        assert self.outcome is not None, "the test did not say what the report holds"
        return self.outcome


class FakeIngester:
    """An `EventIngester` that remembers what it was asked to index."""

    def __init__(self) -> None:
        self.result: IngestResult | IngestFailedError | Exception = IngestResult(0, {})
        self.requests: list[tuple[int, Path]] = []

    async def ingest(self, analysis_id: int, report_path: Path) -> IngestResult:
        self.requests.append((analysis_id, report_path))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeLive:
    """A `LiveCollection` that remembers what it was asked and can be made to fail or hang."""

    def __init__(self) -> None:
        self.journal: list[tuple[str, int]] = []
        self.started: list[tuple[int, int, datetime]] = []
        self.stopped: list[int] = []
        self.start_errors: list[Exception] = []
        self.stop_error: Exception | None = None
        self.hang_on_stop = False
        self.on_stop: Callable[[int], Awaitable[None]] | None = None

    def start(self, analysis_id: int, cape_task_id: int, started_at: datetime) -> None:
        self.journal.append(("start", analysis_id))
        if self.start_errors:
            raise self.start_errors.pop(0)
        self.started.append((analysis_id, cape_task_id, started_at))

    async def stop(self, analysis_id: int) -> None:
        self.journal.append(("stop", analysis_id))
        self.stopped.append(analysis_id)
        if self.on_stop is not None:
            await self.on_stop(analysis_id)
        if self.hang_on_stop:
            await asyncio.Event().wait()
        if self.stop_error is not None:
            raise self.stop_error
