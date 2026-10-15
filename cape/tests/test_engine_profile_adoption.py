"""The Windows profile describes the guest M0b built, so the engine can adopt it at first start."""

import json
from pathlib import Path

from fixtures.profile_samples import FIXTURE_DIR

from guest_engine import registry
from guest_engine.profile import parse_profile

PROFILE_DIR = Path(__file__).parents[2] / "guest" / "profiles" / "windows"
M0B_INPUT_LOCALE = "0415:00000415"


def windows_profile():
    return parse_profile(json.loads((PROFILE_DIR / "profile.json").read_text()))


def test_the_profile_describes_the_guest_that_was_built_before_the_wizard():
    adoption = windows_profile().adoption

    assert adoption is not None
    assert (adoption.account, adoption.machine) == ("Analyst", "DESKTOP-7A3K2P9")
    assert adoption.password == "Tartarus1!"  # noqa: S105 - the documented M0b value
    assert adoption.work_dir == "C:\\tartarus"
    assert adoption.media.file == "Win11_25H2_Polish_x64_v2.iso"
    assert (adoption.media.variant, adoption.media.version) == ("5", "10.0.26200")
    assert (adoption.media.language, adoption.media.arch) == ("pl-PL", "amd64")


def test_its_options_are_the_ones_m0b_built_with_and_its_keyboard_is_the_polish_layout():
    adoption = windows_profile().adoption
    layouts = json.loads((PROFILE_DIR / "keyboards.json").read_text())

    assert adoption.options["defender"] is True
    assert adoption.options["decoys"] is False
    assert adoption.options["sysmon"] is False
    assert adoption.options["key"] == ""
    assert layouts[adoption.options["keyboard"]] == M0B_INPUT_LOCALE


def test_the_real_guests_files_are_adopted_with_it():
    guest = registry.adopt(
        (FIXTURE_DIR / "win.dumpxml.xml").read_text(),
        (FIXTURE_DIR / "win.registration.conf").read_text(),
        windows_profile(),
    )

    assert (guest.name, guest.state, guest.adopted) == ("win", "ready", True)
    assert guest.ip == "192.168.150.10"
    assert guest.identity.account == "Analyst"
    assert guest.options["keyboard"] == "Polish (Programmers)"
    assert guest.work_dir == "C:\\tartarus"
    assert guest.giveaways, "the carried-over names are flagged as giveaways, said on the card"
