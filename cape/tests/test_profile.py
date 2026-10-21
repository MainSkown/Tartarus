import json
import re
import shutil
import stat
from pathlib import Path

import pytest
from fixtures.profile_samples import (
    PROFILE_FIXTURES,
    profile_data,
    sample_profile,
    with_value,
    without,
)

from guest_engine.profile import (
    ProfileError,
    derive_badges,
    find_step,
    load_profile,
    load_profiles,
    parse_profile,
)

GONE = object()
PROFILE_NAMES = ["windows", "ubuntu"]
GENERIC_STEPS = {"preflight", "define", "snapshot", "register", "copy", "fetch_payload"}


def problems_of(data) -> dict[str, str]:
    with pytest.raises(ProfileError) as raised:
        parse_profile(data)
    return raised.value.problems


def bracketed(path: str) -> str:
    return re.sub(r"\.(\d+)", r"[\1]", path)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_the_profile_survives_a_round_trip_through_its_own_dictionary(name):
    profile = sample_profile(name)

    assert parse_profile(profile.to_dict()) == profile


def test_the_windows_fixture_expresses_the_decisions_of_the_plan():
    profile = sample_profile("windows")

    assert (profile.cape.platform, profile.cape.tags, profile.arch) == (
        "windows",
        ["windows"],
        "x64",
    )
    assert [(rule.build_min, rule.tag) for rule in profile.cape.tag_rules] == [
        (22000, "win11"),
        (10240, "win10"),
    ]
    assert profile.hardware.secure_boot
    assert profile.hardware.tpm
    assert [option.key for option in profile.options] == [
        "defender",
        "decoys",
        "sysmon",
        "key",
        "keyboard",
    ]
    assert profile.agent.path_style == "windows"
    assert profile.agent.finish_dir == "C:\\Windows\\Temp"
    assert profile.agent.shutdown == "acpi"
    steps = profile.build_pipeline("installer", {"defender": False})
    assert [entry.step for entry in steps] == [
        "preflight",
        "define",
        "install",
        "provision",
        "tamper-off",
        "snapshot",
        "register",
    ]
    assert steps[2].desktop is True
    assert steps[0].desktop is False


def test_the_linux_fixture_expresses_what_the_linux_paper_design_needs():
    profile = sample_profile("ubuntu")

    assert profile.media.kinds == ["installer", "disk_image"]
    assert profile.hardware.tpm is False
    assert profile.hardware.clock == "utc"
    assert profile.agent.path_style == "posix"
    assert profile.agent.pre_snapshot == "sync-disk"
    assert [s.step for s in profile.build_pipeline("disk_image", {})][:3] == [
        "preflight",
        "fetch_payload",
        "define",
    ]
    storage_signal = next(s for s in profile.selftest.signals if s.source == "storage")
    assert storage_signal.path == "logs/strace.log"


def test_a_profile_may_describe_the_guest_that_existed_before_the_wizard():
    adoption = sample_profile("windows").adoption

    assert adoption is not None
    assert (adoption.account, adoption.work_dir) == ("Analyst", "C:\\tartarus")
    assert adoption.media.file == "Win11_25H2_Polish_x64_v2.iso"
    assert adoption.media.language == "pl-PL"
    assert adoption.options["defender"] is True
    assert sample_profile("ubuntu").adoption is None


def test_option_defaults_are_the_default_of_every_option():
    assert sample_profile("ubuntu").option_defaults() == {
        "desktop": "gnome",
        "locale": "en_US.UTF-8",
        "keyboard": "us",
        "timezone": "UTC",
        "decoys": True,
    }


def test_interactive_runs_are_described_by_cape_options_and_by_task_fields():
    windows = sample_profile("windows").agent.interactive
    linux = sample_profile("ubuntu").agent.interactive

    assert (windows.options, windows.task_fields) == ("interactive=1,nohuman=yes", {})
    assert (linux.options, linux.task_fields) == ("", {"enforce_timeout": True})


def test_task_fields_may_be_flags_numbers_or_text():
    data = with_value(
        profile_data("ubuntu"),
        "agent.interactive.task_fields",
        {"enforce_timeout": True, "timeout": 300, "route": "none"},
    )

    assert parse_profile(data).agent.interactive.task_fields == {
        "enforce_timeout": True,
        "timeout": 300,
        "route": "none",
    }


def test_task_fields_default_to_none():
    data = without(profile_data("ubuntu"), "agent.interactive.task_fields")

    assert parse_profile(data).agent.interactive.task_fields == {}


def test_the_hardware_persona_names_the_smbios_persona_and_defaults_to_the_default_one():
    assert sample_profile("windows").hardware.persona == "default"
    assert sample_profile("ubuntu").hardware.persona == "lab-desktop"


def test_agent_work_root_is_where_a_guests_working_folder_is_made():
    assert sample_profile("windows").agent.work_root == "C:\\ProgramData"
    assert sample_profile("ubuntu").agent.work_root == "/var/lib"


def test_what_may_change_on_a_clone_is_read_from_the_option_flags_alone():
    assert sample_profile("windows").clone_changeable_options() == {"defender", "decoys"}
    assert sample_profile("ubuntu").clone_changeable_options() == {"decoys"}


def test_a_separate_list_of_changeable_options_is_rejected_and_points_at_the_option_flag():
    data = with_value(profile_data("windows"), "clone.changeable_options", ["defender"])

    assert "changeable_on_clone" in problems_of(data)["clone.changeable_options"]


# --- conditional pipeline entries --------------------------------------------------------


def step_names_of(entries) -> list[str]:
    return [entry.step for entry in entries]


def test_a_conditional_build_step_runs_only_for_the_options_that_match():
    profile = sample_profile("windows")

    defender_on = step_names_of(profile.build_pipeline("installer", {"defender": True}))
    defender_off = step_names_of(profile.build_pipeline("installer", {"defender": False}))

    assert "tamper-off" not in defender_on
    assert defender_off == [
        "preflight",
        "define",
        "install",
        "provision",
        "tamper-off",
        "snapshot",
        "register",
    ]
    assert [step for step in defender_off if step != "tamper-off"] == defender_on


def test_options_the_caller_leaves_out_take_the_profiles_defaults():
    profile = sample_profile("windows")

    assert profile.build_pipeline("installer", {}) == profile.build_pipeline(
        "installer", {"defender": True}
    )


def test_the_clone_pipeline_is_chosen_by_the_options_of_the_clone_too():
    profile = sample_profile("windows")

    assert "tamper-off" not in step_names_of(profile.clone_pipeline({"defender": True}))
    assert step_names_of(profile.clone_pipeline({"defender": False})) == [
        "preflight",
        "copy",
        "define",
        "reconfigure",
        "tamper-off",
        "snapshot",
        "register",
    ]


def test_a_step_needed_in_a_build_and_in_a_clone_is_in_both_pipelines_but_named_once():
    profile = sample_profile("windows")

    assert "tamper-off" in step_names_of(profile.build_pipeline("installer", {"defender": False}))
    assert "tamper-off" in step_names_of(profile.clone_pipeline({"defender": False}))
    assert sorted(profile.step_names()).count("tamper-off") == 1


def test_a_negated_condition_runs_the_step_for_every_other_value():
    data = with_value(
        profile_data("ubuntu"), "pipelines.clone.3.when", {"option": "desktop", "not": "none"}
    )
    profile = parse_profile(data)

    assert "reconfigure" in step_names_of(profile.clone_pipeline({"desktop": "gnome"}))
    assert "reconfigure" not in step_names_of(profile.clone_pipeline({"desktop": "none"}))


def test_a_step_without_a_condition_always_runs():
    profile = sample_profile("ubuntu")

    assert step_names_of(profile.clone_pipeline({"desktop": "none"}))[:3] == [
        "preflight",
        "copy",
        "define",
    ]


def test_a_conditional_pipeline_survives_the_round_trip_through_the_dictionary():
    data = with_value(
        profile_data("ubuntu"), "pipelines.clone.3.when", {"option": "desktop", "not": "none"}
    )
    profile = parse_profile(data)

    assert parse_profile(profile.to_dict()) == profile
    assert profile.to_dict()["pipelines"]["clone"][3]["when"] == {
        "option": "desktop",
        "not": "none",
    }
    assert profile.to_dict()["pipelines"]["clone"][0]["when"] is None


CONDITION_CASES = [
    # (the `when` object, expected problem path)
    ({"option": "nope", "value": True}, "pipelines.clone[3].when.option"),
    ({"option": "defender", "value": "yes"}, "pipelines.clone[3].when.value"),
    ({"option": "defender", "not": "yes"}, "pipelines.clone[3].when.not"),
    ({"option": "keyboard", "value": "fr-FR"}, "pipelines.clone[3].when.value"),
    ({"option": "defender"}, "pipelines.clone[3].when"),
    ({"option": "defender", "value": True, "not": False}, "pipelines.clone[3].when"),
    ({"value": True}, "pipelines.clone[3].when.option"),
    ({"option": "defender", "value": True, "extra": 1}, "pipelines.clone[3].when.extra"),
    ("defender", "pipelines.clone[3].when"),
]


@pytest.mark.parametrize(("when", "expected"), CONDITION_CASES)
def test_a_bad_condition_is_reported_with_its_path(when, expected):
    data = with_value(profile_data("windows"), "pipelines.clone.3.when", when)

    assert expected in problems_of(data)


def test_a_condition_on_a_build_step_is_checked_against_the_options_too():
    data = with_value(
        profile_data("windows"),
        "pipelines.build.installer.4.when",
        {"option": "nope", "value": True},
    )

    assert "pipelines.build.installer[4].when.option" in problems_of(data)


def test_a_pipeline_entry_may_carry_a_sentence_for_the_person_watching_the_build():
    data = with_value(
        profile_data("windows"), "pipelines.build.installer.2.description", "Does the thing."
    )

    profile = parse_profile(data)

    described = profile.pipelines.build["installer"][2]
    assert described.description == "Does the thing."
    assert profile.pipelines.build["installer"][0].description is None
    exported = profile.to_dict()["pipelines"]["build"]["installer"][2]
    assert exported["description"] == "Does the thing."
    assert parse_profile(profile.to_dict()) == profile


def test_the_linux_fixture_has_no_windows_terms():
    text = (PROFILE_FIXTURES / "ubuntu.json").read_text().lower()

    assert [word for word in ("windows", "defender", "powershell", "c:\\") if word in text] == []


def test_defaults_fill_in_the_optional_fields():
    profile = sample_profile("windows")
    preflight = profile.build_pipeline("installer", {})[0]

    assert (preflight.desktop, preflight.weight) == (False, 1)
    assert preflight.timeout_s > 0
    assert profile.identity.account.label == "Username"
    assert profile.options[0].requires_user_step is False
    assert profile.options[2].changeable_on_clone is False


CASES = [
    # (profile, dotted path to change, new value or GONE, expected problem path or None = same path)
    ("windows", "schema_version", 2, None),
    ("windows", "schema_version", "1", None),
    ("windows", "schema_version", GONE, None),
    ("windows", "id", "Windows 11", None),
    ("windows", "id", "x", None),
    ("windows", "id", GONE, None),
    ("windows", "display_name", "", None),
    ("windows", "display_name", 7, None),
    ("windows", "family", GONE, None),
    ("windows", "cape", GONE, None),
    ("windows", "cape.platform", "beos", None),
    ("windows", "cape.tags", "windows", None),
    ("windows", "cape.tags", [1], "cape.tags[0]"),
    ("windows", "cape.tags", ["a", "a"], "cape.tags[1]"),
    ("windows", "cape.tag_rules", "win10", None),
    ("windows", "cape.tag_rules", ["win10"], "cape.tag_rules[0]"),
    ("windows", "cape.tag_rules.0.build_min", "22000", None),
    ("windows", "cape.tag_rules.0.build_min", True, None),
    ("windows", "cape.tag_rules.0.build_min", 0, None),
    ("windows", "cape.tag_rules.0.build_min", GONE, None),
    ("windows", "cape.tag_rules.0.tag", "win 11", None),
    ("windows", "cape.tag_rules.0.tag", 11, None),
    ("windows", "cape.tag_rules.0.tag", GONE, None),
    ("windows", "cape.tag_rules.0.edition", "pro", None),
    ("windows", "cape.tag_rules.1.build_min", 22000, None),
    ("windows", "arch", "arm64", None),
    ("windows", "hardware.boot", "efi", None),
    ("windows", "hardware.secure_boot", "yes", None),
    ("windows", "hardware.boot", "bios", "hardware.secure_boot"),
    ("windows", "hardware.clock", "gmt", None),
    ("windows", "hardware.disk_bus", "nvme", None),
    ("windows", "hardware.machine", "", None),
    ("windows", "hardware.tpm", GONE, None),
    ("windows", "hardware.nic_model", 5, None),
    ("windows", "hardware.persona", "Dell Latitude", None),
    ("windows", "hardware.persona", "", None),
    ("windows", "hardware.persona", 5, None),
    ("windows", "resources.vcpus", 0, None),
    ("windows", "resources.vcpus", 9, None),
    ("windows", "resources.vcpus", "2", None),
    ("windows", "resources.vcpus", True, None),
    ("windows", "resources.ram_mb", 1024, None),
    ("windows", "resources.ram_mb", 40000, None),
    ("windows", "resources.disk_gb", 10, None),
    ("windows", "resources.min_disk_gb", 0, None),
    ("windows", "resources.scratch_gb", -1, None),
    ("windows", "media.kinds", [], None),
    ("windows", "media.kinds", ["floppy"], "media.kinds[0]"),
    ("windows", "media.kinds", ["installer", "installer"], "media.kinds[1]"),
    ("windows", "media.inspector", 5, None),
    ("windows", "media.inspector", "Bad Name", None),
    ("windows", "media", GONE, None),
    ("windows", "options", "all", None),
    ("windows", "options.0.type", "number", None),
    ("windows", "options.0.key", "Bad Key", None),
    ("windows", "options.1.key", "defender", None),
    ("windows", "options.4.choices", GONE, None),
    ("windows", "options.0.choices", ["a"], None),
    ("windows", "options.0.default", "yes", None),
    ("windows", "options.4.default", "fr-FR", None),
    ("windows", "options.3.default", 5, None),
    ("windows", "options.0.changeable_on_clone", "yes", None),
    ("windows", "options.0.colour", "red", None),
    ("windows", "options.0.label", GONE, None),
    ("windows", "options.0.help", GONE, None),
    ("windows", "clone.computer_name_editable", "yes", None),
    ("windows", "clone", GONE, None),
    ("windows", "identity.account.pattern", "(", None),
    ("windows", "identity.account.pattern", GONE, None),
    ("windows", "identity.account.generator", "nope", None),
    ("windows", "identity.account.reserved", "Guest", None),
    ("windows", "identity.account.reserved", [1], "identity.account.reserved[0]"),
    ("windows", "identity.account.optional", "yes", None),
    ("windows", "identity.machine", GONE, None),
    ("windows", "pipelines", GONE, None),
    ("windows", "pipelines.build", GONE, None),
    ("windows", "pipelines.build", {}, "pipelines.build.installer"),
    ("windows", "pipelines.clone", GONE, None),
    ("windows", "pipelines.build.installer", [], None),
    ("windows", "pipelines.build.installer.0.step", "Bad Step!", None),
    ("windows", "pipelines.build.installer.0.step", "../evil", None),
    ("windows", "pipelines.build.installer.1.step", "preflight", None),
    ("windows", "pipelines.build.installer.2.timeout_s", 0, None),
    ("windows", "pipelines.build.installer.2.weight", 0, None),
    ("windows", "pipelines.build.installer.2.desktop", "yes", None),
    ("windows", "pipelines.build.installer.2.description", 5, None),
    ("windows", "pipelines.build.installer.2.description", "", None),
    ("windows", "pipelines.clone.1.description", ["Copies."], None),
    ("windows", "pipelines.build.disk_image", [{"step": "define"}], None),
    ("ubuntu", "pipelines.build.disk_image", GONE, None),
    ("windows", "agent.port", 0, None),
    ("windows", "agent.port", 70000, None),
    ("windows", "agent.path_style", "dos", None),
    ("windows", "agent.shutdown", "kill", None),
    ("windows", "agent.ready", GONE, None),
    ("windows", "agent.ready.marker", 5, None),
    ("windows", "agent.finish_dir", "", None),
    ("windows", "agent.work_root", GONE, None),
    ("windows", "agent.work_root", "", None),
    ("windows", "adoption", [], None),
    ("windows", "adoption.account", GONE, None),
    ("windows", "adoption.work_dir", "", None),
    ("windows", "adoption.media.file", "", None),
    ("windows", "adoption.media.arch", GONE, None),
    ("windows", "adoption.media.language", 5, None),
    ("windows", "adoption.nickname", "x", None),
    ("windows", "adoption.options", "none", None),
    ("windows", "adoption.options.nope", True, None),
    ("windows", "adoption.options.defender", "yes", None),
    ("windows", "adoption.options.keyboard", "fr-FR", None),
    ("windows", "agent.interactive_options", "interactive=1", None),
    ("windows", "agent.interactive", GONE, None),
    ("windows", "agent.interactive", "interactive=1", None),
    ("windows", "agent.interactive.options", 5, None),
    ("windows", "agent.interactive.options", GONE, None),
    ("windows", "agent.interactive.task_fields", ["enforce_timeout"], None),
    (
        "windows",
        "agent.interactive.task_fields",
        {"Enforce-Timeout": True},
        "agent.interactive.task_fields.Enforce-Timeout",
    ),
    (
        "windows",
        "agent.interactive.task_fields",
        {"enforce_timeout": 1.5},
        "agent.interactive.task_fields.enforce_timeout",
    ),
    (
        "windows",
        "agent.interactive.task_fields",
        {"enforce_timeout": None},
        "agent.interactive.task_fields.enforce_timeout",
    ),
    (
        "windows",
        "agent.interactive.task_fields",
        {"enforce_timeout": [1]},
        "agent.interactive.task_fields.enforce_timeout",
    ),
    ("windows", "agent.interactive.extra", 1, None),
    ("windows", "agent.pre_snapshot", 5, None),
    ("windows", "agent.pre_snapshot", "Bad Name", None),
    ("windows", "selftest.sample.source", "", None),
    ("windows", "selftest.sample.build", [], None),
    ("windows", "selftest.sample.build", "gcc", None),
    ("windows", "selftest.sample.output", "", None),
    ("windows", "selftest.sample.output", "../x.exe", None),
    ("windows", "selftest.sample.output", GONE, None),
    ("windows", "selftest.sample.build", ["gcc", "-o", "{output}"], None),
    ("windows", "selftest.sample.build", ["gcc", "{source}"], None),
    ("windows", "selftest.sample.build", ["gcc", "{source}", "{source}", "-o", "{output}"], None),
    ("windows", "selftest.check_step", 5, None),
    ("windows", "selftest.check_step", "Bad Name", None),
    ("windows", "selftest.signals", [], None),
    ("windows", "selftest.signals.0.id", "events.nope", None),
    ("windows", "selftest.signals.0.path", "logs/x", None),
    ("windows", "selftest.signals.0.source", "events", None),
    ("windows", "selftest.signals.1.id", "report.present", None),
    ("ubuntu", "selftest.signals.2.path", GONE, None),
    ("windows", "selftest.facts.script", "", None),
    ("windows", "selftest.extras", [1], "selftest.extras[0]"),
    ("windows", "packages", [], None),
    ("windows", "packages", ["Bad Name!"], "packages[0]"),
    ("windows", "packages", ["exe", "exe"], "packages[1]"),
    ("windows", "badges", "none", None),
    ("windows", "badges.0.option", "nope", None),
    ("windows", "badges.0.value", "on", None),
    ("ubuntu", "badges.0.value", "tiny", None),
    ("windows", "badges.0.label", "", None),
    ("windows", "timeouts.agent_s", 0, None),
    ("windows", "timeouts.shutdown_s", GONE, None),
    ("windows", "timeouts", GONE, None),
    ("windows", "firmware", "uefi-secureboot-tpm", None),
]


@pytest.mark.parametrize(("name", "path", "value", "expected"), CASES)
def test_a_field_error_is_reported_with_its_path(name, path, value, expected):
    base = profile_data(name)
    broken = without(base, path) if value is GONE else with_value(base, path, value)

    assert (expected or bracketed(path)) in problems_of(broken)


def test_a_profile_without_tag_rules_tags_every_guest_with_its_base_tags():
    profile = sample_profile("ubuntu")

    assert profile.cape.tag_rules == []
    assert profile.cape.tags_for("22.04") == ["linux", "ubuntu"]


def test_a_rule_that_an_earlier_one_always_wins_over_is_refused_with_a_readable_message():
    data = with_value(profile_data("windows"), "cape.tag_rules.1.build_min", 30000)

    assert "never reached" in problems_of(data)["cape.tag_rules[1].build_min"]


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("10.0.19041", ["windows", "win10"]),
        ("10.0.26200", ["windows", "win11"]),
        ("10.0.22000", ["windows", "win11"]),
        ("10.0.21999", ["windows", "win10"]),
        ("10.0.10240", ["windows", "win10"]),
        ("6.1.7601", ["windows"]),
        ("not a version", ["windows"]),
        ("10.0", ["windows"]),
        ("", ["windows"]),
        (None, ["windows"]),
    ],
)
def test_the_tags_of_a_guest_follow_the_build_of_its_media(version, expected):
    assert sample_profile("windows").cape.tags_for(version) == expected


def test_a_rule_does_not_repeat_a_tag_the_profile_always_has():
    data = with_value(profile_data("windows"), "cape.tags", ["windows", "win10"])

    assert parse_profile(data).cape.tags_for("10.0.19041") == ["windows", "win10"]


def test_every_field_error_is_collected_not_just_the_first():
    data = with_value(profile_data("windows"), "arch", "arm64")
    data = with_value(data, "agent.port", 0)
    data = without(data, "timeouts")

    assert {"arch", "agent.port", "timeouts"} <= set(problems_of(data))


def test_a_profile_that_is_not_an_object_is_rejected():
    assert "" in problems_of([])


def test_the_error_message_names_the_file_and_every_field():
    data = with_value(profile_data("windows"), "arch", "arm64")
    with pytest.raises(ProfileError) as raised:
        parse_profile(data, source="/profiles/windows/profile.json")

    assert str(raised.value).startswith("/profiles/windows/profile.json: ")
    assert "arch: " in str(raised.value)


@pytest.mark.parametrize(
    ("name", "option", "value", "label"),
    [
        ("windows", "defender", True, "DEFENDER ON"),
        ("windows", "defender", False, "DEFENDER OFF"),
        ("ubuntu", "desktop", "none", "NO DESKTOP"),
    ],
)
def test_badges_are_derived_from_option_values(name, option, value, label):
    profile = sample_profile(name)

    assert derive_badges(profile, {option: value}) == [label]


def test_a_value_no_badge_rule_matches_derives_no_badge():
    assert derive_badges(sample_profile("ubuntu"), {"desktop": "gnome"}) == []


# --- loading profiles from a directory -------------------------------------------------


def make_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def install_profile(root: Path, data: dict, *, skip_steps: frozenset[str] = frozenset()) -> Path:
    directory = root / data["id"]
    shutil.copytree(PROFILE_FIXTURES / data["id"], directory)
    (directory / "profile.json").write_text(json.dumps(data))
    for step in parse_profile(data).step_names():
        if step not in GENERIC_STEPS and step not in skip_steps:
            make_executable(directory / "steps" / step)
    return directory


@pytest.fixture
def generic_steps(tmp_path):
    directory = tmp_path / "generic-steps"
    for step in GENERIC_STEPS:
        make_executable(directory / step)
    return directory


@pytest.fixture
def profiles_dir(tmp_path):
    return tmp_path / "profiles"


def test_every_valid_profile_in_the_directory_is_loaded(profiles_dir, generic_steps):
    for name in PROFILE_NAMES:
        install_profile(profiles_dir, profile_data(name))

    catalog = load_profiles(profiles_dir, generic_steps)

    assert sorted(catalog.profiles) == ["ubuntu", "windows"]
    assert catalog.broken == []


def test_a_profile_naming_a_missing_step_is_rejected_with_the_file_and_the_field(
    profiles_dir, generic_steps
):
    directory = install_profile(
        profiles_dir, profile_data("windows"), skip_steps=frozenset({"provision"})
    )

    with pytest.raises(ProfileError) as raised:
        load_profile(directory, generic_steps)

    message = str(raised.value)
    assert str(directory / "profile.json") in message
    assert "pipelines.build.installer[3].step" in message
    assert "provision" in message


def test_a_step_file_that_is_not_executable_is_rejected(profiles_dir, generic_steps):
    directory = install_profile(profiles_dir, profile_data("windows"))
    (directory / "steps" / "install").chmod(0o644)

    with pytest.raises(
        ProfileError, match=r"pipelines\.build\.installer\[2\]\.step.*not executable"
    ):
        load_profile(directory, generic_steps)


@pytest.mark.parametrize(
    ("field", "file"),
    [
        ("selftest.sample.source", "selftest/benign.c"),
        ("selftest.facts.script", "selftest/guest-facts.ps1"),
    ],
)
def test_a_self_test_file_the_profile_names_must_exist_in_its_directory(
    profiles_dir, generic_steps, field, file
):
    directory = install_profile(profiles_dir, profile_data("windows"))
    (directory / file).unlink()

    with pytest.raises(ProfileError) as raised:
        load_profile(directory, generic_steps)

    message = str(raised.value)
    assert field in message
    assert str(directory / file) in message


@pytest.mark.parametrize("path", ["../outside.c", "/etc/hostname"])
def test_a_self_test_file_cannot_point_outside_the_profile_directory(
    profiles_dir, generic_steps, path
):
    data = with_value(profile_data("windows"), "selftest.sample.source", path)
    directory = install_profile(profiles_dir, data)
    (profiles_dir / "outside.c").write_text("int main(void) { return 0; }")

    with pytest.raises(ProfileError, match=r"selftest\.sample\.source.*inside the profile"):
        load_profile(directory, generic_steps)


def test_a_profile_without_a_facts_script_needs_no_such_file(profiles_dir, generic_steps):
    data = without(profile_data("windows"), "selftest.facts")
    directory = install_profile(profiles_dir, data)
    (directory / "selftest" / "guest-facts.ps1").unlink()

    assert load_profile(directory, generic_steps).selftest.facts is None


def test_the_self_test_check_step_must_exist_too(profiles_dir, generic_steps):
    directory = install_profile(
        profiles_dir, profile_data("windows"), skip_steps=frozenset({"selftest-checks"})
    )

    with pytest.raises(ProfileError, match=r"selftest\.check_step.*selftest-checks"):
        load_profile(directory, generic_steps)


def test_a_profile_may_name_the_step_that_runs_the_guest_side_self_test_checks():
    assert sample_profile("windows").selftest.check_step == "selftest-checks"
    assert sample_profile("ubuntu").selftest.check_step is None


def test_a_profile_without_a_check_step_field_has_none():
    data = without(profile_data("ubuntu"), "selftest.check_step")

    assert parse_profile(data).selftest.check_step is None


def test_a_profile_may_define_no_self_test_sample(profiles_dir, generic_steps):
    data = without(profile_data("windows"), "selftest.sample")
    directory = install_profile(profiles_dir, data)
    (directory / "selftest" / "benign.c").unlink()

    assert load_profile(directory, generic_steps).selftest.sample is None


def test_the_sample_build_names_where_the_source_and_the_output_go():
    sample = sample_profile("windows").selftest.sample

    assert sample.build.count("{source}") == sample.build.count("{output}") == 1
    assert sample.output == "benign.exe"


def test_the_pre_snapshot_step_must_exist_too(profiles_dir, generic_steps):
    directory = install_profile(
        profiles_dir, profile_data("ubuntu"), skip_steps=frozenset({"sync-disk"})
    )

    with pytest.raises(ProfileError, match=r"agent\.pre_snapshot"):
        load_profile(directory, generic_steps)


def test_a_broken_profile_is_listed_and_does_not_stop_the_others(profiles_dir, generic_steps):
    install_profile(profiles_dir, profile_data("ubuntu"))
    directory = install_profile(profiles_dir, profile_data("windows"))
    broken_data = with_value(profile_data("windows"), "arch", "arm64")
    (directory / "profile.json").write_text(json.dumps(broken_data))

    catalog = load_profiles(profiles_dir, generic_steps)

    assert sorted(catalog.profiles) == ["ubuntu"]
    [broken] = catalog.broken
    assert broken.directory == profiles_dir / "windows"
    assert str(profiles_dir / "windows" / "profile.json") in broken.message
    assert "arch" in broken.message


@pytest.mark.parametrize(
    ("content", "reason"),
    [("{not json", "not valid JSON"), (None, "no such file")],
)
def test_unreadable_profile_json_is_broken_with_a_readable_reason(
    profiles_dir, generic_steps, content, reason
):
    directory = profiles_dir / "odd"
    directory.mkdir(parents=True)
    if content is not None:
        (directory / "profile.json").write_text(content)

    [broken] = load_profiles(profiles_dir, generic_steps).broken

    assert reason in broken.message
    assert str(directory / "profile.json") in broken.message


def test_the_profile_id_must_be_the_name_of_its_directory(profiles_dir, generic_steps):
    install_profile(profiles_dir, profile_data("windows"))
    (profiles_dir / "windows").rename(profiles_dir / "win11")

    [broken] = load_profiles(profiles_dir, generic_steps).broken

    assert "id: " in broken.message
    assert "win11" in broken.message


def test_files_and_hidden_directories_in_the_profiles_directory_are_ignored(
    profiles_dir, generic_steps
):
    profiles_dir.mkdir()
    (profiles_dir / "README").write_text("not a profile")
    (profiles_dir / ".cache").mkdir()

    catalog = load_profiles(profiles_dir, generic_steps)

    assert catalog.profiles == {}
    assert catalog.broken == []


def test_a_missing_profiles_directory_is_an_empty_catalog(tmp_path, generic_steps):
    assert load_profiles(tmp_path / "nowhere", generic_steps).profiles == {}


def test_steps_are_looked_up_in_the_profiles_own_directory_before_the_generic_one(
    profiles_dir, generic_steps
):
    directory = install_profile(profiles_dir, profile_data("windows"))
    make_executable(directory / "steps" / "preflight")

    profile = load_profile(directory, generic_steps)

    assert profile.step_path("preflight") == directory / "steps" / "preflight"
    assert profile.step_path("define") == generic_steps / "define"
    assert profile.step_path("install") == directory / "steps" / "install"
    assert profile.step_path("nonexistent") is None


def test_find_step_walks_a_search_path_in_order(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    make_executable(second / "only-second")
    make_executable(first / "both")
    make_executable(second / "both")

    assert find_step("both", [first, second]) == first / "both"
    assert find_step("only-second", [first, second]) == second / "only-second"
    assert find_step("neither", [first, second]) is None
