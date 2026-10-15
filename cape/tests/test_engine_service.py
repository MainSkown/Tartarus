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


def build_alpha(client):
    build_id = call(client, "POST", "/builds", params("alpha")).json["id"]
    wait_for(client, build_id, "succeeded")


def test_the_sample_and_the_checks_of_a_guest_come_through_http(service):
    lab, client = service
    build_alpha(client)
    (lab.dir() / "checks-output").write_text("FACT os.build=1\nPROOF defender=ok\n")

    sample = call(client, "GET", "/guests/alpha/selftest/sample")
    checks = call(client, "POST", "/guests/alpha/selftest/checks")

    assert sample.status == 200
    assert sample.raw.startswith(b"built from: ")
    assert sample.headers["x-filename"] == "benign"
    assert sample.headers["content-type"] == "application/octet-stream"
    assert checks.status == 200
    assert checks.json == {
        "facts": {"os.build": "1"},
        "giveaways": [],
        "proofs": {"defender": {"ok": True, "message": ""}},
        "log": [],
    }


def test_a_failed_sample_build_and_failed_checks_are_500_and_502_with_their_messages(service):
    lab, client = service
    build_alpha(client)
    lab.host.compiler_error = "benign.c:1: error: nothing"
    (lab.dir() / "checks-output").write_text("LOG the agent never answered\n")
    (lab.dir() / "checks-exit").write_text("1")

    sample = call(client, "GET", "/guests/alpha/selftest/sample")
    checks = call(client, "POST", "/guests/alpha/selftest/checks")

    assert sample.status == 500
    assert "error: nothing" in sample.json["error"]
    assert checks.status == 502
    assert "the agent never answered" in checks.json["error"]


def test_the_self_test_routes_refuse_an_unknown_guest_and_a_busy_service(service):
    _lab, client = service
    assert call(client, "GET", "/guests/ghost/selftest/sample").status == 404
    assert call(client, "POST", "/guests/ghost/selftest/checks").status == 404
    build_alpha(client)
    started = call(client, "POST", "/builds", params("bravo", options={"pause": True})).json["id"]
    wait_for(client, started, "paused")

    assert call(client, "POST", "/guests/alpha/selftest/checks").status == 409
