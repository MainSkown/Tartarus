"""The real engine behind the real control service: the routes, the status codes, the JSON."""

import time

import pytest
from fixtures.engine_lab import Lab, params
from test_control_http import AUTH, TOKEN, load_script, served

guest_control = load_script("guest-control")


@pytest.fixture
def service(tmp_path):
    lab = Lab(tmp_path)
    handler = guest_control.make_handler(lab.engine, token=TOKEN)
    with served(handler) as client:
        yield lab, client


def call(client, method, path, body=None):
    return client.request(method, path, body, AUTH)


def wait_for(client, build_id, status):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        build = call(client, "GET", f"/builds/{build_id}").json
        if build["status"] == status:
            return build
        time.sleep(0.05)
    raise AssertionError(f"build never became {status}")


def test_a_guest_is_built_checked_completed_and_deleted_through_http(service):
    lab, client = service
    assert call(client, "GET", "/profiles").json[0]["id"] == "fake"
    assert call(client, "GET", "/media").json[0]["file"] == "disc.fake"

    started = call(client, "POST", "/builds", params("alpha"))
    assert started.status == 202
    build_id = started.json["id"]
    build = wait_for(client, build_id, "succeeded")
    assert build["percent"] == 100

    assert call(client, "GET", "/guests/alpha").json["state"] == "testing"
    assert call(client, "GET", f"/builds/{build_id}/log?tail=3").json[-1].startswith("LOG")
    assert call(client, "POST", f"/builds/{build_id}/complete", {"passed": True}).status == 204
    assert [g["state"] for g in call(client, "GET", "/guests").json] == ["ready"]
    checks = call(client, "POST", "/guests/alpha/check").json["checks"]
    assert all(check["ok"] for check in checks)
    assert call(client, "GET", "/guests/alpha/display").status == 404

    assert call(client, "DELETE", "/guests/alpha").status == 204
    assert call(client, "GET", "/guests/alpha").status == 404
    assert lab.host.machines() == []


def test_the_engines_refusals_are_the_statuses_the_service_promises(service):
    _lab, client = service

    assert call(client, "POST", "/builds", params("alpha", options={"pause": 3})).status == 422
    first = call(client, "POST", "/builds", params("alpha", options={"pause": True})).json["id"]
    wait_for(client, first, "paused")
    assert call(client, "POST", "/builds", params("bravo")).status == 409
    assert call(client, "POST", f"/builds/{first}/continue").status == 202
    wait_for(client, first, "succeeded")
    assert call(client, "POST", f"/builds/{first}/restart").status == 409
    assert call(client, "POST", "/guests/ghost/clone", {"name": "x"}).status == 404
    assert call(client, "GET", "/builds/bnothing").status == 404
