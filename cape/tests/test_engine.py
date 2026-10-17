import inspect
import json
import re
import time

import pytest
from fixtures.engine_lab import FAKE, PASSWORD, TOKEN, Lab, params

from guest_engine import protocol
from guest_engine.engine import Engine, create_engine
from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


def fail_the_disk_check(lab, name="alpha"):
    (lab.dir(name)).mkdir(parents=True, exist_ok=True)
    (lab.dir(name) / "break").write_text("")


# --- what the engine offers --------------------------------------------------------------


def test_the_engine_implements_exactly_the_guest_engine_protocol(lab):
    for name, member in inspect.getmembers(protocol.GuestEngine, inspect.isfunction):
        if name.startswith("_"):
            continue
        implemented = getattr(Engine, name)
        assert list(inspect.signature(implemented).parameters) == list(
            inspect.signature(member).parameters
        ), name


def test_the_installed_profiles_are_listed_with_their_option_schema(lab):
    [profile] = lab.engine.profiles()

    assert (profile["id"], profile["display_name"]) == ("fake", "Fake OS")
    assert {option["key"] for option in profile["options"]} == {"pause", "slow", "token"}
    assert profile["badges"] == [{"option": "pause", "value": True, "label": "PAUSES"}]
    assert profile["identity"]["account"]["pattern"]


def test_a_profile_listing_never_carries_the_adoption_password(lab):
    [profile] = lab.engine.profiles()

    assert "adoption" not in profile
    assert "Adopted-pass-1" not in json.dumps(lab.engine.profiles())


def test_media_lists_what_a_profiles_inspector_recognised(lab):
    [entry] = lab.engine.media()

    assert (entry["file"], entry["profile"], entry["kind"]) == ("disc.fake", "fake", "installer")
    assert [v["name"] for v in entry["variants"]] == ["Basic", "Plus"]


def test_a_file_no_inspector_recognises_is_listed_with_why(lab):
    (lab.media_dir / "notes.txt").write_text("hello")

    entries = {entry["file"]: entry for entry in lab.engine.media()}

    assert entries["notes.txt"]["profile"] is None
    assert entries["notes.txt"]["error"]


def test_a_profile_that_fails_to_load_is_skipped_and_the_others_work(tmp_path):
    profiles = tmp_path / "profiles"
    broken = profiles / "broken"
    broken.mkdir(parents=True)
    (broken / "profile.json").write_text("{not json")
    for source in (FAKE / "profiles" / "fake").rglob("*"):
        target = profiles / "fake" / source.relative_to(FAKE / "profiles" / "fake")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            target.write_bytes(source.read_bytes())
            target.chmod(source.stat().st_mode)

    lab = Lab(tmp_path, profiles_dir=profiles)

    assert [profile["id"] for profile in lab.engine.profiles()] == ["fake"]


# --- a build -----------------------------------------------------------------------------


def test_a_build_succeeds_and_leaves_the_guest_testing_and_registered(lab):
    started = lab.engine.start_build(params())
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", started)

    build = lab.settle(started)

    assert (build["status"], build["percent"], build["message"], build["pause"]) == (
        "succeeded",
        100,
        "",
        None,
    )
    assert build["guest"] == "alpha"
    assert build["kind"] == "build"
    assert [step["name"] for step in build["steps"]] == [
        "preflight",
        "define",
        "install",
        "verify-disk",
        "snapshot",
        "register",
    ]
    guest = lab.engine.guest("alpha")
    assert guest["state"] == "testing"
    assert guest["ip"] == "192.168.150.10"
    assert guest["profile"] == "fake"
    assert guest["media"]["file"] == "disc.fake"
    assert guest["build_id"] == started
    registration = (lab.registration_dir / "guests.conf").read_text()
    assert "machines = alpha" in registration
    assert "ip = 192.168.150.10" in registration
    assert lab.host.cape_restarts == 1
    assert lab.host.machines() == ["alpha"]


def test_the_requested_options_and_the_generated_identity_are_in_the_record(lab):
    lab.build(
        options={"token": TOKEN},
        identity={"password": PASSWORD},
        resources={"vcpus": 4, "ram_mb": 4096},
    )

    guest = json.loads((lab.dir() / "guest.json").read_text())

    assert guest["options"]["token"] == TOKEN
    assert guest["identity"]["password"] == PASSWORD
    assert re.fullmatch(r"[a-z]+", guest["identity"]["account"])
    assert (guest["resources"]["vcpus"], guest["resources"]["ram_mb"]) == (4, 4096)
    assert guest["state"] == "testing"


def test_the_second_guest_gets_the_next_address(lab):
    lab.build("alpha")

    lab.build("bravo")

    assert lab.engine.guest("bravo")["ip"] == "192.168.150.11"
    assert lab.host.machines() == ["alpha", "bravo"]


def test_a_conditional_step_runs_only_for_the_options_that_ask_for_it(lab):
    lab.build(options={"pause": False})
    paused = lab.engine.start_build(params("bravo", options={"pause": True}))
    lab.settle(paused)

    assert "ask" not in lab.ran("alpha")
    assert "ask" in lab.ran("bravo")


def test_the_context_file_hands_a_step_the_whole_guest_and_profile(lab):
    build_id = lab.build(identity={"password": PASSWORD})["id"]
    context = json.loads((lab.dir() / "builds" / build_id / "context.json").read_text())

    assert context["guest"]["name"] == "alpha"
    assert context["guest"]["media_kind"] == "installer"
    assert context["guest"]["identity"]["password"] == PASSWORD
    assert context["profile"]["id"] == "fake"
    assert "adoption" not in context["profile"]
    assert context["source"] is None
    assert context["build"] == {
        "id": build_id,
        "kind": "build",
        "steps": [s["name"] for s in lab.engine.build(build_id)["steps"]],
    }
    assert context["host"]["subnet"] == "192.168.150.0/24"
    assert context["host"]["gateway"] == "192.168.150.1"
    assert context["host"]["libvirt_dir"] == str(lab.libvirt_dir)
    assert (lab.dir() / "builds" / build_id / "context.json").stat().st_mode & 0o077 == 0


def test_a_build_of_a_medium_the_scan_cannot_type_does_not_start(lab, monkeypatch):
    scanned = lab.engine.media()
    untyped = [{key: value for key, value in entry.items() if key != "kind"} for entry in scanned]
    monkeypatch.setattr(lab.engine, "media", lambda: untyped)

    with pytest.raises(InvalidParameters) as refused:
        lab.engine.start_build(params())

    assert "kind" in refused.value.fields["media.file"]
    assert lab.engine.guests() == []


def test_a_request_that_is_wrong_is_refused_and_nothing_is_created(lab):
    with pytest.raises(InvalidParameters) as refused:
        lab.engine.start_build(params(media={"file": "ghost.fake"}))

    assert "media.file" in refused.value.fields
    assert lab.engine.guests() == []
    assert list(lab.root.glob("*")) == []


def test_a_name_in_use_is_refused(lab):
    lab.build()

    with pytest.raises(InvalidParameters) as refused:
        lab.engine.start_build(params())

    assert "name" in refused.value.fields


def test_the_build_log_has_the_steps_output_and_tails(lab):
    build_id = lab.build()["id"]

    log = lab.engine.build_log(build_id, 1000)

    assert "== step preflight" in log
    assert "LOG enough room for everything" in log
    assert lab.engine.build_log(build_id, 2) == log[-2:]


def test_an_unknown_build_is_not_found_everywhere(lab):
    for call in (
        lambda: lab.engine.build("bnothing"),
        lambda: lab.engine.build_log("bnothing", 5),
        lambda: lab.engine.resume("bnothing"),
        lambda: lab.engine.restart("bnothing"),
        lambda: lab.engine.cancel("bnothing"),
        lambda: lab.engine.continue_after_pause("bnothing"),
        lambda: lab.engine.complete_build("bnothing", True, {}),
    ):
        with pytest.raises(GuestNotFound):
            call()


# --- failing, resuming, restarting ---------------------------------------------------------


def test_a_failing_step_fails_the_build_and_the_guest_and_registers_nothing(lab):
    fail_the_disk_check(lab)

    build = lab.build()

    assert build["status"] == "failed"
    assert "the disk image is corrupt" in build["message"]
    assert "verify-disk" in build["message"]
    assert lab.engine.guest("alpha")["state"] == "failed"
    assert lab.host.cape_restarts == 0
    assert lab.dir().is_dir()


def test_resume_after_the_fix_continues_from_the_step_that_failed(lab):
    fail_the_disk_check(lab)
    build_id = lab.build()["id"]
    (lab.dir() / "break").unlink()

    lab.engine.resume(build_id)
    build = lab.settle(build_id)

    assert build["status"] == "succeeded"
    assert lab.ran() == ["define", "install", "verify-disk", "verify-disk", "snapshot"]
    assert lab.engine.guest("alpha")["state"] == "testing"
    assert lab.host.machines() == ["alpha"]


def test_resuming_puts_the_guest_back_to_building_while_it_runs(lab):
    fail_the_disk_check(lab)
    build_id = lab.build()["id"]
    states = []
    original = lab.engine._registry.update_state

    def record(name, state):
        states.append(state)
        return original(name, state)

    lab.engine._registry.update_state = record
    (lab.dir() / "break").unlink()

    lab.engine.resume(build_id)
    lab.settle(build_id)

    assert states[0] == "building"
    assert states[-1] == "testing"


def test_restart_runs_every_step_again_from_the_first(lab):
    fail_the_disk_check(lab)
    build_id = lab.build()["id"]
    (lab.dir() / "break").unlink()

    lab.engine.restart(build_id)
    lab.settle(build_id)

    assert lab.ran().count("define") == 2
    assert lab.engine.build(build_id)["status"] == "succeeded"


def test_resume_needs_a_failed_or_paused_build(lab):
    build_id = lab.build()["id"]

    with pytest.raises(Conflict, match="succeeded"):
        lab.engine.resume(build_id)


def test_a_step_past_its_timeout_fails_the_build_naming_it(lab):
    build = lab.build(options={"slow": True})

    assert build["status"] == "failed"
    assert "hang" in build["message"]
    assert "timed out" in build["message"]
    assert lab.engine.guest("alpha")["state"] == "failed"


def test_cape_that_will_not_list_the_guest_fails_the_build_and_resume_registers_it(lab):
    lab.host.cape_fails = True
    build_id = lab.build()["id"]
    failed = lab.engine.build(build_id)

    assert failed["status"] == "failed"
    assert "spawn error" in failed["message"]
    assert lab.engine.guest("alpha")["state"] == "failed"

    lab.host.cape_fails = False
    lab.engine.resume(build_id)
    lab.settle(build_id)

    assert lab.engine.guest("alpha")["state"] == "testing"
    assert lab.host.machines() == ["alpha"]
    assert lab.ran().count("define") == 1


# --- cancelling ----------------------------------------------------------------------------


def test_cancelling_a_running_build_fails_the_guest_and_lets_it_be_deleted(lab):
    started = lab.engine.start_build(params(options={"slow": True}))
    wait_until(lambda: (lab.dir() / "defined").exists() and _running(lab, started, "hang"))

    lab.engine.cancel(started)

    build = lab.engine.build(started)
    assert (build["status"], build["message"]) == ("failed", "the build was cancelled")
    assert lab.engine.guest("alpha")["state"] == "failed"
    assert lab.host.machines() == []
    lab.engine.delete_guest("alpha")
    assert lab.engine.guests() == []


def test_a_cancelled_build_can_be_resumed(lab):
    started = lab.engine.start_build(params(options={"slow": True}))
    wait_until(lambda: (lab.dir() / "defined").exists() and _running(lab, started, "hang"))
    lab.engine.cancel(started)
    (lab.dir() / "release").write_text("")

    lab.engine.resume(started)

    assert lab.settle(started)["status"] == "succeeded"


def test_cancelling_a_paused_clone_fails_the_new_guest_and_registers_only_its_source(lab):
    lab.engine.complete_build(lab.build("alpha")["id"], True, {"ok": True})
    source_record = (lab.dir("alpha") / "guest.json").read_bytes()
    clone = lab.engine.start_clone("alpha", {"name": "bravo", "options": {"pause": True}})
    assert lab.settle(clone)["status"] == "paused"

    lab.engine.cancel(clone)

    assert lab.engine.build(clone)["message"] == "the build was cancelled"
    assert lab.engine.guest("bravo")["state"] == "failed"
    assert lab.engine.guest("alpha")["state"] == "ready"
    assert lab.host.machines() == ["alpha"]
    assert (lab.dir("alpha") / "guest.json").read_bytes() == source_record
    lab.engine.delete_guest("bravo")
    assert [guest["name"] for guest in lab.engine.guests()] == ["alpha"]


def test_a_build_that_is_not_running_or_paused_cannot_be_cancelled(lab):
    build_id = lab.build()["id"]

    with pytest.raises(Conflict, match="succeeded, not running or paused"):
        lab.engine.cancel(build_id)


# --- pause ---------------------------------------------------------------------------------


def test_a_step_that_asks_for_the_user_pauses_the_build_with_the_desktop_on(lab):
    build = lab.build(options={"pause": True})

    assert build["status"] == "paused"
    assert build["pause"] == {
        "instructions": "Press the green button on the desktop, then continue"
    }
    assert build["desktop"] is True
    assert lab.engine.guest("alpha")["state"] == "building"
    assert lab.host.cape_restarts == 0


def test_continue_reruns_the_paused_step_and_carries_on(lab):
    build_id = lab.build(options={"pause": True})["id"]

    lab.engine.continue_after_pause(build_id)
    build = lab.settle(build_id)

    assert build["status"] == "succeeded"
    assert build["pause"] is None
    assert lab.engine.guest("alpha")["state"] == "testing"


def test_the_desktop_is_offered_only_while_a_desktop_step_is_running_or_paused(lab):
    build = lab.build()

    assert build["desktop"] is False


# --- one at a time ------------------------------------------------------------------------


def test_only_one_build_or_clone_is_active_and_the_refusal_names_it(lab):
    lab.build("alpha", options={"pause": True})

    with pytest.raises(Conflict, match="alpha"):
        lab.engine.start_build(params("bravo"))
    with pytest.raises(Conflict, match="alpha"):
        lab.engine.start_clone("alpha", {"name": "charlie"})

    assert [guest["name"] for guest in lab.engine.guests()] == ["alpha"]


def test_a_busy_engine_says_so_before_it_looks_at_the_request(lab):
    lab.build("alpha", options={"pause": True})

    with pytest.raises(Conflict, match="alpha"):
        lab.engine.start_build({"name": "not a valid name"})
    with pytest.raises(Conflict, match="alpha"):
        lab.engine.start_clone("ghost", {"name": "x"})


def test_resume_is_refused_while_another_build_is_active(lab):
    fail_the_disk_check(lab)
    failed = lab.build("alpha")["id"]
    lab.build("bravo", options={"pause": True})
    (lab.dir() / "break").unlink()

    with pytest.raises(Conflict, match="bravo"):
        lab.engine.resume(failed)


# --- the service was killed ---------------------------------------------------------------


def make_running(lab, build_id, name="alpha"):
    path = lab.dir(name) / "builds" / build_id / "build.json"
    data = json.loads(path.read_text())
    data["status"] = "running"
    data["step"] = 3
    for step in data["steps"][3:]:
        step.update(status="pending", finished=None, exit_code=None)
    data["steps"][3].update(status="running", started="2026-10-15T12:00:00Z")
    path.write_text(json.dumps(data))
    guest = json.loads((lab.dir(name) / "guest.json").read_text())
    guest["state"] = "building"
    (lab.dir(name) / "guest.json").write_text(json.dumps(guest))
    return data


def test_a_build_left_running_when_the_service_died_is_failed_at_the_next_start(lab):
    build_id = lab.build()["id"]
    make_running(lab, build_id)
    (lab.dir() / "ran").unlink()

    engine = lab.restarted()

    build = engine.build(build_id)
    assert build["status"] == "failed"
    assert build["message"] == (
        "the control service restarted while this step was running; resume it"
    )
    assert build["steps"][3]["status"] == "failed"
    assert engine.guest("alpha")["state"] == "failed"


def test_the_interrupted_build_can_then_be_resumed(lab):
    build_id = lab.build()["id"]
    make_running(lab, build_id)
    engine = lab.restarted()

    engine.resume(build_id)
    build = lab.settle(build_id)

    assert build["status"] == "succeeded"
    assert engine.guest("alpha")["state"] == "testing"


def test_a_paused_build_survives_the_restart_and_can_be_continued(lab):
    build_id = lab.build(options={"pause": True})["id"]
    engine = lab.restarted()

    assert engine.build(build_id)["status"] == "paused"
    engine.continue_after_pause(build_id)
    assert lab.settle(build_id)["status"] == "succeeded"


# --- the service is stopped ----------------------------------------------------------------


def test_stopping_the_engine_stops_the_running_step_and_leaves_the_build_resumable(lab):
    started = lab.engine.start_build(params(options={"slow": True}))
    wait_until(lambda: (lab.dir() / "defined").exists() and _running(lab, started, "hang"))

    lab.engine.shutdown()

    build = lab.engine.build(started)
    assert build["status"] == "failed"
    assert build["message"] == (
        "the control service was stopped while this step was running; resume it"
    )
    assert lab.engine.guest("alpha")["state"] == "failed"
    (lab.dir() / "release").write_text("")
    revived = lab.restarted()
    revived.resume(started)
    assert lab.settle(started)["status"] == "succeeded"


def test_stopping_an_idle_engine_is_safe_and_can_be_repeated(lab):
    lab.build()

    lab.engine.shutdown()
    lab.engine.shutdown()

    assert lab.engine.build(lab.engine.guest("alpha")["build_id"])["status"] == "succeeded"


def test_a_stopped_engine_starts_no_build(lab):
    lab.engine.shutdown()

    with pytest.raises(Conflict, match="stopping"):
        lab.engine.start_build(params())
    assert lab.engine.guests() == []


# --- the self-test verdict ---------------------------------------------------------------


def test_a_passed_self_test_makes_the_guest_ready_and_keeps_it_registered(lab):
    build_id = lab.build()["id"]
    verdict = {"analysis": "a-1", "signals": {"events.process": True}}

    lab.engine.complete_build(build_id, True, verdict)

    guest = lab.engine.guest("alpha")
    assert guest["state"] == "ready"
    assert guest["selftest"] == verdict
    assert lab.host.machines() == ["alpha"]
    assert lab.host.cape_restarts == 1


def test_a_failed_self_test_fails_and_unregisters_the_guest_but_keeps_its_files(lab):
    keep = lab.build("keep")["id"]
    lab.engine.complete_build(keep, True, {})
    build_id = lab.build("alpha")["id"]

    lab.engine.complete_build(build_id, False, {"message": "no DNS answer"})

    guest = lab.engine.guest("alpha")
    assert guest["state"] == "failed"
    assert guest["selftest"] == {"message": "no DNS answer"}
    assert lab.host.machines() == ["keep"]
    assert (lab.dir() / "guest.json").is_file()
    assert (lab.dir() / "snapshotted").is_file()
    assert lab.engine.guest("keep")["state"] == "ready"


def test_the_verdict_is_idempotent_for_the_same_answer(lab):
    build_id = lab.build()["id"]
    lab.engine.complete_build(build_id, True, {"n": 1})

    lab.engine.complete_build(build_id, True, {"n": 1})

    assert lab.engine.guest("alpha")["state"] == "ready"
    assert lab.host.cape_restarts == 1


def test_a_contradicting_second_verdict_is_refused(lab):
    build_id = lab.build()["id"]
    lab.engine.complete_build(build_id, True, {})

    with pytest.raises(Conflict, match="ready"):
        lab.engine.complete_build(build_id, False, {})


def test_a_verdict_for_a_build_that_has_not_finished_is_refused(lab):
    build_id = lab.build(options={"pause": True})["id"]

    with pytest.raises(Conflict, match="paused"):
        lab.engine.complete_build(build_id, True, {})

    assert lab.engine.guest("alpha")["state"] == "building"


def test_a_passed_verdict_registers_a_guest_that_the_pipeline_left_unregistered(lab):
    build_id = lab.build()["id"]
    lab.host.listed = []
    (lab.registration_dir / "guests.conf").unlink()

    lab.engine.complete_build(build_id, True, {})

    assert lab.host.machines() == ["alpha"]
    assert lab.engine.guest("alpha")["state"] == "ready"


# --- reading guests ---------------------------------------------------------------------


def test_guests_are_listed_with_their_badges_and_the_latest_build(lab):
    build_id = lab.build(options={"pause": True})["id"]

    [guest] = lab.engine.guests()

    assert guest["name"] == "alpha"
    assert guest["badges"] == ["PAUSES"]
    assert guest["build_id"] == build_id


def test_an_unknown_guest_is_not_found(lab):
    for call in (
        lambda: lab.engine.guest("ghost"),
        lambda: lab.engine.guest_address("ghost"),
        lambda: lab.engine.delete_guest("ghost"),
        lambda: lab.engine.check("ghost"),
        lambda: lab.engine.display("ghost"),
    ):
        with pytest.raises(GuestNotFound):
            call()


def test_a_guest_record_that_cannot_be_read_is_listed_as_broken(lab):
    lab.build("alpha")
    lab.build("bravo")
    (lab.dir("bravo") / "guest.json").write_text("{broken")

    listed = {guest["name"]: guest for guest in lab.engine.guests()}

    assert listed["alpha"]["state"] == "testing"
    assert listed["bravo"]["state"] == "broken"
    assert "not valid JSON" in listed["bravo"]["error"]


def test_where_the_agent_of_a_guest_is_comes_from_its_record_and_profile(lab):
    lab.build()

    assert lab.engine.guest_address("alpha") == {
        "ip": "192.168.150.10",
        "agent_port": 8000,
        "finish_dir": "/tmp",  # noqa: S108 - a path inside the guest
    }


def test_a_secret_option_is_masked_in_what_the_engine_reports(lab):
    lab.build(options={"token": TOKEN})

    assert lab.engine.guest("alpha")["options"]["token"] == "***"  # noqa: S105
    assert TOKEN not in json.dumps(lab.engine.guests())


def test_a_secret_option_that_is_empty_stays_empty(lab):
    lab.build()

    assert lab.engine.guest("alpha")["options"]["token"] == ""


def test_the_display_of_a_running_guest_is_its_vnc_address(lab):
    lab.build()
    assert lab.engine.display("alpha") is None

    lab.host.running.add("alpha")

    assert lab.engine.display("alpha") == {"host": "127.0.0.1", "port": 5901}


# --- health checks -------------------------------------------------------------------------


def test_the_health_checks_of_a_registered_guest_all_pass(lab):
    lab.build()

    answer = lab.engine.check("alpha")

    assert answer["name"] == "alpha"
    assert {check["id"]: check["ok"] for check in answer["checks"]} == {
        "domain": True,
        "snapshot": True,
        "registration": True,
        "agent": True,
    }


def test_checks_are_refused_while_a_build_is_active(lab):
    lab.build("alpha")
    lab.build("bravo", options={"pause": True})

    with pytest.raises(Conflict, match="bravo"):
        lab.engine.check("alpha")


def test_the_agent_check_is_the_injected_one(tmp_path):
    seen = []

    def agent(guest, profile):
        seen.append((guest.name, profile.id))
        return False, "no answer"

    lab = Lab(tmp_path, agent_check=agent)
    lab.build()

    answer = lab.engine.check("alpha")

    assert seen == [("alpha", "fake")]
    assert {c["id"]: c["message"] for c in answer["checks"]}["agent"] == "no answer"


# --- deleting -----------------------------------------------------------------------------


def test_deleting_a_guest_unregisters_it_before_undefining_and_removes_everything(lab):
    lab.build("alpha")
    lab.build("bravo")
    lab.host.create_files("alpha")
    cape_before = lab.host.cape_restarts

    lab.engine.delete_guest("alpha")

    assert lab.host.machines() == ["bravo"]
    assert lab.host.cape_restarts == cape_before + 1
    assert lab.host.undefined == ["alpha"]
    assert lab.host.listed_when_undefined["alpha"] == ["bravo"]
    assert not lab.dir("alpha").exists()
    assert not any(path.exists() for path in lab.host.files_of("alpha"))
    assert lab.host.outside_file.exists()
    assert lab.engine.guest("bravo")["state"] == "testing"
    with pytest.raises(GuestNotFound):
        lab.engine.guest("alpha")


def test_the_registration_is_rewritten_without_the_deleted_guest(lab):
    lab.build("alpha")
    lab.build("bravo")

    lab.engine.delete_guest("alpha")

    registration = (lab.registration_dir / "guests.conf").read_text()
    assert "[bravo]" in registration
    assert "alpha" not in registration


def test_a_running_vm_is_stopped_before_it_is_undefined(lab):
    lab.build()
    lab.host.running.add("alpha")

    lab.engine.delete_guest("alpha")

    assert lab.host.events.index("destroy alpha") < lab.host.events.index("undefine alpha")


def test_a_guest_whose_build_failed_before_any_vm_existed_can_be_deleted(lab):
    lab.engine.start_build(params(options={"slow": True}))
    lab.engine.wait(lab.engine.guest("alpha")["build_id"], timeout=30)
    (lab.dir() / "defined").unlink()

    lab.engine.delete_guest("alpha")

    assert not lab.dir().exists()
    assert lab.host.undefined == []


def wait_until(condition, seconds=20):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.02)


def test_a_guest_is_not_deleted_while_its_build_runs(lab):
    started = lab.engine.start_build(params(options={"slow": True}))
    wait_until(lambda: (lab.dir() / "defined").exists() and _running(lab, started, "hang"))

    with pytest.raises(Conflict, match="running"):
        lab.engine.delete_guest("alpha")
    (lab.dir() / "release").write_text("")
    lab.settle(started)

    assert lab.dir().exists()


def _running(lab, build_id, step_name):
    steps = {step["name"]: step for step in lab.engine.build(build_id)["steps"]}
    return steps[step_name]["status"] == "running"


def test_a_paused_builds_guest_can_be_deleted_to_abandon_the_build(lab):
    lab.build(options={"pause": True})

    lab.engine.delete_guest("alpha")

    assert lab.engine.guests() == []
    lab.build("bravo")  # the slot of the abandoned build is free again


def test_a_guest_cannot_be_deleted_while_a_clone_of_it_is_being_made(lab):
    lab.engine.complete_build(lab.build("alpha")["id"], True, {})
    clone = lab.engine.start_clone("alpha", {"name": "bravo", "options": {"pause": True}})
    lab.settle(clone)

    with pytest.raises(Conflict, match="bravo"):
        lab.engine.delete_guest("alpha")


def test_a_failed_unregistration_leaves_the_guest_completely_alone(lab):
    lab.build()
    lab.host.create_files("alpha")
    lab.host.cape_fails = True

    with pytest.raises(Conflict, match="unregister"):
        lab.engine.delete_guest("alpha")

    assert lab.dir().exists()
    assert lab.host.undefined == []
    assert all(path.exists() for path in lab.host.files_of("alpha"))


def test_files_outside_the_libvirt_folder_and_the_media_are_never_deleted(lab):
    lab.build()
    lab.host.create_files("alpha")

    lab.engine.delete_guest("alpha")

    assert lab.host.outside_file.exists()
    assert (lab.media_dir / "disc.fake").exists()


def files_a_build_lays_down(lab, name):
    images, nvram = lab.libvirt_dir / "images", lab.libvirt_dir / "nvram"
    return [
        images / f"{name}.qcow2",
        images / f"{name}-clean.mem",
        images / f"{name}-clean.qcow2",
        nvram / f"{name}_VARS.fd",
    ]


def test_the_files_a_build_left_are_removed_when_its_domain_is_already_gone(lab):
    lab.build("alpha")
    lab.host.create_files("alpha")
    (lab.dir() / "defined").unlink()  # a restart's preflight undefines the domain before define

    lab.engine.delete_guest("alpha")

    assert not lab.dir().exists()
    assert not any(path.exists() for path in files_a_build_lays_down(lab, "alpha"))
    assert lab.host.outside_file.exists()


def test_deleting_a_guest_never_removes_the_files_of_a_guest_whose_name_it_starts(lab):
    lab.build("alpha")
    lab.build("alpha2")
    lab.host.create_files("alpha2")
    (lab.dir("alpha") / "defined").unlink()

    lab.engine.delete_guest("alpha")

    assert all(path.exists() for path in files_a_build_lays_down(lab, "alpha2"))


# --- cloning ----------------------------------------------------------------------------


def ready_alpha(lab):
    lab.engine.complete_build(lab.build("alpha")["id"], True, {"ok": True})


def test_a_clone_runs_the_clone_pipeline_and_ends_testing_beside_its_source(lab):
    ready_alpha(lab)
    source_record = (lab.dir("alpha") / "guest.json").read_bytes()

    build_id = lab.engine.start_clone("alpha", {"name": "bravo"})
    build = lab.settle(build_id)

    assert build["status"] == "succeeded"
    assert build["kind"] == "clone"
    assert [step["name"] for step in build["steps"]] == [
        "preflight",
        "copy",
        "define",
        "reconfigure",
        "verify-disk",
        "snapshot",
        "register",
    ]
    clone = lab.engine.guest("bravo")
    assert (clone["state"], clone["kind"], clone["cloned_from"]) == ("testing", "clone", "alpha")
    assert clone["ip"] == "192.168.150.11"
    assert clone["machine"]["mac"] != lab.engine.guest("alpha")["machine"]["mac"]
    assert clone["identity"]["account"] == lab.engine.guest("alpha")["identity"]["account"]
    assert lab.host.machines() == ["alpha", "bravo"]
    assert (lab.dir("alpha") / "guest.json").read_bytes() == source_record


def test_a_clone_step_is_given_the_source_in_its_context(lab):
    ready_alpha(lab)

    build_id = lab.engine.start_clone("alpha", {"name": "bravo"})
    lab.settle(build_id)
    context = json.loads((lab.dir("bravo") / "builds" / build_id / "context.json").read_text())

    assert context["source"]["name"] == "alpha"
    assert context["guest"]["cloned_from"] == "alpha"
    assert context["guest"]["media_kind"] == "installer"
    assert (lab.dir("bravo") / "context-seen").read_text().strip() == '"cloned_from": "alpha"'


def test_a_clone_can_change_what_the_profile_allows(lab):
    ready_alpha(lab)

    lab.settle(lab.engine.start_clone("alpha", {"name": "bravo", "options": {"pause": True}}))

    assert lab.engine.guest("bravo")["options"]["pause"] is True
    assert lab.engine.build(lab.engine.guest("bravo")["build_id"])["status"] == "paused"


def test_a_clone_that_changes_what_it_may_not_is_refused(lab):
    ready_alpha(lab)

    with pytest.raises(InvalidParameters) as refused:
        lab.engine.start_clone("alpha", {"name": "bravo", "options": {"slow": True}})

    assert "options.slow" in refused.value.fields


def test_only_a_ready_guest_can_be_cloned(lab):
    lab.build("alpha")

    with pytest.raises(Conflict, match="testing"):
        lab.engine.start_clone("alpha", {"name": "bravo"})
    with pytest.raises(GuestNotFound):
        lab.engine.start_clone("ghost", {"name": "bravo"})


def test_a_clone_that_fails_leaves_the_source_ready_and_registered_and_itself_failed(lab):
    ready_alpha(lab)
    fail_the_disk_check(lab, "bravo")
    source_record = (lab.dir("alpha") / "guest.json").read_bytes()

    build = lab.settle(lab.engine.start_clone("alpha", {"name": "bravo"}))

    assert build["status"] == "failed"
    assert "verify-disk" in build["message"]
    assert lab.engine.guest("bravo")["state"] == "failed"
    assert lab.engine.guest("alpha")["state"] == "ready"
    assert lab.host.machines() == ["alpha"]
    assert (lab.dir("alpha") / "guest.json").read_bytes() == source_record


def test_resuming_a_clone_whose_source_was_deleted_meanwhile_fails_with_that_reason(lab):
    ready_alpha(lab)
    fail_the_disk_check(lab, "bravo")
    build_id = lab.engine.start_clone("alpha", {"name": "bravo"})
    lab.settle(build_id)
    lab.engine.delete_guest("alpha")
    (lab.dir("bravo") / "break").unlink()

    lab.engine.resume(build_id)
    build = lab.settle(build_id)

    assert build["status"] == "failed"
    assert build["message"] == "the source guest alpha no longer exists"


def test_a_build_that_cannot_be_started_leaves_no_guest_behind(lab, monkeypatch):
    def refuse(*_arguments, **_keywords):
        raise OSError("disk full")

    monkeypatch.setattr(lab.engine._sequencer, "begin", refuse)

    with pytest.raises(OSError, match="disk full"):
        lab.engine.start_build(params())

    assert lab.engine.guests() == []
    assert not lab.dir().exists()


# --- secrets ----------------------------------------------------------------------------


def test_the_guests_secrets_are_in_no_log_message_or_reply(lab):
    build_id = lab.build(options={"token": TOKEN}, identity={"password": PASSWORD})["id"]

    log = lab.engine.build_log(build_id, 1000)
    log_file = (lab.dir() / "builds" / build_id / "log").read_text()

    assert any("account=" in line for line in log)
    assert not any(PASSWORD in line or TOKEN in line for line in log)
    assert PASSWORD not in log_file
    assert TOKEN not in log_file
    assert PASSWORD not in json.dumps(lab.engine.build(build_id))
    assert TOKEN not in json.dumps(lab.engine.build(build_id))
    assert "password=***" in log_file


def test_everything_the_engine_returns_is_plain_json(lab):
    build_id = lab.build()["id"]
    lab.engine.complete_build(build_id, True, {"a": [1, 2]})

    for value in (
        lab.engine.profiles(),
        lab.engine.media(),
        lab.engine.guests(),
        lab.engine.guest("alpha"),
        lab.engine.build(build_id),
        lab.engine.build_log(build_id, 5),
        lab.engine.check("alpha"),
        lab.engine.guest_address("alpha"),
    ):
        assert json.loads(json.dumps(value)) == value


# --- the start of the service --------------------------------------------------------------


def test_stale_loop_mounts_are_cleaned_once_when_the_engine_is_created(tmp_path):
    (tmp_path / "scan").mkdir()

    lab = Lab(tmp_path)

    assert lab.host.calls.count(["findmnt", "-rno", "TARGET,SOURCE"]) == 1


def test_the_create_function_works_with_no_arguments_when_nothing_is_installed(
    tmp_path, monkeypatch
):
    for variable in (
        "GUEST_REGISTRY_DIR",
        "GUEST_MEDIA_DIR",
        "GUEST_PROFILES_DIR",
        "GUEST_STEPS_DIR",
        "GUEST_REGISTRATION_DIR",
    ):
        monkeypatch.setenv(variable, str(tmp_path / variable.lower()))

    engine = create_engine()

    assert engine.profiles() == []
    assert engine.guests() == []
    assert engine.media() == []
