from app.cape.errors import CapeAuthError, CapeNotConfigured, CapeRejected, CapeUnreachable
from app.cape.health import CapeCheck
from app.cape.models import CuckooStatus
from app.health import HealthStatus

CUCKOO = CuckooStatus.model_validate(
    {
        "version": "2.5",
        "machines": {"total": 1, "available": 1},
        "tasks": {"pending": 0, "running": 0, "completed": 0, "reported": 6},
    }
)


class FakeCape:
    def __init__(self, status: CuckooStatus | Exception = CUCKOO) -> None:
        self.status = status

    async def cuckoo_status(self) -> CuckooStatus:
        if isinstance(self.status, Exception):
            raise self.status
        return self.status


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
