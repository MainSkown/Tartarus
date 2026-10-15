import random
import re
import string

import pytest

from guest_engine import names
from guest_engine.giveaways import find_giveaway

SEEDS = range(200)


def seeded(seed):
    return random.Random(seed)  # noqa: S311 - determinism is the point, not secrecy


def test_there_are_at_least_sixty_first_names_and_none_is_a_giveaway():
    assert len(names.FIRST_NAMES) >= 60
    assert len(set(names.FIRST_NAMES)) == len(names.FIRST_NAMES)
    assert all(re.fullmatch(r"[A-Z][a-z]+", name) for name in names.FIRST_NAMES)
    assert [name for name in names.FIRST_NAMES if find_giveaway(name)] == []


def test_computer_name_is_desktop_or_laptop_and_seven_characters():
    generated = {names.generate("computer_name", seeded(seed)) for seed in SEEDS}

    assert all(re.fullmatch(r"(DESKTOP|LAPTOP)-[A-Z0-9]{7}", name) for name in generated)
    assert {name.split("-")[0] for name in generated} == {"DESKTOP", "LAPTOP"}


def test_folder_name_is_eight_lower_case_letters():
    generated = {names.generate("folder_name", seeded(seed)) for seed in SEEDS}

    assert all(re.fullmatch(r"[a-z]{8}", name) for name in generated)
    assert len(generated) > 100


def test_password_is_sixteen_safe_characters_with_every_class():
    safe = string.ascii_letters + string.digits + "-_.+=@#%"

    for seed in SEEDS:
        password = names.generate("password", seeded(seed))

        assert len(password) == 16
        assert set(password) <= set(safe)
        assert any(c in string.ascii_lowercase for c in password)
        assert any(c in string.ascii_uppercase for c in password)
        assert any(c in string.digits for c in password)
        assert any(c in "-_.+=@#%" for c in password)


@pytest.mark.parametrize("generator", sorted(names.GENERATOR_NAMES))
def test_a_seeded_source_gives_the_same_value_every_time(generator):
    assert names.generate(generator, seeded(7)) == names.generate(generator, seeded(7))


def test_first_name_comes_from_the_list_and_lower_case_variant_is_lowered():
    assert names.generate("first_name", seeded(3)) in names.FIRST_NAMES
    lowered = names.generate("first_name_lower", seeded(3))
    assert lowered.capitalize() in names.FIRST_NAMES
    assert lowered == lowered.lower()


def test_hostname_is_a_lower_case_first_name_and_a_form_factor():
    generated = {names.generate("hostname", seeded(seed)) for seed in SEEDS}

    assert all(re.fullmatch(r"[a-z]+-(pc|laptop|desktop)", name) for name in generated)


def test_no_generated_value_contains_a_giveaway():
    for generator in names.GENERATOR_NAMES:
        for seed in SEEDS:
            assert find_giveaway(names.generate(generator, seeded(seed))) is None


def test_a_generator_that_produces_a_giveaway_is_asked_again(monkeypatch):
    produced = iter(["my-cape-box", "Michael"])
    monkeypatch.setitem(names.GENERATORS, "flaky", lambda _rng: next(produced))

    assert names.generate("flaky", seeded(0)) == "Michael"


def test_a_generator_that_only_produces_giveaways_fails_loudly(monkeypatch):
    monkeypatch.setitem(names.GENERATORS, "stuck", lambda _rng: "sandbox")

    with pytest.raises(RuntimeError, match="stuck"):
        names.generate("stuck", seeded(0))


def test_an_unknown_generator_is_a_key_error():
    with pytest.raises(KeyError):
        names.generate("nope")


def test_without_a_source_generation_is_not_deterministic():
    assert len({names.generate("password") for _ in range(5)}) == 5
