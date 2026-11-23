import pytest

from app.api.lan import router as lan_router
from app.guest.errors import GuestControlRejected, GuestControlUnreachable
from tests.guest.fakes import FakeGuestControl
from tests.guest.harness import UNREACHABLE_MESSAGE, Harness


@pytest.fixture
def harness(harness: Harness) -> Harness:
    harness.app.include_router(lan_router, prefix="/api")
    return harness


async def test_the_presets_are_listed_with_their_hosts_and_services(harness: Harness) -> None:
    response = await harness.client.get("/api/lan-presets")

    assert response.status_code == 200
    (preset,) = response.json()
    assert (preset["id"], preset["name"]) == ("small-office", "Small office")
    assert preset["hosts"] == [
        {
            "fqdn": "dc01.corp.example",
            "address": "192.168.150.200",
            "role": "domain-controller",
            "services": [{"kind": "smb", "port": 445}],
        }
    ]
    assert harness.control.lan_calls() == [("lan_presets", None)]


async def test_no_preset_is_an_empty_list(harness: Harness) -> None:
    control = FakeGuestControl()
    control.lan_presets_listed = []
    harness.use(control)

    response = await harness.client.get("/api/lan-presets")

    assert response.json() == []


async def test_presets_while_the_control_service_is_down_are_a_502(harness: Harness) -> None:
    harness.use(FakeGuestControl(error=GuestControlUnreachable("lan_presets", "ConnectError")))

    response = await harness.client.get("/api/lan-presets")

    assert response.status_code == 502
    assert response.json()["error"]["message"] == UNREACHABLE_MESSAGE


async def test_a_refusal_of_the_control_service_is_not_passed_on_as_its_own_words(
    harness: Harness,
) -> None:
    harness.use(FakeGuestControl(error=GuestControlRejected("lan_presets", 500, "internals")))

    assert (await harness.client.get("/api/lan-presets")).status_code == 502


async def test_the_route_has_the_operation_id_the_client_is_generated_from(
    harness: Harness,
) -> None:
    operation = harness.app.openapi()["paths"]["/api/lan-presets"]["get"]

    assert operation["operationId"] == "lan_presets_list"
    assert operation["tags"] == ["lan"]
    assert operation["description"]
