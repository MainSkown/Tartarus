import asyncio
from typing import Any, cast

import pytest
from opensearchpy import AsyncOpenSearch

from app.health import (
    ComponentHealth,
    HealthCheck,
    HealthStatus,
    NotConfiguredCheck,
    OpenSearchCheck,
    collect_health,
    evaluate,
)


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
        "guest": NotConfiguredCheck(),
    }

    health = await collect_health(checks, timeout_s=1)

    assert health.postgres == ok
    assert health.opensearch == degraded
    assert health.cape.status is HealthStatus.DOWN
    assert health.guest.status is HealthStatus.DOWN


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


async def test_not_configured_check_reports_down_not_set_up_yet() -> None:
    result = await evaluate(NotConfiguredCheck(), timeout_s=1)

    assert result == ComponentHealth(status=HealthStatus.DOWN, message="not set up yet")


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
