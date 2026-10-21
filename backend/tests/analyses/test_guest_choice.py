from collections.abc import Collection

import pytest

from app.analyses.guest_choice import (
    GuestRefusedError,
    PackageNotAcceptedError,
    choose_guest,
    require_package_accepted,
)
from app.guest.schemas import Guest, GuestState
from tests.analyses.guest_fakes import windows_profile


def guest(name: str, state: GuestState = "ready") -> Guest:
    return Guest(name=name, state=state)


def refusal(
    guests: list[Guest],
    requested: str | None = None,
    preferred: str | None = None,
    *,
    gate: bool = True,
) -> str:
    with pytest.raises(GuestRefusedError) as refused:
        choose_guest(guests, requested, preferred, gate=gate)
    return str(refused.value)


def chosen(
    guests: list[Guest],
    requested: str | None = None,
    preferred: str | None = None,
    *,
    gate: bool = True,
    busy: Collection[str] = (),
) -> str:
    return choose_guest(guests, requested, preferred, gate=gate, busy=busy).name


def test_the_requested_ready_guest_is_the_one_chosen() -> None:
    assert chosen([guest("lab1"), guest("lab2")], requested="lab2", preferred="lab1") == "lab2"


def test_without_a_request_the_preferred_default_is_chosen_when_it_is_ready() -> None:
    assert chosen([guest("lab1"), guest("lab2")], preferred="lab2") == "lab2"


def test_a_busy_default_gives_way_to_a_ready_guest_with_nothing_queued_or_active() -> None:
    guests = [guest("lab1"), guest("lab2"), guest("lab3")]

    assert chosen(guests, preferred="lab2", busy={"lab1", "lab2"}) == "lab3"


def test_an_idle_default_stays_the_default_while_other_guests_are_busy() -> None:
    assert chosen([guest("lab1"), guest("lab2")], preferred="lab2", busy={"lab1"}) == "lab2"


def test_with_every_guest_busy_the_default_is_chosen_and_queues() -> None:
    guests = [guest("lab1"), guest("lab2")]

    assert chosen(guests, preferred="lab2", busy={"lab1", "lab2"}) == "lab2"


def test_an_idle_guest_is_never_a_guest_that_is_not_ready() -> None:
    guests = [guest("lab1"), guest("lab2", "failed"), guest("lab3")]

    assert chosen(guests, preferred="lab1", busy={"lab1", "lab3"}) == "lab1"


def test_a_requested_busy_guest_is_never_overridden() -> None:
    guests = [guest("lab1"), guest("lab2")]

    assert chosen(guests, requested="lab1", preferred="lab2", busy={"lab1"}) == "lab1"


def test_a_preferred_default_that_is_not_ready_is_ignored_for_the_first_ready_guest() -> None:
    guests = [guest("lab0", "failed"), guest("lab1"), guest("lab2")]

    assert chosen(guests, preferred="lab0") == "lab1"


def test_a_preferred_default_that_no_longer_exists_is_ignored() -> None:
    assert chosen([guest("lab1"), guest("lab2")], preferred="gone") == "lab1"


def test_without_a_request_or_a_preference_the_first_ready_guest_is_chosen() -> None:
    assert chosen([guest("lab1", "failed"), guest("lab2"), guest("lab3")]) == "lab2"


def test_no_guest_at_all_is_refused_saying_none_has_been_built() -> None:
    assert "no guest has been built" in refusal([]).lower()


def test_an_unknown_requested_guest_is_refused_by_name() -> None:
    message = refusal([guest("lab1")], requested="lab9")

    assert "lab9" in message
    assert "no guest" in message.lower()


@pytest.mark.parametrize("state", ["building", "testing", "failed", "broken"])
def test_a_requested_guest_that_is_not_ready_is_refused_naming_it_and_its_state(
    state: GuestState,
) -> None:
    message = refusal([guest("lab1"), guest("lab2", state)], requested="lab2")

    assert message.startswith(f"lab2 is {state}: it cannot run an analysis")


def test_a_building_guest_blocks_every_submission_even_to_another_ready_guest() -> None:
    message = refusal([guest("lab1"), guest("lab2", "building")], requested="lab1")

    assert message == "Guest lab2 is being built: wait for it to finish"


def test_two_guests_being_built_are_both_named_in_the_refusal() -> None:
    message = refusal([guest("lab1"), guest("lab2", "building"), guest("lab3", "building")])

    assert message == "Guests lab2, lab3 are being built: wait for them to finish"


def test_a_testing_guest_blocks_user_submissions() -> None:
    message = refusal([guest("lab1"), guest("lab2", "testing")])

    assert "being tested" in message


def test_with_nothing_ready_and_nothing_building_the_states_are_listed() -> None:
    message = refusal([guest("lab1", "failed"), guest("lab2", "broken")])

    assert "no guest is ready" in message.lower()
    assert "lab1 is failed" in message
    assert "lab2 is broken" in message


def test_the_gate_off_lets_a_testing_guest_run_while_others_build_or_test() -> None:
    guests = [guest("lab1", "building"), guest("lab2", "testing")]

    assert chosen(guests, requested="lab2", gate=False) == "lab2"


def test_the_gate_off_still_needs_the_guest_to_exist_and_to_be_registered() -> None:
    guests = [guest("lab1", "building"), guest("lab2", "failed")]

    assert "lab9" in refusal(guests, requested="lab9", gate=False)
    assert "lab1 is building" in refusal(guests, requested="lab1", gate=False)
    assert "lab2 is failed" in refusal(guests, requested="lab2", gate=False)


@pytest.mark.parametrize("package", ["auto", "exe", "dll", "ps1"])
def test_auto_and_the_packages_of_the_profile_are_accepted(package: str) -> None:
    require_package_accepted(guest("lab1"), windows_profile(), package)


def test_a_package_the_profile_does_not_list_is_refused_naming_the_allowed_ones() -> None:
    with pytest.raises(PackageNotAcceptedError) as refused:
        require_package_accepted(guest("lab1"), windows_profile(), "elf")

    message = str(refused.value)
    assert "elf" in message
    assert "lab1" in message
    assert "auto, exe, dll" in message
