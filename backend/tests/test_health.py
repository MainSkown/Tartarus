import asyncio
from typing import Any, cast

import pytest
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncEngine

from app.cape.errors import CapeUnreachable
from app.cape.models import CuckooStatus
from app.guest.errors import GuestControlUnreachable
from app.guest.schemas import Guest
from app.health import (
    ComponentHealth,
    HealthCheck,
    HealthStatus,
    OpenSearchCheck,
    collect_health,
    evaluate,
)
from app.main import build_health_checks


class FixedCheck:
    def __init__(self, result: ComponentHealth) -> None:
        self.result = result

    async def check(self) -> ComponentHealth:
        return self.result


class RaisingCheck:
    async def check(self) -> ComponentHealth:
        raise ConnectionRefusedError("secret-host:5432")


class HangingCheck:
    async def check(self) -> ComponentHealth:
        await asyncio.sleep(60)
        raise AssertionError("evaluate must cancel a hanging check")


class FakeClusterApi:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.response = response

    async def health(self) -> dict[str, Any]:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeOpenSearch:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.cluster = FakeClusterApi(response)


def opensearch_check(response: dict[str, Any] | Exception) -> OpenSearchCheck:
    return OpenSearchCheck(cast(AsyncOpenSearch, FakeOpenSearch(response)))


ok = ComponentHealth(status=HealthStatus.OK)

CUCKOO = CuckooStatus.model_validate(
    {
        "version": "2.5",
        "machines": {"total": 1, "available": 1},
        "tasks": {"pending": 0, "running": 0, "completed": 0, "reported": 6},
    }
)


class FakeCape:
    def __init__(self, unreachable: bool = False) -> None:
        self.unreachable = unreachable

    async def cuckoo_status(self) -> CuckooStatus:
        if self.unreachable:
            raise CapeUnreachable("cuckoo/status", "ConnectError")
        return CUCKOO


class FakeGuestControl:
    def __init__(self, guests: list[Guest] | None = None, unreachable: bool = False) -> None:
        self.guests_listed = [Guest(name="lab1", state="ready")] if guests is None else guests
        self.unreachable = unreachable

    async def guests(self) -> list[Guest]:
        if self.unreachable:
            raise GuestControlUnreachable("guests", "ConnectError")
        return self.guests_listed


def component_checks(cape: FakeCape, guests: FakeGuestControl) -> dict[str, HealthCheck]:
    checks = build_health_checks(
        cast(AsyncEngine, object()),
        cast(AsyncOpenSearch, FakeOpenSearch({"status": "green"})),
        cape,
        guests,
    )
    return {name: checks[name] for name in ("cape", "guest")}


async def test_evaluate_returns_the_result_of_a_healthy_check() -> None:
    assert await evaluate(FixedCheck(ok), timeout_s=1) == ok


async def test_evaluate_reports_a_raising_check_as_down_with_a_message() -> None:
    result = await evaluate(RaisingCheck(), timeout_s=1)

    assert result.status is HealthStatus.DOWN
    assert result.message == "check failed: ConnectionRefusedError"


async def test_evaluate_does_not_leak_exception_details() -> None:
    result = await evaluate(RaisingCheck(), timeout_s=1)

    assert "secret-host" not in (result.message or "")


async def test_evaluate_reports_a_check_exceeding_its_timeout_as_down() -> None:
    result = await evaluate(HangingCheck(), timeout_s=0.05)

    assert result.status is HealthStatus.DOWN
    assert result.message == "timed out after 0.05s"


async def test_collect_health_aggregates_each_component_result() -> None:
    degraded = ComponentHealth(status=HealthStatus.DEGRADED, message="cluster is red")
    checks: dict[str, HealthCheck] = {
        "postgres": FixedCheck(ok),
        "opensearch": FixedCheck(degraded),
        "cape": RaisingCheck(),
        "guest": FixedCheck(ok),
    }

    health = await collect_health(checks, timeout_s=1)

    assert health.postgres == ok
    assert health.opensearch == degraded
    assert health.cape.status is HealthStatus.DOWN
    assert health.guest == ok


async def test_collect_health_runs_checks_concurrently() -> None:
    checks: dict[str, HealthCheck] = {
        "postgres": HangingCheck(),
        "opensearch": HangingCheck(),
        "cape": HangingCheck(),
        "guest": HangingCheck(),
    }

    loop = asyncio.get_running_loop()
    started = loop.time()
    await collect_health(checks, timeout_s=0.2)

    assert loop.time() - started < 0.6


async def test_cape_and_guest_are_ok_when_cape_answers_and_a_guest_is_ready() -> None:
    checks = component_checks(FakeCape(), FakeGuestControl())

    assert await evaluate(checks["cape"], timeout_s=1) == ok
    assert await evaluate(checks["guest"], timeout_s=1) == ok


async def test_guest_is_down_with_a_reason_when_no_guest_has_been_built() -> None:
    checks = component_checks(FakeCape(), FakeGuestControl(guests=[]))

    assert await evaluate(checks["cape"], timeout_s=1) == ok
    assert await evaluate(checks["guest"], timeout_s=1) == ComponentHealth(
        status=HealthStatus.DOWN, message="no guest has been built"
    )


async def test_guest_health_does_not_depend_on_cape_being_reachable() -> None:
    checks = component_checks(FakeCape(unreachable=True), FakeGuestControl())

    cape = await evaluate(checks["cape"], timeout_s=1)
    assert cape == ComponentHealth(status=HealthStatus.DOWN, message="CAPE is unreachable")
    assert await evaluate(checks["guest"], timeout_s=1) == ok


async def test_guest_is_down_when_the_control_service_is_unreachable() -> None:
    checks = component_checks(FakeCape(), FakeGuestControl(unreachable=True))

    assert await evaluate(checks["guest"], timeout_s=1) == ComponentHealth(
        status=HealthStatus.DOWN, message="the guest control service is not reachable"
    )


@pytest.mark.parametrize("cluster_status", ["green", "yellow"])
async def test_opensearch_green_or_yellow_cluster_is_ok(cluster_status: str) -> None:
    # A single-node cluster is yellow as soon as an index has replicas; that is normal here.
    result = await opensearch_check({"status": cluster_status}).check()

    assert result == ok


async def test_opensearch_red_cluster_is_degraded() -> None:
    result = await opensearch_check({"status": "red"}).check()

    assert result.status is HealthStatus.DEGRADED
    assert result.message == "cluster status is red"


async def test_opensearch_unreachable_is_down() -> None:
    result = await evaluate(opensearch_check(ConnectionError("refused")), timeout_s=1)

    assert result.status is HealthStatus.DOWN
