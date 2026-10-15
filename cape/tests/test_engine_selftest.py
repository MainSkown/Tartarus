"""The engine's two self-test calls: the profile's sample, and the checks run inside a guest."""

import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from fixtures.engine_lab import FAKE, PASSWORD, Lab, params

from guest_engine.errors import Conflict, GuestNotFound
from guest_engine.selftest import ChecksFailed, SampleBuildFailed

SOURCE = FAKE / "profiles" / "fake" / "selftest" / "benign.c"


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


def wait_until(condition, seconds=20):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.02)


def edited_profile_lab(tmp_path, edit):
    """A lab whose only profile is the fake one after `edit(profile_json)`."""
    profiles = tmp_path / "edited-profiles"
    shutil.copytree(FAKE / "profiles", profiles)
    file = profiles / "fake" / "profile.json"
    data = json.loads(file.read_text())
    edit(data)
    file.write_text(json.dumps(data))
    return Lab(tmp_path, profiles_dir=profiles)


# --- the sample ----------------------------------------------------------------------------


def test_the_sample_of_a_guest_is_built_from_its_profiles_source_and_cached(lab):
    lab.build()

    sample = lab.engine.selftest_sample("alpha")

    assert sample["filename"] == "benign"
    path = Path(sample["path"])
    assert path == lab.libvirt_dir / "tartarus" / "cache" / "selftest" / "fake" / "benign"
    assert path.read_bytes() == b"built from: " + SOURCE.read_bytes()


def test_the_build_command_gets_the_profiles_source_file_and_a_scratch_output(lab):
    lab.build()

    lab.engine.selftest_sample("alpha")

    [call] = [call for call in lab.host.calls if call[0] == "fake-cc"]
    assert call[1] == str(SOURCE)
    assert (
        Path(call[3]).parent.parent == lab.libvirt_dir / "tartarus" / "cache" / "selftest" / "fake"
    )


def test_an_unchanged_sample_is_built_only_once(lab):
    lab.build()

    first = lab.engine.selftest_sample("alpha")
    second = lab.engine.selftest_sample("alpha")

    assert first == second
    assert len([call for call in lab.host.calls if call[0] == "fake-cc"]) == 1


def test_the_sample_of_an_unknown_guest_is_not_found(lab):
    with pytest.raises(GuestNotFound):
        lab.engine.selftest_sample("ghost")


def test_a_failed_sample_build_raises_with_the_compilers_message(lab):
    lab.build()
    lab.host.compiler_error = "benign.c:3: error: expected ';'"

    with pytest.raises(SampleBuildFailed, match="expected ';'"):
        lab.engine.selftest_sample("alpha")


def test_a_profile_that_defines_no_sample_is_a_conflict(tmp_path):
    lab = edited_profile_lab(tmp_path, lambda data: data["selftest"].pop("sample"))
    lab.build()

    with pytest.raises(Conflict, match="no self-test sample"):
        lab.engine.selftest_sample("alpha")


# --- the checks ----------------------------------------------------------------------------


def checks_output(lab, *lines, name="alpha", code=0):
    (lab.dir(name) / "checks-output").write_text("\n".join(lines) + "\n")
    (lab.dir(name) / "checks-exit").write_text(str(code))


def test_the_checks_report_what_the_profiles_step_printed(lab):
    lab.build()
    checks_output(
        lab,
        "FACT system.model=Fake PC",
        "GIVEAWAY service: Fake agent",
        "PROOF defender=ok",
        "LOG done",
    )

    report = lab.engine.selftest_checks("alpha")

    assert report == {
        "facts": {"system.model": "Fake PC"},
        "giveaways": ["service: Fake agent"],
        "proofs": {"defender": {"ok": True, "message": ""}},
        "log": ["done"],
    }


def test_a_guest_that_passed_its_self_test_can_be_checked_again(lab):
    build_id = lab.build()["id"]
    lab.engine.complete_build(build_id, True, {"passed": True})
    checks_output(lab, "PROOF defender=ok")

    assert lab.engine.selftest_checks("alpha")["proofs"]["defender"]["ok"] is True


def test_the_step_runs_with_the_environment_of_a_build_step_for_a_folder_of_its_own(lab):
    lab.build()
    checks_output(lab, "FACT a=1")

    lab.engine.selftest_checks("alpha")

    environment = dict(
        line.split("=", 1) for line in (lab.dir() / "checks-env").read_text().splitlines()
    )
    build_dir = Path(environment["TT_BUILD_DIR"])
    assert build_dir.parent == lab.dir() / "checks"
    assert build_dir.name == "2026-10-15T12:00:00Z"
    assert environment["TT_STEP"] == "selftest-checks"
    assert environment["TT_GUEST_DIR"] == str(lab.dir())
    assert environment["TT_GUEST_JSON"] == str(lab.dir() / "guest.json")
    assert environment["TT_CONTEXT_JSON"] == str(build_dir / "context.json")
    assert environment["TT_STATE_FILE"] == str(build_dir / "build.json")
    assert environment["TT_LOG"] == str(build_dir / "log")
    assert environment["TT_BUILD_ID"] == "checks-2026-10-15T12:00:00Z"
    assert environment["TT_PROFILE_DIR"] == str(FAKE / "profiles" / "fake")
    assert (build_dir / "log").read_text() == "FACT a=1\n"


def test_the_context_file_describes_the_guest_like_a_builds_does(lab):
    lab.build(identity={"password": PASSWORD})
    checks_output(lab)

    lab.engine.selftest_checks("alpha")

    [checks_dir] = (lab.dir() / "checks").iterdir()
    context = json.loads((checks_dir / "context.json").read_text())
    assert context["guest"]["name"] == "alpha"
    assert context["guest"]["ip"] == "192.168.150.10"
    assert context["profile"]["id"] == "fake"
    assert context["host"]["libvirt_uri"]
    assert context["build"]["kind"] == "checks"
    assert context["source"] is None
    assert (checks_dir / "context.json").stat().st_mode & 0o077 == 0


def test_running_the_checks_leaves_no_build_record_and_the_guest_untouched(lab):
    build = lab.build()
    before = (lab.dir() / "guest.json").read_bytes()
    builds_before = sorted(path.name for path in (lab.dir() / "builds").iterdir())
    checks_output(lab, "FACT a=1")

    lab.engine.selftest_checks("alpha")

    assert (lab.dir() / "guest.json").read_bytes() == before
    assert sorted(path.name for path in (lab.dir() / "builds").iterdir()) == builds_before
    assert lab.engine.guest("alpha")["state"] == "testing"
    assert lab.engine.guest("alpha")["build_id"] == build["id"]


def test_the_guests_password_never_reaches_the_report(lab):
    lab.build(identity={"password": PASSWORD})
    checks_output(
        lab, f"FACT leaked={PASSWORD}", f"PROOF p=failed saw {PASSWORD}", f"LOG {PASSWORD}"
    )

    report = lab.engine.selftest_checks("alpha")

    assert PASSWORD not in json.dumps(report)
    assert report["facts"] == {"leaked": "***"}


def test_a_line_from_the_guest_that_looks_like_a_proof_is_only_log(lab):
    lab.build()
    checks_output(lab, "LOG PROOF defender=ok", "PROOF eicar=failed")

    report = lab.engine.selftest_checks("alpha")

    assert report["proofs"] == {"eicar": {"ok": False, "message": ""}}
    assert report["log"] == ["PROOF defender=ok"]


@pytest.mark.parametrize("code", [1, 75])
def test_a_step_that_fails_makes_the_checks_fail_with_the_end_of_its_log(lab, code):
    lab.build()
    checks_output(lab, "LOG the agent never answered", code=code)

    with pytest.raises(ChecksFailed, match=rf"(?s)exit code {code}.*the agent never answered"):
        lab.engine.selftest_checks("alpha")


def test_a_step_past_the_time_limit_fails_the_checks(tmp_path):
    lab = Lab(tmp_path, selftest_check_timeout_s=1)
    lab.build()
    (lab.dir() / "checks-hold").write_text("")

    with pytest.raises(ChecksFailed, match="timed out after 1 s"):
        lab.engine.selftest_checks("alpha")


def test_checks_that_failed_leave_the_guest_switched_off_even_if_the_step_was_killed(tmp_path):
    lab = Lab(tmp_path, selftest_check_timeout_s=1)
    lab.build()
    (lab.dir() / "checks-hold").write_text("")
    lab.host.events.clear()

    with pytest.raises(ChecksFailed):
        lab.engine.selftest_checks("alpha")

    assert lab.host.events == ["destroy alpha"]


def test_checks_that_worked_do_not_touch_the_domain_themselves(lab):
    lab.build()
    lab.host.events.clear()

    lab.engine.selftest_checks("alpha")

    assert lab.host.events == []


def test_the_unknown_guest_is_not_found(lab):
    with pytest.raises(GuestNotFound):
        lab.engine.selftest_checks("ghost")


def test_a_guest_that_is_still_building_is_refused_with_its_state(lab):
    started = lab.engine.start_build(params(options={"slow": True}))
    wait_until(lambda: lab.engine.guest("alpha")["state"] == "building")

    with pytest.raises(Conflict):
        lab.engine.selftest_checks("alpha")

    (lab.dir() / "release").write_text("")
    lab.settle(started)


def test_a_failed_guest_is_refused_and_the_message_says_its_state(lab):
    (lab.dir()).mkdir(parents=True, exist_ok=True)
    (lab.dir() / "break").write_text("")
    lab.build()

    with pytest.raises(Conflict, match=r"failed.*testing or ready"):
        lab.engine.selftest_checks("alpha")


def test_checks_are_refused_while_another_guest_builds(lab):
    lab.build("alpha")
    started = lab.engine.start_build(params("bravo", options={"slow": True}))
    wait_until(lambda: lab.engine.guest("bravo")["state"] == "building")

    with pytest.raises(Conflict, match="build of bravo"):
        lab.engine.selftest_checks("alpha")

    (lab.dir("bravo") / "release").write_text("")
    lab.settle(started)


def test_a_profile_without_a_check_step_has_nothing_to_check(tmp_path):
    lab = edited_profile_lab(tmp_path, lambda data: data["selftest"].update(check_step=None))
    lab.build()

    assert lab.engine.selftest_checks("alpha") == {
        "facts": {},
        "giveaways": [],
        "proofs": {},
        "log": [],
    }
    assert not (lab.dir() / "checks").exists()


# --- while the checks run, nothing else does ---------------------------------------------------


@pytest.fixture
def checking(lab):
    """A lab whose guest alpha is being checked by a step that waits to be released."""
    lab.build()
    lab.build("bravo")
    (lab.dir() / "checks-hold").write_text("")
    outcome: dict = {}

    def run():
        try:
            outcome["report"] = lab.engine.selftest_checks("alpha")
        except Exception as error:  # noqa: BLE001 - handed to the test
            outcome["error"] = error

    worker = threading.Thread(target=run)
    worker.start()
    wait_until((lab.dir() / "checks-env").exists)
    yield lab, outcome
    (lab.dir() / "release").write_text("")
    worker.join(20)


def test_a_second_run_of_the_checks_is_refused_meanwhile(checking):
    lab, _ = checking

    with pytest.raises(Conflict, match="self-test checks of alpha"):
        lab.engine.selftest_checks("bravo")


def test_a_build_and_a_clone_are_refused_meanwhile(checking):
    lab, _ = checking

    with pytest.raises(Conflict, match="self-test checks of alpha"):
        lab.engine.start_build(params("charlie"))
    with pytest.raises(Conflict, match="self-test checks of alpha"):
        lab.engine.start_clone("bravo", {"name": "charlie"})


def test_a_health_check_and_a_deletion_are_refused_meanwhile(checking):
    lab, _ = checking

    with pytest.raises(Conflict, match="self-test checks of alpha"):
        lab.engine.check("bravo")
    with pytest.raises(Conflict, match="self-test checks of alpha"):
        lab.engine.delete_guest("bravo")


def test_the_slot_is_free_again_once_the_checks_ended(lab):
    lab.build()
    checks_output(lab, code=1)
    with pytest.raises(ChecksFailed):
        lab.engine.selftest_checks("alpha")

    assert lab.settle(lab.engine.start_build(params("bravo")))["status"] == "succeeded"


def test_stopping_the_engine_stops_the_step_the_checks_run(lab):
    lab.build()
    (lab.dir() / "checks-hold").write_text("")
    outcome: dict = {}

    def run():
        try:
            lab.engine.selftest_checks("alpha")
        except ChecksFailed as error:
            outcome["error"] = error

    worker = threading.Thread(target=run)
    worker.start()
    wait_until((lab.dir() / "checks-env").exists)

    lab.engine.shutdown()
    worker.join(20)

    assert "service was stopped" in str(outcome["error"])
