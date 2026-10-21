import asyncio

from app.guest.errors import GuestControlRejected
from app.guest.schemas import (
    Guest,
    GuestProfile,
    GuestResources,
    GuestState,
    InteractiveOptions,
    MemoryAnalysis,
    MissingSymbols,
)
from tests.guest.conftest import captured
from tests.guest.fakes import FakeGuestControl


def guest_named(
    name: str,
    state: GuestState = "ready",
    profile: str = "windows",
    badges: tuple[str, ...] = (),
    ram_mb: int | None = 4096,
) -> Guest:
    resources = None if ram_mb is None else GuestResources(vcpus=2, ram_mb=ram_mb, disk_gb=60)
    return Guest(name=name, state=state, profile=profile, badges=list(badges), resources=resources)


def windows_profile() -> GuestProfile:
    return GuestProfile.model_validate(captured("profiles.json")[0])


def profile_needing_enforced_timeout(profile_id: str = "ubuntu") -> GuestProfile:
    """A profile like the Linux one: it holds the run with a task field, not `interactive=1`."""
    interactive = InteractiveOptions(options="", task_fields={"enforce_timeout": True})
    agent = windows_profile().agent.model_copy(update={"interactive": interactive})
    return windows_profile().model_copy(
        update={"id": profile_id, "packages": ["elf", "sh"], "agent": agent}
    )


class ScriptedGuestControl(FakeGuestControl):
    """The control service as the analyses use it: guests, one guest or a 404, profiles, finish."""

    def __init__(
        self,
        guests: list[Guest] | None = None,
        *,
        profiles: list[GuestProfile] | None = None,
        error: Exception | None = None,
        finish_error: Exception | None = None,
    ) -> None:
        listed = guests if guests is not None else [guest_named("win"), guest_named("lab1")]
        super().__init__(listed, error=error)
        self.profiles_listed = profiles if profiles is not None else [windows_profile()]
        self.finish_error = finish_error
        self.finished: list[tuple[int, str]] = []
        self.memory_analysis: MemoryAnalysis | Exception = MemoryAnalysis(
            plugins={"windows.pslist": 144}, seconds=1.0, pids=[1234]
        )
        self.memory_deletion: Exception | None = None
        self.memory_script: list[MemoryAnalysis | Exception] = []
        self.memory_gate: asyncio.Event | None = None
        self.images_asked: list[str | None] = []
        self.symbols_made: list[MissingSymbols] = []
        self.symbols_error: Exception | None = None

    async def guest(self, name: str) -> Guest:
        self._record("guest", name)
        found = next((guest for guest in self.guests_listed if guest.name == name), None)
        if found is None:
            raise GuestControlRejected("guest", 404, f"no guest named {name}")
        return found

    async def profiles(self) -> list[GuestProfile]:
        self._record("profiles")
        return self.profiles_listed

    async def finish_task(self, task_id: int, guest: str) -> None:
        self._record("finish_task", (task_id, guest))
        if self.finish_error is not None:
            raise self.finish_error
        self.finished.append((task_id, guest))

    async def analyse_memory(self, task_id: int, image: str | None = None) -> MemoryAnalysis:
        self._record("analyse_memory", task_id)
        self.images_asked.append(image)
        if self.memory_gate is not None:
            await self.memory_gate.wait()
        answer = self.memory_script.pop(0) if self.memory_script else self.memory_analysis
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def make_symbols(self, missing: MissingSymbols) -> None:
        self._record("make_symbols", missing)
        if self.symbols_error is not None:
            raise self.symbols_error
        self.symbols_made.append(missing)

    async def delete_memory_dump(self, task_id: int) -> None:
        self._record("delete_memory_dump", task_id)
        if self.memory_deletion is not None:
            raise self.memory_deletion
