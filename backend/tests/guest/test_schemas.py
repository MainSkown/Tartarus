from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.guest.schemas import (
    BuildStatus,
    Guest,
    GuestProfile,
    HealthCheckResult,
    MediaEntry,
)
from tests.guest.conftest import captured

GUESTS = TypeAdapter(list[Guest])
PROFILES = TypeAdapter(list[GuestProfile])
MEDIA = TypeAdapter(list[MediaEntry])


def test_the_real_guest_list_parses_with_win_lab1_and_lab2() -> None:
    guests = {guest.name: guest for guest in GUESTS.validate_python(captured("guests.json"))}

    assert list(guests) == ["win", "lab1", "lab2"]
    assert {guest.state for guest in guests.values()} == {"ready"}
    assert guests["win"].adopted is True
    assert guests["win"].build_id is None
    assert guests["lab2"].cloned_from == "lab1"
    assert guests["lab2"].badges == ["DEFENDER OFF"]


def test_a_guest_carries_everything_the_card_renders() -> None:
    lab1 = GUESTS.validate_python(captured("guests.json"))[1]

    assert lab1.identity is not None
    assert (lab1.identity.account, lab1.identity.machine) == ("Alice", "LAPTOP-LJZ4UEE")
    assert lab1.resources is not None
    assert (lab1.resources.vcpus, lab1.resources.ram_mb, lab1.resources.disk_gb) == (2, 4096, 80)
    assert lab1.media is not None
    assert (lab1.media.file, lab1.media.language) == ("Win11_25H2_Polish_x64_v2.iso", "pl-PL")
    assert lab1.machine is not None
    assert lab1.machine.mac == "00:14:22:8d:44:27"
    assert (lab1.ip, lab1.snapshot, lab1.work_dir) == (
        "192.168.150.11",
        "tartarus-clean",
        "C:\\ProgramData\\wrchynkw",
    )
    assert lab1.options["sysmon"] is True
    assert lab1.selftest == {"by": "guest-build CLI, no analysis was run"}
    assert lab1.giveaways == []


def test_the_giveaways_of_the_adopted_guest_are_kept() -> None:
    win = GUESTS.validate_python(captured("guests.json"))[0]

    assert "work_dir 'C:\\tartarus' contains 'tartarus'" in win.giveaways


def test_a_broken_record_is_a_guest_with_only_a_name_a_state_and_an_error() -> None:
    broken = Guest.model_validate(captured("guest_broken.json"))

    assert (broken.name, broken.state) == ("lab9", "broken")
    assert broken.error == "guest.json is not valid JSON"
    assert broken.identity is None
    assert broken.resources is None
    assert broken.badges == []


def test_a_guest_in_an_unknown_state_is_refused() -> None:
    with pytest.raises(ValidationError):
        Guest.model_validate({"name": "lab1", "state": "sleeping"})


def test_fields_the_control_service_may_grow_are_ignored() -> None:
    record: dict[str, Any] = {**captured("guest_lab2.json"), "region": "somewhere"}

    guest = Guest.model_validate(record)

    assert guest.name == "lab2"
    assert not hasattr(guest, "region")


def test_the_real_profile_parses_with_the_rules_the_gui_renders_from() -> None:
    (windows,) = PROFILES.validate_python(captured("profiles.json"))

    assert (windows.id, windows.display_name, windows.family) == (
        "windows",
        "Windows 11",
        "windows",
    )
    assert [option.key for option in windows.options] == [
        "defender",
        "decoys",
        "sysmon",
        "key",
        "keyboard",
    ]
    defender = windows.options[0]
    assert (defender.type, defender.default, defender.changeable_on_clone) == ("bool", True, True)
    keyboard = windows.options[4]
    assert keyboard.type == "choice"
    assert "Polish (Programmers)" in keyboard.choices
    assert windows.identity.account.pattern == "[A-Za-z][A-Za-z0-9_-]{0,19}"
    assert "Administrator" in windows.identity.account.reserved
    assert windows.identity.machine.generator == "computer_name"
    assert [badge.label for badge in windows.badges] == ["DEFENDER ON", "DEFENDER OFF"]
    assert windows.badges[1].value is False
    assert "exe" in windows.packages
    assert windows.resources.min_disk_gb == 64
    assert windows.media.kinds == ["installer"]
    assert windows.agent.interactive.options == "interactive=1,nohuman=yes"
    assert windows.clone.computer_name_editable is True


def test_the_real_media_answer_lists_the_editions_of_the_iso() -> None:
    (iso,) = MEDIA.validate_python(captured("media.json"))

    assert (iso.file, iso.profile, iso.kind) == (
        "Win11_25H2_Polish_x64_v2.iso",
        "windows",
        "installer",
    )
    assert (iso.version, iso.language, iso.arch) == ("10.0.26200", "pl-PL", "amd64")
    assert iso.error is None
    assert len(iso.variants) == 10
    professional = iso.variants[4]
    assert (professional.index, professional.name) == (5, "Windows 11 Pro")
    assert professional.languages == ["pl-PL"]


def test_a_file_no_profile_recognised_is_listed_with_its_error() -> None:
    (unknown,) = MEDIA.validate_python(captured("media_unrecognised.json"))

    assert unknown.profile is None
    assert unknown.error == "Not a recognised installation medium."
    assert unknown.variants == []


def test_the_real_build_status_parses_with_its_steps() -> None:
    build = BuildStatus.model_validate(captured("build_status.json"))

    assert (build.id, build.guest, build.kind, build.status) == (
        "b2f48f9dcd08a",
        "lab1",
        "build",
        "succeeded",
    )
    assert (build.step, build.percent, build.desktop, build.pause) == (6, 100, False, None)
    assert [step.name for step in build.steps][:4] == ["preflight", "fetch", "define", "install"]
    assert build.steps[3].desktop is True


def test_a_paused_build_carries_its_instructions() -> None:
    record = {
        **captured("build_status.json"),
        "status": "paused",
        "pause": {"instructions": "Turn Tamper Protection off, then continue."},
        "desktop": True,
    }

    build = BuildStatus.model_validate(record)

    assert build.pause is not None
    assert build.pause.instructions == "Turn Tamper Protection off, then continue."


def test_the_last_activity_and_the_step_descriptions_pass_through_unchanged() -> None:
    record = captured("build_status.json")
    record["last_activity"] = "2026-10-15T19:12:31Z"
    record["steps"][3]["description"] = "Windows installs itself."

    build = BuildStatus.model_validate(record)

    assert build.last_activity == "2026-10-15T19:12:31Z"
    assert build.steps[3].description == "Windows installs itself."
    dumped = build.model_dump(mode="json")
    assert dumped["last_activity"] == "2026-10-15T19:12:31Z"
    assert dumped["steps"][3]["description"] == "Windows installs itself."


def test_a_build_record_without_them_reads_them_as_null() -> None:
    build = BuildStatus.model_validate(captured("build_status.json"))

    assert build.last_activity is None
    assert [step.description for step in build.steps] == [None] * len(build.steps)


def test_a_build_with_an_unknown_status_is_refused() -> None:
    with pytest.raises(ValidationError):
        BuildStatus.model_validate({**captured("build_status.json"), "status": "exploded"})


def test_a_health_check_result_lists_each_check_with_its_message() -> None:
    result = HealthCheckResult.model_validate(captured("check_result.json"))

    assert result.name == "lab1"
    assert [(check.id, check.ok) for check in result.checks] == [
        ("domain", True),
        ("snapshot", True),
        ("registration", True),
        ("agent", False),
    ]
    assert result.checks[3].message.startswith("the agent at")
