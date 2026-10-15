import copy
import re
from dataclasses import replace

import pytest
from fixtures.guest_samples import make_guest, seeded
from fixtures.profile_samples import profile_data, sample_profile, with_value

from guest_engine import names
from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters
from guest_engine.profile import parse_profile
from guest_engine.registry import MAX_GUESTS
from guest_engine.validation import (
    ValidationContext,
    validate_build,
    validate_clone,
)

PROFILES = {"windows": sample_profile("windows"), "ubuntu": sample_profile("ubuntu")}

MEDIA = [
    {
        "file": "disc.iso",
        "profile": "windows",
        "kind": "installer",
        "variants": [{"index": 4, "name": "Home"}, {"index": 5, "name": "Pro"}],
        "version": "10.0.26200",
        "language": "pl-PL",
        "arch": "amd64",
    },
    {
        "file": "server.iso",
        "profile": "ubuntu",
        "kind": "installer",
        "variants": [{"name": "Server"}],
        "version": "24.04.1",
        "language": None,
        "arch": "amd64",
    },
    {
        "file": "cloud.img",
        "profile": "ubuntu",
        "kind": "disk_image",
        "variants": [],
        "version": "24.04",
        "language": None,
        "arch": "amd64",
    },
    {"file": "broken.iso", "profile": None, "error": "Not a disc image that can be read."},
]

GOOD_BUILD = {
    "name": "lab-one",
    "profile": "windows",
    "media": {"file": "disc.iso", "variant": "5"},
    "options": {"defender": False},
    "identity": {"account": "Michael", "machine": "DESKTOP-ABC1234", "password": "S3cret-pass!"},
    "resources": {"vcpus": 4, "ram_mb": 8192, "disk_gb": 100},
}


def context(guests=(), profiles=None, media=None):
    return ValidationContext(profiles or PROFILES, list(guests), MEDIA if media is None else media)


def changed(request, path, value="__remove__"):
    """A copy of `request` with the value at dotted `path` replaced, or removed."""
    result = copy.deepcopy(request)
    *parents, last = path.split(".")
    target = result
    for key in parents:
        target = target[key]
    if value == "__remove__":
        del target[last]
    else:
        target[last] = value
    return result


def fields_of(request, ctx=None):
    with pytest.raises(InvalidParameters) as raised:
        validate_build(request, ctx or context(), seeded(1))
    return raised.value.fields


# --- a build request -----------------------------------------------------------------------


def test_a_complete_request_becomes_a_resolved_spec():
    built = validate_build(GOOD_BUILD, context(), seeded(1))

    spec = built.spec
    assert (spec.name, spec.profile, spec.kind, spec.cloned_from) == (
        "lab-one",
        "windows",
        "build",
        None,
    )
    assert built.media_kind == "installer"
    assert spec.media_kind == "installer"
    assert (spec.media.file, spec.media.variant, spec.media.version) == (
        "disc.iso",
        "5",
        "10.0.26200",
    )
    assert (spec.media.language, spec.media.arch) == ("pl-PL", "amd64")
    assert spec.options == {**PROFILES["windows"].option_defaults(), "defender": False}
    assert (spec.identity.account, spec.identity.machine) == ("Michael", "DESKTOP-ABC1234")
    assert spec.identity.password == "S3cret-pass!"  # noqa: S105
    assert (spec.resources.vcpus, spec.resources.ram_mb, spec.resources.disk_gb) == (4, 8192, 100)
    assert spec.work_dir is None


def test_a_bare_request_uses_the_profile_defaults_and_generates_the_identity():
    request = {
        "name": "lab-one",
        "profile": "windows",
        "media": {"file": "disc.iso", "variant": "5"},
    }

    spec = validate_build(request, context(), seeded(1)).spec

    profile = PROFILES["windows"]
    assert spec.options == profile.option_defaults()
    assert (spec.resources.vcpus, spec.resources.ram_mb, spec.resources.disk_gb) == (2, 4096, 80)
    assert spec.identity.account in names.FIRST_NAMES
    assert re.fullmatch(r"(DESKTOP|LAPTOP)-[A-Z0-9]{7}", spec.identity.machine)
    assert len(spec.identity.password) == 16


def test_blank_identity_values_are_generated_and_the_same_seed_gives_the_same_ones():
    request = changed(GOOD_BUILD, "identity", {"account": "", "machine": None, "password": ""})

    first = validate_build(request, context(), seeded(5)).spec.identity
    second = validate_build(request, context(), seeded(5)).spec.identity

    assert first == second
    assert first.account != ""
    assert first.machine != ""


@pytest.mark.parametrize(
    ("profile", "media_file", "variant"),
    [
        ("windows", "disc.iso", "5"),
        ("ubuntu", "server.iso", "Server"),
        ("ubuntu", "cloud.img", None),
    ],
)
def test_what_a_profile_generates_always_satisfies_that_profiles_own_rules(
    profile, media_file, variant
):
    rules = PROFILES[profile].identity
    request = {
        "name": "lab-one",
        "profile": profile,
        "media": {"file": media_file, "variant": variant},
    }

    for seed in range(100):
        identity = validate_build(request, context(), seeded(seed)).spec.identity

        assert re.fullmatch(rules.account.pattern, identity.account)
        assert re.fullmatch(rules.machine.pattern, identity.machine)
        assert re.fullmatch(rules.password.pattern, identity.password)


def test_the_media_kind_selects_the_pipeline_and_a_medium_without_variants_needs_none():
    request = {"name": "lab-one", "profile": "ubuntu", "media": {"file": "cloud.img"}}

    built = validate_build(request, context(), seeded(1))

    assert built.media_kind == "disk_image"
    assert built.spec.media.variant is None


def test_a_variant_may_be_given_as_the_number_the_scan_listed():
    request = changed(GOOD_BUILD, "media.variant", 5)

    assert validate_build(request, context(), seeded(1)).spec.media.variant == "5"


def test_a_variant_without_an_index_is_chosen_by_name():
    request = {
        "name": "lab-one",
        "profile": "ubuntu",
        "media": {"file": "server.iso", "variant": "Server"},
    }

    assert validate_build(request, context(), seeded(1)).spec.media.variant == "Server"


BAD_FIELDS = [
    # (path to change, new value or REMOVE, field expected in the answer)
    ("name", "__remove__", "name"),
    ("name", "Bad Name", "name"),
    ("name", "a", "name"),
    ("name", "x" * 33, "name"),
    ("name", 5, "name"),
    ("name", "kvm", "name"),
    ("name", "taken", "name"),
    ("profile", "__remove__", "profile"),
    ("profile", "nope", "profile"),
    ("media", "__remove__", "media.file"),
    ("media.file", "__remove__", "media.file"),
    ("media.file", "../disc.iso", "media.file"),
    ("media.file", "sub/disc.iso", "media.file"),
    ("media.file", ".hidden", "media.file"),
    ("media.file", "missing.iso", "media.file"),
    ("media.file", "broken.iso", "media.file"),
    ("media.file", "server.iso", "media.file"),
    ("media.variant", "__remove__", "media.variant"),
    ("media.variant", "99", "media.variant"),
    ("options", "all", "options"),
    ("options.colour", "red", "options.colour"),
    ("options.defender", "yes", "options.defender"),
    ("options.keyboard", "xx-XX", "options.keyboard"),
    ("options.key", 5, "options.key"),
    ("identity", "me", "identity"),
    ("identity.account", 5, "identity.account"),
    ("identity.account", "Administrator", "identity.account"),
    ("identity.account", "administrator", "identity.account"),
    ("identity.account", "1abc", "identity.account"),
    ("identity.account", "A" * 21, "identity.account"),
    ("identity.account", "MyCape", "identity.account"),
    ("identity.account", "Analyst", "identity.account"),
    ("identity.account", " ", "identity.account"),
    ("identity.machine", "SANDBOX-01", "identity.machine"),
    ("identity.machine", "CAPE-01", "identity.machine"),
    ("identity.machine", "12345", "identity.machine"),
    ("identity.machine", "-abc", "identity.machine"),
    ("identity.machine", "abc-", "identity.machine"),
    ("identity.machine", "A" * 16, "identity.machine"),
    ("identity.machine", "has space", "identity.machine"),
    ("identity.machine", "localhost", "identity.machine"),
    ("identity.password", "short", "identity.password"),
    ("identity.password", "x" * 65, "identity.password"),
    ("identity.password", "tab\tinside1", "identity.password"),
    ("identity.password", "Tartarus1!", "identity.password"),
    ("resources", "big", "resources"),
    ("resources.vcpus", 0, "resources.vcpus"),
    ("resources.vcpus", 9, "resources.vcpus"),
    ("resources.vcpus", "2", "resources.vcpus"),
    ("resources.vcpus", True, "resources.vcpus"),
    ("resources.ram_mb", 1024, "resources.ram_mb"),
    ("resources.ram_mb", 40000, "resources.ram_mb"),
    ("resources.disk_gb", 63, "resources.disk_gb"),
    ("resources.disk_gb", 0, "resources.disk_gb"),
    ("resources.disk_gb", "80", "resources.disk_gb"),
    ("colour", "red", "colour"),
]


@pytest.mark.parametrize(("path", "value", "field"), BAD_FIELDS)
def test_every_bad_field_is_reported_under_its_own_path(path, value, field):
    request = changed(GOOD_BUILD, path, value)
    existing = [make_guest("taken", "192.168.150.10", state="ready")]

    assert field in fields_of(request, context(existing))


def test_the_refusal_of_a_giveaway_says_what_it_found_and_not_the_password():
    request = changed(GOOD_BUILD, "identity.password", "Tartarus1!")

    reason = fields_of(request)["identity.password"]

    assert "tartarus" in reason
    assert "Tartarus1" not in reason


def test_every_problem_is_collected_before_anything_is_raised():
    request = changed(GOOD_BUILD, "name", "Bad Name")
    request = changed(request, "identity.machine", "SANDBOX-01")
    request = changed(request, "resources.ram_mb", 1)

    assert {"name", "identity.machine", "resources.ram_mb"} <= set(fields_of(request))


def test_a_request_that_is_not_an_object_is_refused():
    with pytest.raises(InvalidParameters) as raised:
        validate_build(["name"], context(), seeded(1))

    assert "request" in raised.value.fields


def test_a_name_is_taken_by_a_guest_in_any_state():
    existing = [make_guest("lab-one", state="failed")]

    assert "name" in fields_of(GOOD_BUILD, context(existing))


def test_a_profile_that_makes_an_identity_value_mandatory_does_not_generate_it():
    data = with_value(profile_data("windows"), "identity.account.optional", False)
    ctx = context(profiles={"windows": parse_profile(data)})
    request = changed(GOOD_BUILD, "identity.account", "")

    assert "identity.account" in fields_of(request, ctx)


def test_the_profile_decides_which_names_are_reserved():
    request = {
        "name": "tux",
        "profile": "ubuntu",
        "media": {"file": "server.iso", "variant": "Server"},
        "identity": {"account": "root"},
    }

    assert "identity.account" in fields_of(request)


def test_a_request_with_a_problem_does_not_need_the_rest_to_be_valid_to_be_judged():
    assert fields_of({"name": "lab-one", "profile": "nope"}) == {
        "profile": "is not an installed profile (windows, ubuntu)"
    }


def test_the_guest_cap_is_a_conflict_even_for_a_valid_request():
    guests = [make_guest(f"guest-{n}", f"192.168.150.{10 + n}") for n in range(MAX_GUESTS)]

    with pytest.raises(Conflict, match=str(MAX_GUESTS)):
        validate_build(GOOD_BUILD, context(guests), seeded(1))


def test_one_below_the_cap_is_fine():
    guests = [make_guest(f"guest-{n}", f"192.168.150.{10 + n}") for n in range(MAX_GUESTS - 1)]

    assert validate_build(GOOD_BUILD, context(guests), seeded(1)).spec.name == "lab-one"


# --- a clone request -----------------------------------------------------------------------


def source_guest(**changes):
    profile = PROFILES["windows"]
    defaults = {
        "state": "ready",
        "options": {**profile.option_defaults(), "defender": True, "decoys": False},
    }
    return make_guest("win", **{**defaults, **changes})


def clone_fields(params, guests=None, profiles=None):
    ctx = context(guests if guests is not None else [source_guest()], profiles)
    with pytest.raises(InvalidParameters) as raised:
        validate_clone("win", params, ctx, seeded(1))
    return raised.value.fields


def test_a_bare_clone_inherits_everything_and_gets_a_new_computer_name():
    source = source_guest()

    spec = validate_clone("win", {"name": "win-two"}, context([source]), seeded(1))

    assert (spec.name, spec.profile, spec.kind, spec.cloned_from) == (
        "win-two",
        "windows",
        "clone",
        "win",
    )
    assert spec.media == source.media
    assert spec.options == source.options
    assert spec.resources == source.resources
    assert spec.work_dir == source.work_dir
    assert spec.identity.account == source.identity.account
    assert spec.identity.password == source.identity.password
    assert spec.identity.machine != source.identity.machine
    assert re.fullmatch(r"(DESKTOP|LAPTOP)-[A-Z0-9]{7}", spec.identity.machine)


def test_the_changeable_options_and_the_resources_can_differ_on_a_clone():
    params = {
        "name": "win-two",
        "options": {"defender": False, "decoys": True},
        "identity": {"machine": "DESKTOP-NEW1234"},
        "resources": {"vcpus": 4, "ram_mb": 8192},
    }

    spec = validate_clone("win", params, context([source_guest()]), seeded(1))

    assert (spec.options["defender"], spec.options["decoys"]) == (False, True)
    assert spec.identity.machine == "DESKTOP-NEW1234"
    assert (spec.resources.vcpus, spec.resources.ram_mb, spec.resources.disk_gb) == (4, 8192, 80)


def test_an_option_that_is_not_changeable_may_be_repeated_as_it_is_but_not_altered():
    source = source_guest()
    same = {"name": "win-two", "options": {"sysmon": source.options["sysmon"]}}
    other = {"name": "win-two", "options": {"sysmon": not source.options["sysmon"]}}

    assert validate_clone("win", same, context([source]), seeded(1)).options == source.options
    assert "options.sysmon" in clone_fields(other)


def test_which_options_a_clone_may_change_is_decided_by_the_option_flag_alone():
    data = with_value(profile_data("windows"), "options.0.changeable_on_clone", False)
    data = with_value(data, "options.2.changeable_on_clone", True)
    profiles = {"windows": parse_profile(data)}
    source = source_guest()

    allowed = {"name": "win-two", "options": {"sysmon": not source.options["sysmon"]}}
    refused = {"name": "win-two", "options": {"defender": not source.options["defender"]}}

    spec = validate_clone("win", allowed, context([source], profiles), seeded(1))
    assert spec.options["sysmon"] is not source.options["sysmon"]
    assert "options.defender" in clone_fields(refused, profiles=profiles)


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"name": "win-two", "options": {"colour": "red"}}, "options.colour"),
        ({"name": "win-two", "options": {"defender": "yes"}}, "options.defender"),
        ({"name": "win-two", "identity": {"account": "Someone"}}, "identity.account"),
        ({"name": "win-two", "identity": {"account": "Analyst"}}, "identity.account"),
        ({"name": "win-two", "identity": {"password": "Another-pass-1"}}, "identity.password"),
        ({"name": "win-two", "identity": {"machine": "DESKTOP-ABC1234"}}, "identity.machine"),
        ({"name": "win-two", "identity": {"machine": "desktop-abc1234"}}, "identity.machine"),
        ({"name": "win-two", "identity": {"machine": "SANDBOX-01"}}, "identity.machine"),
        ({"name": "win-two", "identity": {"machine": "12345"}}, "identity.machine"),
        ({"name": "win-two", "resources": {"disk_gb": 200}}, "resources.disk_gb"),
        ({"name": "win-two", "resources": {"vcpus": 99}}, "resources.vcpus"),
        ({"name": "win-two", "resources": {"ram_mb": 100}}, "resources.ram_mb"),
        ({"name": "win-two", "media": {"file": "other.iso"}}, "media"),
        ({"name": "win-two", "profile": "ubuntu"}, "profile"),
        ({"name": "win"}, "name"),
        ({"name": "Bad Name"}, "name"),
        ({}, "name"),
    ],
)
def test_a_clone_field_that_is_inherited_or_invalid_is_refused(params, field):
    assert field in clone_fields(params)


def test_a_blank_inherited_field_is_not_a_request_to_change_it():
    params = {"name": "win-two", "identity": {"account": "", "password": None}}

    spec = validate_clone("win", params, context([source_guest()]), seeded(1))

    assert spec.identity.account == source_guest().identity.account


def test_the_same_disk_size_is_not_a_change():
    params = {"name": "win-two", "resources": {"disk_gb": source_guest().resources.disk_gb}}

    assert (
        validate_clone("win", params, context([source_guest()]), seeded(1)).resources.disk_gb == 80
    )


def test_a_profile_that_does_not_let_the_machine_name_be_edited_always_generates_it():
    data = with_value(profile_data("windows"), "clone.computer_name_editable", False)
    profiles = {"windows": parse_profile(data)}
    chosen = {"name": "win-two", "identity": {"machine": "DESKTOP-NEW1234"}}

    assert "identity.machine" in clone_fields(chosen, profiles=profiles)
    spec = validate_clone(
        "win", {"name": "win-two"}, context([source_guest()], profiles), seeded(1)
    )
    assert spec.identity.machine != source_guest().identity.machine


def test_a_generated_clone_name_is_never_the_sources(monkeypatch):
    source = source_guest()
    produced = iter([source.identity.machine.lower(), "DESKTOP-FRESH123"])
    monkeypatch.setitem(names.GENERATORS, "computer_name", lambda _rng: next(produced))

    spec = validate_clone("win", {"name": "win-two"}, context([source]), seeded(1))

    assert spec.identity.machine == "DESKTOP-FRESH123"


def test_cloning_an_unknown_guest_is_not_found():
    with pytest.raises(GuestNotFound, match="ghost"):
        validate_clone("ghost", {"name": "win-two"}, context([source_guest()]), seeded(1))


@pytest.mark.parametrize("state", ["building", "testing", "failed"])
def test_only_a_ready_guest_can_be_cloned(state):
    source = source_guest(state=state)

    with pytest.raises(Conflict, match=state):
        validate_clone("win", {"name": "win-two"}, context([source]), seeded(1))


def test_cloning_is_refused_at_the_guest_cap():
    guests = [source_guest()] + [
        make_guest(f"guest-{n}", f"192.168.150.{20 + n}") for n in range(MAX_GUESTS - 1)
    ]

    with pytest.raises(Conflict, match=str(MAX_GUESTS)):
        validate_clone("win", {"name": "win-two"}, context(guests), seeded(1))


def test_a_source_whose_profile_is_gone_cannot_be_cloned():
    source = replace(source_guest(), profile="removed")

    with pytest.raises(Conflict, match="removed"):
        validate_clone("win", {"name": "win-two"}, context([source]), seeded(1))


# --- the kind of the medium ----------------------------------------------------------------


@pytest.mark.parametrize("kind", [None, "", "floppy"])
def test_a_medium_whose_kind_the_scan_could_not_name_is_refused_instead_of_guessed(kind):
    entry = {**MEDIA[0], "kind": kind}
    if kind is None:
        del entry["kind"]

    with pytest.raises(InvalidParameters) as raised:
        validate_build(GOOD_BUILD, context(media=[entry]), seeded(1))

    assert "kind" in raised.value.fields["media.file"]
    assert "installer" in raised.value.fields["media.file"]


def test_a_clone_carries_the_media_kind_of_its_source():
    source = replace(source_guest(), media_kind="disk_image")

    spec = validate_clone("win", {"name": "win-two"}, context([source]), seeded(1))

    assert spec.media_kind == "disk_image"
