import json
import re
import stat

import pytest
from fixtures.guest_samples import NOW, PASSWORD, SUBNET, make_guest, make_spec, seeded
from fixtures.profile_samples import FIXTURE_DIR, sample_profile

from guest_engine import registry
from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters
from guest_engine.giveaways import find_giveaway
from guest_engine.profile import MediaRef
from guest_engine.registry import (
    Guest,
    GuestIdentity,
    GuestResources,
    Registry,
    generate_machine_identity,
    new_guest,
    new_work_dir,
    next_free_ip,
)


@pytest.fixture
def guests(tmp_path):
    return Registry(tmp_path / "guests")


# --- machine identity and work folder ----------------------------------------------------


def test_machine_identity_follows_the_formats_of_the_build_script():
    identity = generate_machine_identity(seeded(1))

    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", identity.uuid
    )
    assert re.fullmatch(r"00:14:22(:[0-9a-f]{2}){3}", identity.mac)
    assert re.fullmatch(r"[A-Z0-9]{7}", identity.smbios_serial)
    assert re.fullmatch(rf"/{identity.smbios_serial}/CN[A-Z0-9]{{12}}/", identity.board_serial)
    assert re.fullmatch(r"S4EWNX0[A-Z0-9]{6}", identity.disk_serial)


def test_machine_identity_is_deterministic_for_a_seed_and_differs_between_seeds():
    assert generate_machine_identity(seeded(1)) == generate_machine_identity(seeded(1))
    assert generate_machine_identity(seeded(1)) != generate_machine_identity(seeded(2))


def test_work_dir_is_a_neutral_random_folder_under_the_profiles_root():
    windows, linux = sample_profile("windows"), sample_profile("ubuntu")

    assert re.fullmatch(r"C:\\ProgramData\\[a-z]{8}", new_work_dir(windows, seeded(1)))
    assert re.fullmatch(r"/var/lib/[a-z]{8}", new_work_dir(linux, seeded(1)))
    assert new_work_dir(windows, seeded(1)) != new_work_dir(windows, seeded(2))
    assert find_giveaway(new_work_dir(windows, seeded(1))) is None


# --- the record --------------------------------------------------------------------------


def test_a_new_guest_starts_building_with_a_generated_identity_and_the_agreed_snapshot():
    guest = new_guest(
        make_spec(), sample_profile("windows"), "192.168.150.10", rng=seeded(1), now=NOW
    )

    assert (guest.state, guest.kind, guest.cloned_from) == ("building", "build", None)
    assert guest.created == "2026-10-15T12:00:00Z"
    assert guest.ip == "192.168.150.10"
    assert guest.snapshot == "tartarus-clean"
    assert guest.selftest is None
    assert guest.adopted is False
    assert guest.machine == generate_machine_identity(seeded(1))
    assert re.fullmatch(r"C:\\ProgramData\\[a-z]{8}", guest.work_dir)


def test_a_clone_keeps_the_work_dir_of_its_source_because_it_is_the_same_disk():
    spec = make_spec(
        "beta", kind="clone", cloned_from="alpha", work_dir="C:\\ProgramData\\qwertyui"
    )

    guest = new_guest(spec, sample_profile("windows"), "192.168.150.11", rng=seeded(1), now=NOW)

    assert (guest.kind, guest.cloned_from) == ("clone", "alpha")
    assert guest.work_dir == "C:\\ProgramData\\qwertyui"


def test_a_record_survives_a_round_trip_through_its_dictionary():
    guest = make_guest()

    assert Guest.from_dict(json.loads(json.dumps(guest.to_dict()))) == guest


def test_the_dictionary_has_the_documented_keys_and_keeps_the_password():
    data = make_guest().to_dict()

    assert set(data) >= {
        "name", "profile", "kind", "cloned_from", "state", "created", "media", "options",
        "identity", "resources", "ip", "machine", "work_dir", "snapshot", "selftest",
    }  # fmt: skip
    assert data["identity"]["password"] == PASSWORD
    assert data["media"] == {
        "file": "disc.iso", "variant": "5", "version": "10.0.26200",
        "language": "pl-PL", "arch": "amd64",
    }  # fmt: skip
    assert set(data["machine"]) == {"uuid", "mac", "smbios_serial", "board_serial", "disk_serial"}


# --- storage -----------------------------------------------------------------------------


def test_a_created_guest_can_be_read_back_and_listed(guests):
    guest = make_guest()

    guests.create(guest)

    assert guests.get("alpha") == guest
    assert guests.list() == [guest]
    assert (guests.root / "alpha" / "guest.json").is_file()


def test_the_record_is_private_to_its_owner_because_it_holds_the_password(guests):
    guests.create(make_guest())

    mode = stat.S_IMODE((guests.root / "alpha" / "guest.json").stat().st_mode)

    assert mode & 0o077 == 0


def test_the_record_and_its_directory_are_synced_to_disk_before_the_write_returns(
    guests, monkeypatch
):
    synced = []
    real_fsync = registry.os.fsync
    monkeypatch.setattr(
        registry.os, "fsync", lambda descriptor: (synced.append(descriptor), real_fsync(descriptor))
    )

    guests.create(make_guest())

    assert len(synced) == 2


def test_creating_a_guest_twice_is_a_conflict(guests):
    guests.create(make_guest())

    with pytest.raises(Conflict, match="alpha"):
        guests.create(make_guest())


@pytest.mark.parametrize("name", ["../etc", "Alpha", "a", "", "a/b", "-x"])
def test_a_name_that_is_not_a_slug_cannot_be_created(guests, name):
    with pytest.raises(InvalidParameters) as raised:
        guests.create(make_guest(name))

    assert "name" in raised.value.fields


@pytest.mark.parametrize("name", ["missing", "../etc", ""])
def test_an_unknown_guest_is_not_found(guests, name):
    with pytest.raises(GuestNotFound):
        guests.get(name)


def test_listing_is_in_creation_order_and_ignores_strays(guests):
    guests.create(make_guest("bravo", "192.168.150.11", created="2026-10-15T12:00:02Z"))
    guests.create(make_guest("alpha", "192.168.150.10", created="2026-10-15T12:00:01Z"))
    (guests.root / "half-made").mkdir()
    (guests.root / "notes.txt").write_text("not a guest")

    assert [guest.name for guest in guests.list()] == ["alpha", "bravo"]


def test_an_empty_or_missing_registry_lists_nothing(guests):
    assert guests.list() == []


def test_the_state_can_be_changed_and_is_persisted(guests):
    guests.create(make_guest())

    updated = guests.update_state("alpha", "testing")

    assert updated.state == "testing"
    assert Registry(guests.root).get("alpha").state == "testing"


def test_an_unknown_state_is_refused(guests):
    guests.create(make_guest())

    with pytest.raises(InvalidParameters) as raised:
        guests.update_state("alpha", "sleeping")

    assert "state" in raised.value.fields
    assert guests.get("alpha").state == "building"


def test_updating_an_unknown_guest_is_not_found(guests):
    with pytest.raises(GuestNotFound):
        guests.update_state("missing", "ready")


def test_other_fields_can_be_updated_without_touching_the_rest(guests):
    guests.create(make_guest())

    guests.update("alpha", disk_path="/var/lib/libvirt/images/alpha.qcow2")
    guests.store_selftest("alpha", {"passed": True})

    stored = guests.get("alpha")
    assert stored.disk_path == "/var/lib/libvirt/images/alpha.qcow2"
    assert stored.selftest == {"passed": True}
    assert stored.state == "building"


def test_deleting_removes_the_record_and_everything_in_its_directory(guests):
    guests.create(make_guest())
    (guests.root / "alpha" / "state.json").write_text("{}")

    guests.delete("alpha")

    assert not (guests.root / "alpha").exists()
    with pytest.raises(GuestNotFound):
        guests.get("alpha")


def test_deleting_an_unknown_guest_is_not_found(guests):
    with pytest.raises(GuestNotFound):
        guests.delete("missing")


def test_a_failed_write_leaves_the_previous_record_whole_and_no_temporary_file(guests, monkeypatch):
    guests.create(make_guest())

    def crash(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(registry.os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        guests.update_state("alpha", "ready")
    monkeypatch.undo()

    assert guests.get("alpha").state == "building"
    assert [path.name for path in (guests.root / "alpha").iterdir()] == ["guest.json"]


# --- addresses ---------------------------------------------------------------------------


def test_the_first_guest_gets_dot_ten():
    assert next_free_ip(SUBNET, set()) == "192.168.150.10"


def test_taken_addresses_are_skipped_and_gaps_are_filled():
    taken = {"192.168.150.10", "192.168.150.11", "192.168.150.13"}

    assert next_free_ip(SUBNET, taken) == "192.168.150.12"


def test_the_subnet_decides_the_prefix():
    assert next_free_ip("10.1.2.0/24", {"10.1.2.10"}) == "10.1.2.11"


def test_addresses_outside_the_static_range_are_never_handed_out():
    taken = {f"192.168.150.{host}" for host in range(10, 99)}

    assert next_free_ip(SUBNET, taken) == "192.168.150.99"
    with pytest.raises(Conflict, match=r"192\.168\.150\.10"):
        next_free_ip(SUBNET, taken | {"192.168.150.99"})


def test_allocation_skips_the_addresses_of_every_guest_including_failed_ones(guests):
    guests.create(make_guest("alpha", "192.168.150.10"))
    guests.create(make_guest("bravo", "192.168.150.11", state="failed"))

    assert guests.allocate_ip(SUBNET) == "192.168.150.12"


def test_a_deleted_guests_address_is_free_again(guests):
    guests.create(make_guest("alpha", "192.168.150.10"))
    guests.create(make_guest("bravo", "192.168.150.11"))

    guests.delete("alpha")

    assert guests.allocate_ip(SUBNET) == "192.168.150.10"


# --- adoption ----------------------------------------------------------------------------

DOMAIN_XML = (FIXTURE_DIR / "win.dumpxml.xml").read_text()
REGISTRATION = (FIXTURE_DIR / "win.registration.conf").read_text()


def adopted():
    return registry.adopt(DOMAIN_XML, REGISTRATION, sample_profile("windows"), now=NOW)


def test_the_existing_guest_is_described_from_its_domain_and_registration():
    guest = adopted()

    assert (guest.name, guest.profile, guest.kind, guest.state) == (
        "win",
        "windows",
        "build",
        "ready",
    )
    assert guest.machine.uuid == "03f22cad-8664-4dc2-ba2f-a93e3ba26471"
    assert guest.machine.mac == "00:14:22:c8:97:00"
    assert guest.machine.smbios_serial == "AGGI4Q1"
    assert guest.machine.board_serial == "/AGGI4Q1/CN4I3G1JW6OB6V/"
    assert guest.machine.disk_serial == "S4EWNX0X67M3L"
    assert guest.resources == GuestResources(vcpus=2, ram_mb=4096, disk_gb=80)
    assert guest.ip == "192.168.150.10"
    assert guest.snapshot == "tartarus-clean"
    assert guest.created == "2026-10-15T12:00:00Z"
    assert guest.selftest is None


def test_the_disk_is_the_base_image_not_the_overlay_a_revert_leaves():
    assert adopted().disk_path == "/var/lib/libvirt/images/win.qcow2"


def test_the_options_are_the_profiles_defaults_overlaid_with_what_the_old_guest_was_built_with():
    guest = adopted()

    assert guest.options == {
        "defender": True,
        "decoys": False,
        "sysmon": False,
        "key": "",
        "keyboard": "pl-PL",
    }


def test_the_identity_and_media_come_from_what_the_profile_knows_of_that_guest():
    guest = adopted()

    assert guest.identity == GuestIdentity("Analyst", "DESKTOP-7A3K2P9", "Tartarus1!")
    assert guest.work_dir == "C:\\tartarus"
    assert guest.media == MediaRef(
        "Win11_25H2_Polish_x64_v2.iso", "5", "10.0.26200", "pl-PL", "amd64"
    )


def test_the_adopted_record_says_it_is_adopted_and_lists_the_giveaways_it_carries():
    guest = adopted()

    assert guest.adopted is True
    assert any("identity.account" in item and "analy" in item for item in guest.giveaways)
    assert any("identity.password" in item and "tartarus" in item for item in guest.giveaways)
    assert any("work_dir" in item and "tartarus" in item for item in guest.giveaways)
    assert not any("identity.machine" in item for item in guest.giveaways)


def test_adopting_twice_changes_nothing(guests):
    first = guests.adopt(DOMAIN_XML, REGISTRATION, sample_profile("windows"), now=NOW)
    guests.update_state("win", "failed")

    second = guests.adopt(DOMAIN_XML, REGISTRATION, sample_profile("windows"), now=NOW)

    assert first.state == "ready"
    assert second.state == "failed"
    assert [guest.name for guest in guests.list()] == ["win"]


def test_a_profile_that_cannot_describe_an_old_guest_cannot_adopt_one():
    with pytest.raises(ValueError, match="adoption"):
        registry.adopt(DOMAIN_XML, REGISTRATION, sample_profile("ubuntu"), now=NOW)


def test_a_registration_for_a_different_domain_is_refused():
    other = REGISTRATION.replace("win", "other")

    with pytest.raises(ValueError, match="other"):
        registry.adopt(DOMAIN_XML, other, sample_profile("windows"), now=NOW)


def test_a_registration_listing_several_machines_is_refused():
    several = REGISTRATION.replace("machines = win", "machines = win,win2")

    with pytest.raises(ValueError, match="one machine"):
        registry.adopt(DOMAIN_XML, several, sample_profile("windows"), now=NOW)


def test_a_platform_the_profile_does_not_serve_is_refused():
    wrong = REGISTRATION.replace("platform = windows", "platform = linux")

    with pytest.raises(ValueError, match="platform"):
        registry.adopt(DOMAIN_XML, wrong, sample_profile("windows"), now=NOW)
