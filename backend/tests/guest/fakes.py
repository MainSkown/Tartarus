from typing import Any

from app.guest.schemas import Guest, GuestProfile, HealthCheckResult, MediaEntry
from tests.guest.conftest import captured


class FakeGuestControl:
    """Answers from the lists it was given, records the calls it got, and fails with `error`."""

    def __init__(
        self,
        guests: list[Guest] | None = None,
        *,
        error: Exception | None = None,
        check_result: HealthCheckResult | None = None,
    ) -> None:
        self.guests_listed = guests if guests is not None else real_guests()
        self.error = error
        self.check_result = check_result
        self.calls: list[tuple[str, Any]] = []

    def _record(self, call: str, argument: Any = None) -> None:
        self.calls.append((call, argument))
        if self.error is not None:
            raise self.error

    async def guests(self) -> list[Guest]:
        self._record("guests")
        return self.guests_listed

    async def guest(self, name: str) -> Guest:
        self._record("guest", name)
        return next(guest for guest in self.guests_listed if guest.name == name)

    async def delete_guest(self, name: str) -> None:
        self._record("delete_guest", name)

    async def check(self, name: str) -> HealthCheckResult:
        self._record("check", name)
        return self.check_result or HealthCheckResult.model_validate(captured("check_result.json"))

    async def media(self) -> list[MediaEntry]:
        self._record("media")
        return [MediaEntry.model_validate(entry) for entry in captured("media.json")]

    async def profiles(self) -> list[GuestProfile]:
        self._record("profiles")
        return [GuestProfile.model_validate(entry) for entry in captured("profiles.json")]


def real_guests() -> list[Guest]:
    return [Guest.model_validate(record) for record in captured("guests.json")]
