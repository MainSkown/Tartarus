import configparser
import stat

import pytest
from fixtures.guest_samples import NOW, make_guest
from fixtures.profile_samples import FIXTURE_DIR, sample_profile

from guest_engine import registry
from guest_engine.errors import Conflict, GuestNotFound
from guest_engine.registration import apply_registration, render_registration

PROFILES = {"windows": sample_profile("windows"), "ubuntu": sample_profile("ubuntu")}

# The file S0b proved with CAPE: two machines in one registration, listed and routed by label.
PROVEN_BY_S0B = """\
[kvm]
machines = win,win2

[win]
label = win
platform = windows
ip = 192.168.150.10
snapshot = tartarus-clean
arch = x64
interface = tt-guest
tags = windows,win11

[win2]
label = win2
platform = windows
ip = 192.168.150.11
snapshot = tartarus-clean
arch = x64
interface = tt-guest
tags = windows,win11
"""


def ready(name, ip, **changes):
    return make_guest(name, ip, state="ready", **changes)


def test_two_guests_render_the_registration_that_cape_accepted_in_s0b():
    guests = [ready("win", "192.168.150.10"), ready("win2", "192.168.150.11")]

    assert render_registration(guests, PROFILES) == PROVEN_BY_S0B


def test_the_existing_guest_renders_the_file_the_build_script_wrote():
    adopted = registry.adopt(
        (FIXTURE_DIR / "win.dumpxml.xml").read_text(),
        (FIXTURE_DIR / "win.registration.conf").read_text(),
        PROFILES["windows"],
        now=NOW,
    )

    assert (
        render_registration([adopted], PROFILES)
        == (FIXTURE_DIR / "win.registration.conf").read_text()
    )


def test_only_testing_and_ready_guests_are_registered():
    guests = [
        make_guest("building", "192.168.150.10", state="building"),
        make_guest("testing", "192.168.150.11", state="testing"),
        make_guest("ready", "192.168.150.12", state="ready"),
        make_guest("failed", "192.168.150.13", state="failed"),
    ]

    text = render_registration(guests, PROFILES)

    parsed = configparser.ConfigParser()
    parsed.read_string(text)
    assert parsed["kvm"]["machines"] == "ready,testing"
    assert parsed.sections() == ["kvm", "ready", "testing"]


def test_the_output_does_not_depend_on_the_order_the_guests_come_in():
    guests = [ready("win", "192.168.150.10"), ready("win2", "192.168.150.11")]

    assert render_registration(guests[::-1], PROFILES) == render_registration(guests, PROFILES)


def test_platform_arch_and_tags_come_from_each_guests_profile():
    guests = [
        ready("win", "192.168.150.10"),
        ready("tux", "192.168.150.11", profile="ubuntu"),
    ]

    parsed = configparser.ConfigParser()
    parsed.read_string(render_registration(guests, PROFILES))

    assert parsed["tux"]["platform"] == "linux"
    assert parsed["tux"]["tags"] == "linux,ubuntu"
    assert parsed["win"]["tags"] == "windows,win11"


def test_the_snapshot_name_comes_from_the_guest():
    parsed = configparser.ConfigParser()
    parsed.read_string(
        render_registration([ready("win", "192.168.150.10", snapshot="other-clean")], PROFILES)
    )

    assert parsed["win"]["snapshot"] == "other-clean"


@pytest.mark.parametrize("guests", [[], [make_guest("failed", state="failed")]])
def test_nothing_to_register_renders_the_empty_list_cape_accepts(guests):
    assert render_registration(guests, PROFILES) == "[kvm]\nmachines =\n"


def test_two_registered_guests_on_one_address_are_refused_naming_both():
    guests = [ready("win", "192.168.150.10"), ready("win2", "192.168.150.10")]

    with pytest.raises(Conflict, match=r"win.*win2.*192\.168\.150\.10"):
        render_registration(guests, PROFILES)


def test_a_failed_guest_on_the_same_address_does_not_count():
    guests = [ready("win", "192.168.150.10"), make_guest("old", "192.168.150.10", state="failed")]

    assert "machines = win\n" in render_registration(guests, PROFILES)


def test_a_guest_whose_profile_is_not_installed_cannot_be_registered():
    with pytest.raises(GuestNotFound, match="gone"):
        render_registration([ready("win", "192.168.150.10", profile="gone")], PROFILES)


# --- writing the registration directory ----------------------------------------------------


def test_applying_writes_guests_conf_and_removes_every_other_conf(tmp_path):
    (tmp_path / "win.conf").write_text("[kvm]\nmachines = win\n")
    (tmp_path / "zzz.conf").write_text("[kvm]\nmachines = zzz\n")
    (tmp_path / "keep.txt").write_text("not a registration")

    removed = apply_registration(tmp_path, PROVEN_BY_S0B)

    assert removed == ["win.conf", "zzz.conf"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["guests.conf", "keep.txt"]
    assert (tmp_path / "guests.conf").read_text() == PROVEN_BY_S0B


def test_applying_again_has_nothing_left_to_remove(tmp_path):
    apply_registration(tmp_path, PROVEN_BY_S0B)

    assert apply_registration(tmp_path, PROVEN_BY_S0B) == []


def test_a_missing_directory_is_created(tmp_path):
    apply_registration(tmp_path / "kvm.conf.d", PROVEN_BY_S0B)

    assert (tmp_path / "kvm.conf.d" / "guests.conf").is_file()


def test_the_file_is_readable_by_cape(tmp_path):
    apply_registration(tmp_path, PROVEN_BY_S0B)

    assert stat.S_IMODE((tmp_path / "guests.conf").stat().st_mode) == 0o644


def test_a_failed_write_keeps_the_old_registration_and_removes_nothing(tmp_path, monkeypatch):
    apply_registration(tmp_path, PROVEN_BY_S0B)
    (tmp_path / "win.conf").write_text("[kvm]\nmachines = win\n")

    def crash(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(registry.os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        apply_registration(tmp_path, "[kvm]\nmachines =\n")
    monkeypatch.undo()

    assert (tmp_path / "guests.conf").read_text() == PROVEN_BY_S0B
    assert (tmp_path / "win.conf").exists()
