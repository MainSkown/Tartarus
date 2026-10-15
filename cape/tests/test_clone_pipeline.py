"""The shipped Windows profile, with the shipped generic steps, is a profile the engine accepts."""

from pathlib import Path

from guest_engine.profile import load_profile, load_profiles

REPO = Path(__file__).parents[2]
PROFILES = REPO / "guest" / "profiles"
GENERIC_STEPS = REPO / "guest" / "steps"


def test_the_shipped_windows_profile_loads_with_every_step_of_both_pipelines():
    profile = load_profile(PROFILES / "windows", GENERIC_STEPS)

    assert profile.id == "windows"


def test_the_catalog_of_the_shipped_profiles_has_no_broken_profile():
    catalog = load_profiles(PROFILES, GENERIC_STEPS)

    assert [broken.message for broken in catalog.broken] == []
    assert "windows" in catalog.profiles
