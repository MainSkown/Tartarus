import asyncio
from typing import Any, cast

import pytest
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncEngine

from app.cape.errors import CapeUnreachable
from app.cape.models import CuckooStatus, Machine
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

GUEST_LABEL = "win"
GUEST = Machine(
    id=25,
    name=GUEST_LABEL,
    label=GUEST_LABEL,
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
        machines: list[Machine] | None = None,
        unreachable: bool = False,
    ) -> None:
        self.machines = [GUEST] if machines is None else machines
        self.unreachable = unreachable

    async def cuckoo_status(self) -> CuckooStatus:
        self._answer()
        return CUCKOO

    async def list_machines(self) -> list[Machine]:
        self._answer()
        return self.machines

    def _answer(self) -> None:
        if self.unreachable:
            raise CapeUnreachable("cuckoo/status", "ConnectError")


def cape_checks(cape: FakeCape) -> dict[str, HealthCheck]:
    checks = build_health_checks(
        cast(AsyncEngine, object()),
        cast(AsyncOpenSearch, FakeOpenSearch({"status": "green"})),
        cape,
        GUEST_LABEL,
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


async def test_cape_and_guest_are_ok_when_cape_answers_and_lists_the_guest() -> None:
    checks = cape_checks(FakeCape())

    assert await evaluate(checks["cape"], timeout_s=1) == ok
    assert await evaluate(checks["guest"], timeout_s=1) == ok


async def test_guest_is_degraded_when_cape_answers_but_does_not_list_the_guest() -> None:
    checks = cape_checks(FakeCape(machines=[]))

    assert await evaluate(checks["cape"], timeout_s=1) == ok
    guest = await evaluate(checks["guest"], timeout_s=1)
    assert guest.status is HealthStatus.DEGRADED
    assert guest.message == f"CAPE does not list a guest named {GUEST_LABEL}"


async def test_cape_and_guest_are_both_down_when_cape_is_unreachable() -> None:
    checks = cape_checks(FakeCape(unreachable=True))

    cape = await evaluate(checks["cape"], timeout_s=1)
    guest = await evaluate(checks["guest"], timeout_s=1)
    assert cape == ComponentHealth(status=HealthStatus.DOWN, message="CAPE is unreachable")
    assert guest == cape


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
