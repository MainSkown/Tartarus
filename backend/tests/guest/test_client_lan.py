import httpx
import pytest

from app.guest.errors import (
    GuestControlBadResponse,
    GuestControlNotConfigured,
    GuestControlRejected,
    GuestControlUnreachable,
)
from app.guest.lan_schemas import LanHealth
from tests.guest.test_client import CONTROL_URL, control_with, json_response, serving

PRESETS = {
    "presets": [
        {
            "id": "small-office",
            "name": "Small office",
            "description": "A domain controller and a file server",
            "hosts": [
                {
                    "fqdn": "dc01.corp.example",
                    "address": "192.168.150.200",
                    "role": "domain-controller",
                    "services": [{"kind": "smb", "port": 445}, {"kind": "ldap", "port": 389}],
                }
            ],
        }
    ]
}


async def test_lan_presets_get_the_list_and_parse_the_hosts() -> None:
    control = serving("GET", "/lan-presets", json_response(PRESETS))

    presets = await control_with(control).lan_presets()

    (preset,) = presets
    assert (preset.id, preset.name) == ("small-office", "Small office")
    (host,) = preset.hosts
    assert (host.fqdn, host.address, host.role) == (
        "dc01.corp.example",
        "192.168.150.200",
        "domain-controller",
    )
    assert [(service.kind, service.port) for service in host.services] == [
        ("smb", 445),
        ("ldap", 389),
    ]
    assert str(control.only_request.url) == f"{CONTROL_URL}/lan-presets"


async def test_lan_presets_in_another_shape_are_a_bad_response() -> None:
    control = serving("GET", "/lan-presets", json_response({"presets": "none"}))

    with pytest.raises(GuestControlBadResponse):
        await control_with(control).lan_presets()


@pytest.mark.parametrize(
    "answer", [{"ready": True, "reason": None}, {"ready": False, "reason": "the daemon is down"}]
)
async def test_lan_health_reads_ready_and_the_reason(answer: dict[str, object]) -> None:
    control = serving("GET", "/lan/health", json_response(answer))

    health = await control_with(control).lan_health()

    assert health == LanHealth(**answer)  # type: ignore[arg-type]


async def test_lan_sessions_lists_the_open_keys() -> None:
    control = serving("GET", "/lan/sessions", json_response({"keys": ["analysis-4", "other"]}))

    assert await control_with(control).lan_sessions() == ["analysis-4", "other"]


async def test_open_lan_session_posts_the_key_the_guest_and_the_preset() -> None:
    control = serving("POST", "/lan/sessions", json_response({"key": "analysis-4"}, 201))

    await control_with(control).open_lan_session("analysis-4", "win", "small-office")

    request = control.only_request
    assert request.headers["Authorization"].startswith("Bearer ")
    assert request.read() == b'{"key":"analysis-4","guest":"win","preset":"small-office"}'


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "no preset named x"),
        (409, "a session for win is already open"),
        (503, "the fake hosts cannot start: the daemon did not answer"),
    ],
)
async def test_open_lan_session_keeps_the_refusal_with_its_words(status: int, message: str) -> None:
    control = serving("POST", "/lan/sessions", json_response({"error": message}, status))

    with pytest.raises(GuestControlRejected) as refused:
        await control_with(control).open_lan_session("analysis-4", "win", "small-office")

    assert (refused.value.status, refused.value.message) == (status, message)


async def test_open_lan_session_without_a_confirmed_key_is_a_bad_response() -> None:
    control = serving("POST", "/lan/sessions", json_response({"key": "another"}, 201))

    with pytest.raises(GuestControlBadResponse):
        await control_with(control).open_lan_session("analysis-4", "win", "small-office")


async def test_close_lan_session_with_a_task_asks_for_the_log_to_be_copied() -> None:
    control = serving("DELETE", "/lan/sessions/analysis-4", json_response({"copied": True}))

    copied = await control_with(control).close_lan_session("analysis-4", task_id=77)

    assert copied is True
    assert control.only_request.url.params["task_id"] == "77"


async def test_close_lan_session_without_a_task_sends_no_task_id() -> None:
    control = serving("DELETE", "/lan/sessions/analysis-4", json_response({"copied": False}))

    copied = await control_with(control).close_lan_session("analysis-4")

    assert copied is False
    assert "task_id" not in control.only_request.url.params


@pytest.mark.parametrize(
    "call",
    [
        lambda control: control.lan_presets(),
        lambda control: control.lan_health(),
        lambda control: control.lan_sessions(),
        lambda control: control.open_lan_session("analysis-4", "win", "small-office"),
        lambda control: control.close_lan_session("analysis-4"),
    ],
)
async def test_every_lan_call_fails_closed_without_a_token_or_with_the_service_down(call) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(GuestControlNotConfigured):
        await call(control_with(lambda _: httpx.Response(200), token=None))

    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(GuestControlUnreachable):
        await call(control_with(down))
