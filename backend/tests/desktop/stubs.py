from dataclasses import dataclass, field

from app.cape.errors import CapeError, CapeUnreachable
from app.cape.models import TaskView
from app.db.models.analysis import AnalysisStatus
from app.desktop.admission import AnalysisSnapshot

TASK_ID = 41


def interactive_snapshot(
    status: AnalysisStatus = AnalysisStatus.RUNNING,
    *,
    cape_task_id: int | None = TASK_ID,
    interactive: bool = True,
) -> AnalysisSnapshot:
    return AnalysisSnapshot(status=status, interactive=interactive, cape_task_id=cape_task_id)


@dataclass
class StubLookup:
    snapshots: dict[int, AnalysisSnapshot] = field(default_factory=dict)
    asked: int = 0

    async def snapshot(self, analysis_id: int) -> AnalysisSnapshot | None:
        self.asked += 1
        return self.snapshots.get(analysis_id)


@dataclass
class StubViewer:
    """CAPE's task view: `options` per task, and errors to raise for the next calls."""

    options: dict[int, str | None] = field(default_factory=dict)
    errors: list[CapeError] = field(default_factory=list)
    viewed: list[int] = field(default_factory=list)
    options_once_viewed: tuple[int, str] | None = None

    async def task_view(self, task_id: int) -> TaskView:
        self.viewed.append(task_id)
        if self.options_once_viewed and len(self.viewed) >= self.options_once_viewed[0]:
            self.options[task_id] = self.options_once_viewed[1]
        if self.errors:
            raise self.errors.pop(0)
        return TaskView(id=task_id, status="running", options=self.options.get(task_id))


def cape_unreachable() -> CapeError:
    return CapeUnreachable("tasks/view", "HTTP 502")
