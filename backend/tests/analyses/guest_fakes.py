from app.guest.errors import GuestControlRejected
from app.guest.schemas import Guest, GuestProfile, GuestState, InteractiveOptions
from tests.guest.conftest import captured
from tests.guest.fakes import FakeGuestControl


def guest_named(
    name: str, state: GuestState = "ready", profile: str = "windows", badges: tuple[str, ...] = ()
) -> Guest:
    return Guest(name=name, state=state, profile=profile, badges=list(badges))


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
