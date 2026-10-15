from dataclasses import dataclass, field

from app.cape.errors import CapeError, CapeUnreachable
from app.cape.models import TaskView
from app.db.models.analysis import AnalysisStatus
from app.desktop.admission import AnalysisSnapshot
from app.guest.errors import GuestControlError, GuestControlRejected, GuestControlUnreachable
from app.guest.schemas import BuildProgress, BuildStatus, Guest, GuestDisplay, GuestState

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


GUEST = "lab1"
BUILD_ID = "build-1"
BUILD_SCREEN = GuestDisplay(host="127.0.0.1", port=5931)


def building_guest(
    name: str = GUEST, *, state: GuestState = "building", build_id: str | None = BUILD_ID
) -> Guest:
    return Guest(name=name, state=state, build_id=build_id)


def build_status(
    *, status: BuildProgress = "running", desktop: bool = True, guest: str = GUEST
) -> BuildStatus:
    return BuildStatus(
        id=BUILD_ID,
        guest=guest,
        kind="build",
        status=status,
        step=0,
        steps=[],
        percent=10,
        desktop=desktop,
    )


def control_refused(call: str, status: int = 404) -> GuestControlError:
    return GuestControlRejected(call, status, "no such thing")


def control_unreachable(call: str = "guest") -> GuestControlError:
    return GuestControlUnreachable(call, "HTTP 502")


@dataclass
class StubGuestControl:
    """The control service's guests, builds and screens; whatever is missing is a 404, as there.

    `screen_once_asked` is `(n, display)`: the display appears with the n-th ask for it.
    `error` is raised by every call until it is set to None.
    """

    guests: dict[str, Guest] = field(default_factory=dict)
    builds: dict[str, BuildStatus] = field(default_factory=dict)
    screens: dict[str, GuestDisplay] = field(default_factory=dict)
    screen_once_asked: tuple[int, GuestDisplay] | None = None
    error: GuestControlError | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def guest(self, name: str) -> Guest:
        return self._answer("guest", name, self.guests)

    async def build(self, build_id: str) -> BuildStatus:
        return self._answer("build", build_id, self.builds)

    async def display(self, name: str) -> GuestDisplay:
        asked = sum(1 for call, _ in self.calls if call == "display") + 1
        if self.screen_once_asked and asked >= self.screen_once_asked[0]:
            self.screens[name] = self.screen_once_asked[1]
        return self._answer("display", name, self.screens)

    def _answer[T](self, call: str, key: str, known: dict[str, T]) -> T:
        self.calls.append((call, key))
        if self.error is not None:
            raise self.error
        if key not in known:
            raise control_refused(call)
        return known[key]


def guest_building_with_a_desktop() -> StubGuestControl:
    """The case the resolver admits: a building guest, its running build at a desktop step, and
    a display the control service can name."""
    return StubGuestControl(
        guests={GUEST: building_guest()},
        builds={BUILD_ID: build_status()},
        screens={GUEST: BUILD_SCREEN},
    )
