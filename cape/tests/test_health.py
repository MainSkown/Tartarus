import json

import pytest
from fixtures.fake_host import SNAPSHOT, FakeHost, failure
from fixtures.guest_samples import make_guest
from fixtures.profile_samples import sample_profile

from guest_engine.health import (
    CapeMachinesProbe,
    SnapshotAgentCheck,
    labels_from_machines_list,
    run_checks,
)
from guest_engine.host import Host


@pytest.fixture
def world(tmp_path):
    fake = FakeHost(tmp_path / "lib", tmp_path / "guests", tmp_path / "conf.d")
    (tmp_path / "guests" / "alpha").mkdir(parents=True)
    return fake


def define(world, snapshot=True):
    (world.guests_root / "alpha" / "defined").write_text("")
    if snapshot:
        (world.guests_root / "alpha" / "snapshotted").write_text("")


def checks_of(answer):
    return {check["id"]: check for check in answer["checks"]}


PROFILE = sample_profile("windows")
GUEST = make_guest("alpha", "192.168.150.10", state="ready")


def run(world, *, listed=("alpha",), agent=lambda *_: (True, "agent ok")):
    return run_checks(GUEST, PROFILE, Host(world, "qemu:///system"), lambda: list(listed), agent)


# --- the four checks ---------------------------------------------------------------------


def test_a_healthy_guest_passes_all_four_checks(world):
    define(world)

    answer = run(world)

    assert answer["name"] == "alpha"
    assert [c["id"] for c in answer["checks"]] == ["domain", "snapshot", "registration", "agent"]
    assert all(c["ok"] for c in answer["checks"])
    assert all(c["message"] for c in answer["checks"])


def test_a_missing_vm_fails_the_domain_check_and_skips_what_needs_it(world):
    checks = checks_of(run(world))

    assert not checks["domain"]["ok"]
    assert "alpha" in checks["domain"]["message"]
    assert not checks["snapshot"]["ok"]
    assert not checks["agent"]["ok"]
    assert "skipped" in checks["agent"]["message"]


def test_a_missing_snapshot_fails_its_check_and_skips_the_agent(world):
    define(world, snapshot=False)
    asked = []

    checks = checks_of(run(world, agent=lambda *a: asked.append(a) or (True, "")))

    assert checks["domain"]["ok"]
    assert not checks["snapshot"]["ok"]
    assert SNAPSHOT in checks["snapshot"]["message"]
    assert not checks["agent"]["ok"]
    assert asked == []


def test_a_guest_cape_does_not_list_fails_the_registration_check_only(world):
    define(world)

    checks = checks_of(run(world, listed=("other",)))

    assert not checks["registration"]["ok"]
    assert "alpha" in checks["registration"]["message"]
    assert checks["domain"]["ok"]
    assert checks["agent"]["ok"]


def test_cape_being_unreachable_fails_the_registration_check_with_the_reason(world):
    define(world)

    def down():
        raise OSError("connection refused")

    answer = run_checks(
        GUEST, PROFILE, Host(world, "qemu:///system"), down, lambda *_: (True, "agent ok")
    )

    registration = checks_of(answer)["registration"]
    assert not registration["ok"]
    assert "connection refused" in registration["message"]


def test_the_agents_own_answer_is_the_agent_checks_message(world):
    define(world)

    checks = checks_of(run(world, agent=lambda *_: (False, "no answer at 192.168.150.10:8000")))

    assert not checks["agent"]["ok"]
    assert checks["agent"]["message"] == "no answer at 192.168.150.10:8000"


def test_the_agent_check_receives_the_guest_and_its_profile(world):
    define(world)
    received = []

    run(world, agent=lambda guest, profile: received.append((guest.name, profile.id)) or (True, ""))

    assert received == [("alpha", "windows")]


# --- reaching the agent after a revert ---------------------------------------------------


def agent_check(world, statuses, timeout_s=20):
    answers = iter(statuses)
    slept = []
    check = SnapshotAgentCheck(
        Host(world, "qemu:///system"),
        status_of=lambda _url: next(answers),
        sleep=slept.append,
        timeout_s=timeout_s,
        poll_s=5,
    )
    return check, slept


def test_the_snapshot_is_restored_the_agent_polled_and_the_vm_stopped_again(world):
    define(world)
    check, slept = agent_check(world, [None, None, 200])

    ok, message = check(GUEST, PROFILE)

    assert ok
    assert "192.168.150.10" in message
    assert world.events == ["revert alpha", "destroy alpha"]
    assert slept == [5, 5]


def test_an_agent_that_never_answers_fails_after_the_timeout_and_still_stops_the_vm(world):
    define(world)
    check, slept = agent_check(world, [None] * 10, timeout_s=15)

    ok, message = check(GUEST, PROFILE)

    assert not ok
    assert "15 s" in message
    assert world.events == ["revert alpha", "destroy alpha"]
    assert len(slept) == 2  # three polls, one pause between each


def test_the_agent_is_asked_at_the_guests_address_and_the_profiles_port(world):
    define(world)
    urls = []
    check = SnapshotAgentCheck(
        Host(world, "qemu:///system"), status_of=lambda url: urls.append(url) or 200, sleep=print
    )

    check(GUEST, PROFILE)

    assert urls == ["http://192.168.150.10:8000/status"]


def test_a_failed_revert_is_reported_without_polling(world):
    define(world)
    world.running.clear()
    host = Host(
        lambda _args, _timeout=None: failure("error: snapshot is corrupt"), "qemu:///system"
    )
    polled = []
    check = SnapshotAgentCheck(host, status_of=lambda url: polled.append(url) or 200, sleep=print)

    ok, message = check(GUEST, PROFILE)

    assert not ok
    assert "revert" in message
    assert polled == []


# --- CAPE's machine list -----------------------------------------------------------------

LISTING = {
    "error": False,
    "data": [
        {"id": 58, "name": "win", "label": "win", "ip": "192.168.150.10", "locked": False},
        {"id": 59, "name": "win2", "label": "win2", "ip": "192.168.150.11", "locked": False},
    ],
}


def test_the_labels_come_from_the_data_list():
    assert labels_from_machines_list(LISTING) == ["win", "win2"]


@pytest.mark.parametrize(
    "payload", [{}, {"data": None}, {"data": "x"}, [], None, {"data": [1, {"name": "no-label"}]}]
)
def test_a_listing_of_another_shape_has_no_labels(payload):
    assert labels_from_machines_list(payload) == []


def test_the_probe_asks_machines_list_with_the_api_token():
    seen = {}

    def fetch(url, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return json.dumps(LISTING).encode()

    probe = CapeMachinesProbe("http://127.0.0.1:8000/", "secret-token", fetch=fetch)

    assert probe() == ["win", "win2"]
    assert seen["url"] == "http://127.0.0.1:8000/apiv2/machines/list/"
    assert seen["headers"] == {"Authorization": "Token secret-token"}
    assert seen["timeout"] > 0


def test_an_answer_that_is_not_json_is_an_error_the_caller_can_retry():
    probe = CapeMachinesProbe("http://x", "t", fetch=lambda *_: b"<html>502</html>")

    with pytest.raises(ValueError, match="JSON"):
        probe()
