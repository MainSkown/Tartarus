import json
import logging

import pytest
from fixtures.engine_lab import FAKE, Lab
from fixtures.profile_samples import FIXTURE_DIR

DOMAIN_XML = (FIXTURE_DIR / "win.dumpxml.xml").read_text()
REGISTRATION = (
    (FIXTURE_DIR / "win.registration.conf")
    .read_text()
    .replace("platform = windows", "platform = linux")
    .replace("tags = windows,win11", "tags = fake")
)


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


def existing_guest(lab, registration=REGISTRATION, file="win.conf"):
    (lab.registration_dir / file).write_text(registration)
    lab.host.define_elsewhere("win", DOMAIN_XML)
    return lab.restarted()


def test_a_guest_registered_before_the_registry_existed_is_adopted_at_start(lab):
    engine = existing_guest(lab)

    [guest] = engine.guests()

    assert (guest["name"], guest["state"], guest["adopted"]) == ("win", "ready", True)
    assert guest["ip"] == "192.168.150.10"
    assert guest["identity"]["account"] == "analyst"
    assert guest["options"] == {"pause": False, "slow": False, "token": ""}


def test_adoption_replaces_the_old_registration_file_without_restarting_cape(lab):
    existing_guest(lab)

    assert sorted(path.name for path in lab.registration_dir.iterdir()) == ["guests.conf"]
    assert "machines = win" in (lab.registration_dir / "guests.conf").read_text()
    assert lab.host.cape_restarts == 0


def test_adopting_twice_changes_nothing(lab):
    engine = existing_guest(lab)
    record = (lab.root / "win" / "guest.json").read_bytes()

    lab.restarted()

    assert (lab.root / "win" / "guest.json").read_bytes() == record
    assert [guest["name"] for guest in engine.guests()] == ["win"]
    assert lab.host.cape_restarts == 0


def test_a_leftover_file_of_a_guest_the_registry_knows_is_cleaned_even_if_its_vm_is_gone(lab):
    engine = existing_guest(lab)
    (lab.registration_dir / "win.conf").write_text(REGISTRATION)
    lab.host.extra_domains.pop("win")

    engine = lab.restarted()

    assert [guest["name"] for guest in engine.guests()] == ["win"]
    assert sorted(path.name for path in lab.registration_dir.iterdir()) == ["guests.conf"]


def test_a_guest_built_afterwards_gets_the_next_address(lab):
    existing_guest(lab)

    lab.build("alpha")

    assert lab.engine.guest("alpha")["ip"] == "192.168.150.11"
    assert lab.host.machines() == ["alpha", "win"]


def test_a_registration_whose_vm_libvirt_does_not_have_is_left_alone(lab, caplog):
    (lab.registration_dir / "win.conf").write_text(REGISTRATION)

    with caplog.at_level(logging.INFO, logger="guest_engine"):
        engine = lab.restarted()

    assert engine.guests() == []
    assert (lab.registration_dir / "win.conf").exists()
    assert not (lab.registration_dir / "guests.conf").exists()
    assert "win" in caplog.text
    assert "libvirt has no VM" in caplog.text


def test_without_a_profile_that_has_adoption_data_nothing_is_adopted_or_touched(tmp_path, caplog):
    profiles = tmp_path / "profiles"
    source = FAKE / "profiles" / "fake"
    for file in source.rglob("*"):
        target = profiles / "fake" / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if file.is_file():
            target.write_bytes(file.read_bytes())
            target.chmod(file.stat().st_mode)
    data = json.loads((profiles / "fake" / "profile.json").read_text())
    del data["adoption"]
    (profiles / "fake" / "profile.json").write_text(json.dumps(data))
    lab = Lab(tmp_path, profiles_dir=profiles)
    (lab.registration_dir / "win.conf").write_text(REGISTRATION)
    lab.host.define_elsewhere("win", DOMAIN_XML)

    with caplog.at_level(logging.INFO, logger="guest_engine"):
        engine = lab.restarted()

    assert engine.guests() == []
    assert (lab.registration_dir / "win.conf").read_text() == REGISTRATION
    assert "no installed profile has adoption data" in caplog.text


def test_a_registration_that_does_not_match_its_vm_is_not_adopted(lab, caplog):
    wrong = REGISTRATION.replace("label = win", "label = other")

    with caplog.at_level(logging.INFO, logger="guest_engine"):
        engine = existing_guest(lab, registration=wrong)

    assert engine.guests() == []
    assert (lab.registration_dir / "win.conf").exists()
    assert "not adopted" in caplog.text


def test_one_registration_nobody_can_adopt_keeps_every_file_in_place(lab):
    (lab.registration_dir / "other.conf").write_text("[kvm]\nmachines = a,b\n")

    existing_guest(lab)

    assert sorted(path.name for path in lab.registration_dir.iterdir()) == [
        "other.conf",
        "win.conf",
    ]
    assert [guest["name"] for guest in lab.engine.guests()] == ["win"]


def test_the_adopted_guest_can_be_cloned_like_any_other(lab):
    engine = existing_guest(lab)

    build_id = engine.start_clone("win", {"name": "copy"})
    lab.settle(build_id)

    assert engine.guest("copy")["cloned_from"] == "win"
    assert engine.guest("copy")["state"] == "testing"
    assert lab.host.machines() == ["copy", "win"]


def test_the_adopted_guests_address_is_never_given_to_a_new_build(lab):
    existing_guest(lab)
    (lab.root / "win" / "guest.json").write_text('{"ip": "192.168.150.10"')  # now corrupt

    lab.build("alpha")

    assert lab.engine.guest("alpha")["ip"] == "192.168.150.11"
