"""Tests of the fake-LAN routes of `bin/guest-control`, in front of `lan_logic` (tested on its own
in test_lan_logic.py): paths, authentication, status codes and what reaches the service's log.

The service runs for real on a loopback port; the firewall, the daemon, the guests and the storage
are the fakes of test_lan_logic.py.
"""

import pytest
from test_control_http import AUTH, TOKEN, load_script, served
from test_guest_control import FakeEngine
from test_lan_logic import ADMIN_PASSWORD, SERVICE_PASSWORD, Stack

from guest_engine.media import CommandResult

guest_control = load_script("guest-control")

OPEN = {"key": "analysis-7", "guest": "lab1", "preset": "small-office"}


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path)


@pytest.fixture
def client(stack):
    handler = guest_control.make_handler(FakeEngine(), token=TOKEN, lan=stack.sessions)
    with served(handler) as started:
        yield started


def open_session(client, body=OPEN):
    return client.request("POST", "/lan/sessions", body=body, headers=AUTH)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/lan-presets"),
        ("GET", "/lan/health"),
        ("GET", "/lan/sessions"),
        ("POST", "/lan/sessions"),
        ("DELETE", "/lan/sessions/analysis-7"),
    ],
)
def test_every_lan_route_needs_the_token(client, stack, method, path):
    reply = client.request(method, path)

    assert reply.status == 401
    assert stack.firewall.calls == []


def test_the_presets_are_listed(client):
    reply = client.request("GET", "/lan-presets", headers=AUTH)

    assert reply.status == 200
    assert [preset["id"] for preset in reply.json["presets"]] == ["small-office"]


def test_health_answers_ready_and_why_not(client, stack):
    stack.beat(age=None)

    reply = client.request("GET", "/lan/health", headers=AUTH)

    assert reply.status == 200
    assert reply.json["ready"] is False
    assert isinstance(reply.json["reason"], str)


def test_opening_a_session_is_201_and_it_is_then_listed(client):
    reply = open_session(client)

    assert (reply.status, reply.json) == (201, {"key": "analysis-7"})
    assert client.request("GET", "/lan/sessions", headers=AUTH).json == {"keys": ["analysis-7"]}


def test_an_unknown_guest_is_404_with_an_error(client):
    reply = open_session(client, {**OPEN, "guest": "nobody"})

    assert reply.status == 404
    assert "error" in reply.json


def test_an_unknown_preset_is_404(client):
    assert open_session(client, {**OPEN, "preset": "nowhere"}).status == 404


def test_a_conflicting_session_is_409(client):
    open_session(client)

    assert open_session(client, {**OPEN, "key": "analysis-8"}).status == 409


def test_a_body_that_is_not_a_session_is_422_naming_the_fields(client):
    reply = open_session(client, {"key": "../x", "guest": 3})

    assert reply.status == 422
    assert sorted(reply.json["fields"]) == ["guest", "key", "preset"]


def test_a_daemon_that_fails_the_session_is_503_with_the_reason(client, stack):
    stack.daemon.opens = "failed"

    reply = open_session(client)

    assert (reply.status, reply.json) == (503, {"error": "port 445 is already in use"})


def test_closing_answers_copied_and_is_repeatable(client):
    open_session(client)

    first = client.request("DELETE", "/lan/sessions/analysis-7?task_id=7", headers=AUTH)
    second = client.request("DELETE", "/lan/sessions/analysis-7?task_id=7", headers=AUTH)

    assert (first.status, first.json) == (200, {"copied": True})
    assert (second.status, second.json) == (200, {"copied": False})


def test_closing_without_a_task_id_copies_nothing(client, stack):
    open_session(client)

    reply = client.request("DELETE", "/lan/sessions/analysis-7", headers=AUTH)

    assert (reply.status, reply.json) == (200, {"copied": False})
    assert not stack.events_file().exists()


def test_closing_an_unknown_key_is_200(client):
    reply = client.request("DELETE", "/lan/sessions/analysis-99", headers=AUTH)

    assert (reply.status, reply.json) == (200, {"copied": False})


def test_a_firewall_that_will_not_close_is_500_with_the_reason(client, stack):
    open_session(client)
    stack.firewall.fail["lan-close"] = CommandResult(1, "", "guest-firewall: lock busy")

    reply = client.request("DELETE", "/lan/sessions/analysis-7", headers=AUTH)

    assert reply.status == 500
    assert "lock busy" in reply.json["error"]


@pytest.mark.parametrize("path", ["/lan/sessions/-bad", "/lan/sessions/" + "a" * 65])
def test_a_key_that_is_not_one_is_400_and_nothing_runs(client, stack, path):
    assert client.request("DELETE", path, headers=AUTH).status == 400
    assert stack.firewall.calls == []


@pytest.mark.parametrize("task_id", ["abc", "", "-1", "1.5", "7a", "1" * 19])
def test_a_task_id_that_is_not_digits_is_400_and_nothing_runs(client, stack, task_id):
    reply = client.request("DELETE", f"/lan/sessions/analysis-7?task_id={task_id}", headers=AUTH)

    assert reply.status == 400
    assert stack.firewall.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [("PUT", "/lan/sessions"), ("DELETE", "/lan/sessions"), ("POST", "/lan/health")],
)
def test_the_routes_accept_only_their_method(client, method, path):
    assert client.request(method, path, headers=AUTH).status == 405


def test_no_reply_and_no_log_line_of_the_service_holds_a_password(client, stack, capsys):
    stack.daemon.opens = "failed"
    stack.daemon.failure = f"{ADMIN_PASSWORD} and {SERVICE_PASSWORD}"
    replies = [
        client.request("GET", "/lan-presets", headers=AUTH),
        client.request("GET", "/lan/health", headers=AUTH),
        open_session(client),
        client.request("GET", "/lan/sessions", headers=AUTH),
        client.request("DELETE", "/lan/sessions/analysis-7?task_id=7", headers=AUTH),
    ]

    said = "".join(reply.raw.decode() for reply in replies) + "".join(capsys.readouterr())
    assert ADMIN_PASSWORD not in said
    assert SERVICE_PASSWORD not in said
    assert "analysis-7" in said


def test_starting_the_service_closes_no_session(stack):
    stack.open()
    calls_before = list(stack.firewall.calls)

    guest_control.make_handler(FakeEngine(), token=TOKEN, lan=stack.sessions)

    assert stack.firewall.calls == calls_before
    assert stack.layout.session_file("analysis-7").exists()
