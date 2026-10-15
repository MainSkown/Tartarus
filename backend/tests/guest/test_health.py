import pytest

from app.guest.errors import GuestControlBadResponse, GuestControlRejected, GuestControlUnreachable
from app.guest.health import GuestCheck
from app.guest.schemas import Guest, GuestState
from app.health import ComponentHealth, HealthStatus
from tests.guest.conftest import captured


def guest(name: str, state: GuestState) -> Guest:
    return Guest(name=name, state=state)


class FakeGuests:
    def __init__(self, guests: list[Guest] | Exception) -> None:
        self._guests = guests

    async def guests(self) -> list[Guest]:
        if isinstance(self._guests, Exception):
            raise self._guests
        return self._guests


async def health_of(guests: list[Guest] | Exception) -> ComponentHealth:
    return await GuestCheck(FakeGuests(guests)).check()


def expect(status: HealthStatus, message: str | None = None) -> ComponentHealth:
    return ComponentHealth(status=status, message=message)


OK = HealthStatus.OK
DEGRADED = HealthStatus.DEGRADED
DOWN = HealthStatus.DOWN


@pytest.mark.parametrize(
    ("guests", "expected"),
    [
        pytest.param([], expect(DOWN, "no guest has been built"), id="none"),
        pytest.param([guest("lab1", "ready")], expect(OK), id="one-ready"),
        pytest.param(
            [guest("lab1", "ready"), guest("lab2", "ready")], expect(OK), id="several-ready"
        ),
        pytest.param(
            [guest("lab1", "building")],
            expect(DOWN, "no guest is ready (lab1 is building)"),
            id="one-building",
        ),
        pytest.param(
            [guest("lab1", "failed"), guest("lab2", "testing")],
            expect(DOWN, "no guest is ready (lab1 is failed, lab2 is testing)"),
            id="none-ready-several-not",
        ),
        pytest.param(
            [guest("lab1", "ready"), guest("lab2", "failed"), guest("lab3", "building")],
            expect(DEGRADED, "lab2 is failed, lab3 is building"),
            id="one-ready-others-not",
        ),
        pytest.param(
            [guest("lab1", "ready"), guest("lab9", "broken")],
            expect(DEGRADED, "lab9 is broken"),
            id="broken-record",
        ),
    ],
)
async def test_the_guests_states_decide_the_health(
    guests: list[Guest], expected: ComponentHealth
) -> None:
    assert await health_of(guests) == expected


async def test_the_real_guest_list_is_ok() -> None:
    guests = [Guest.model_validate(record) for record in captured("guests.json")]

    assert await health_of(guests) == expect(OK)


async def test_a_control_service_that_cannot_be_reached_is_down() -> None:
    result = await health_of(GuestControlUnreachable("guests", "ConnectError"))

    assert result == expect(DOWN, "the guest control service is not reachable")


@pytest.mark.parametrize(
    "error",
    [
        GuestControlRejected("guests", 409, "the guest engine is not installed in this image yet"),
        GuestControlBadResponse("guests", "wrong shape"),
    ],
    ids=["rejected", "bad-response"],
)
async def test_a_control_service_that_answers_with_an_error_is_down(
    error: Exception,
) -> None:
    result = await health_of(error)

    assert result == expect(DOWN, "the guest control service answered with an error")
