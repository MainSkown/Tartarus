from app.cape.errors import CapeAuthError, CapeNotConfigured, CapeRejected, CapeUnreachable
from app.cape.health import CapeCheck, GuestCheck
from app.cape.models import CuckooStatus, Machine
from app.health import HealthStatus

GUEST = Machine(
    id=25,
    name="win",
    label="win",
    status="poweroff",
    locked=False,
    reserved=False,
    ip="192.168.150.10",
)
CUCKOO = CuckooStatus.model_validate(
    {
        "version": "2.5",
        "machines": {"total": 1, "available": 1},
        "tasks": {"pending": 0, "running": 0, "completed": 0, "reported": 6},
    }
)


class FakeCape:
    def __init__(
        self,
        machines: list[Machine] | Exception | None = None,
        status: CuckooStatus | Exception = CUCKOO,
    ) -> None:
        self.machines = [GUEST] if machines is None else machines
        self.status = status

    async def cuckoo_status(self) -> CuckooStatus:
        if isinstance(self.status, Exception):
            raise self.status
        return self.status

    async def list_machines(self) -> list[Machine]:
        if isinstance(self.machines, Exception):
            raise self.machines
        return self.machines


async def test_cape_check_is_ok_when_cuckoo_status_answers() -> None:
    result = await CapeCheck(FakeCape()).check()

    assert result.status is HealthStatus.OK


async def test_cape_check_is_down_when_cape_is_unreachable() -> None:
    result = await CapeCheck(
        FakeCape(status=CapeUnreachable("cuckoo/status", "ConnectError"))
    ).check()

    assert result.status is HealthStatus.DOWN
    assert result.message is not None
    assert "unreachable" in result.message.lower()


async def test_cape_check_is_down_and_says_so_when_the_token_is_refused() -> None:
    result = await CapeCheck(FakeCape(status=CapeAuthError("cuckoo/status"))).check()

    assert result.status is HealthStatus.DOWN
    assert result.message is not None
    assert "token" in result.message.lower()


async def test_cape_check_is_down_when_no_token_is_configured() -> None:
    result = await CapeCheck(FakeCape(status=CapeNotConfigured())).check()

    assert result.status is HealthStatus.DOWN
    assert result.message is not None
    assert "CAPE_API_TOKEN" in result.message


async def test_cape_check_is_down_when_cape_answers_with_an_error() -> None:
    result = await CapeCheck(FakeCape(status=CapeRejected("cuckoo/status", "Disabled"))).check()

    assert result.status is HealthStatus.DOWN


async def test_guest_check_is_ok_when_the_guest_is_listed_and_unlocked_even_if_powered_off() -> (
    None
):
    result = await GuestCheck(FakeCape(), "win").check()

    assert result.status is HealthStatus.OK


async def test_guest_check_is_degraded_when_the_label_is_not_listed() -> None:
    other = GUEST.model_copy(update={"label": "other", "name": "other"})

    result = await GuestCheck(FakeCape(machines=[other]), "win").check()

    assert result.status is HealthStatus.DEGRADED
    assert result.message is not None
    assert "win" in result.message


async def test_guest_check_is_degraded_when_no_machines_are_listed() -> None:
    result = await GuestCheck(FakeCape(machines=[]), "win").check()

    assert result.status is HealthStatus.DEGRADED


async def test_guest_check_is_ok_while_the_guest_is_busy_with_an_analysis() -> None:
    # A locked guest is running a task. That is healthy, and a new sample must still be accepted:
    # it waits in the queue.
    busy = GUEST.model_copy(update={"locked": True, "status": "running"})

    result = await GuestCheck(FakeCape(machines=[busy]), "win").check()

    assert result.status is HealthStatus.OK
    assert result.message is not None
    assert "busy" in result.message


async def test_guest_check_is_down_when_cape_is_unreachable() -> None:
    unreachable = CapeUnreachable("machines/list", "ConnectError")

    result = await GuestCheck(FakeCape(machines=unreachable), "win").check()

    assert result.status is HealthStatus.DOWN


async def test_guest_check_is_down_when_the_token_is_refused() -> None:
    result = await GuestCheck(FakeCape(machines=CapeAuthError("machines/list")), "win").check()

    assert result.status is HealthStatus.DOWN


async def test_guest_check_is_down_when_cape_answers_with_an_error() -> None:
    result = await GuestCheck(
        FakeCape(machines=CapeRejected("machines/list", "boom")), "win"
    ).check()

    assert result.status is HealthStatus.DOWN
