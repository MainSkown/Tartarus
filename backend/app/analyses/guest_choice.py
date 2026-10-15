"""Which guest an analysis runs on and what it accepts. Pure: the callers fetch the data."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.guest.schemas import Guest, GuestProfile

AUTO_PACKAGE = "auto"
# A guest in these states changes CAPE's registration, which kills a running analysis (decision 7).
BLOCKING_STATES = {
    "building": "A guest is being built: wait for it to finish",
    "testing": "A guest is being tested: wait for its self-test to finish",
}
TRANSIENT_STATES = frozenset(BLOCKING_STATES)


class GuestRefusedError(Exception):
    """No analysis can be submitted to that guest; the message tells the analyst why."""


class PackageNotAcceptedError(Exception):
    def __init__(self, guest: str, package: str, allowed: Sequence[str]) -> None:
        super().__init__(
            f"Guest {guest} does not accept the package {package!r}: "
            f"it accepts {', '.join(allowed)}"
        )


def recorded_guest(options: Mapping[str, Any]) -> str | None:
    """The guest an analysis was queued for; absent from analyses older than the guest option."""
    guest = options.get("guest")
    return guest if isinstance(guest, str) and guest else None


def choose_guest(
    guests: Sequence[Guest], requested: str | None, preferred: str | None, *, gate: bool
) -> Guest:
    """The guest an analysis runs on.

    `requested` is the analyst's choice and `preferred` the stored default, which only counts
    while that guest is ready. With `gate` off (the self-test of a guest being built) other guests
    building or testing do not matter, and the requested guest may be `testing`.
    """
    if not guests:
        raise GuestRefusedError("No guest has been built: build one on the Guest page first")
    chosen = _requested_guest(guests, requested, gate=gate) if requested else None
    if gate:
        _require_nothing_in_transition(guests)
    return chosen or _default_guest(guests, preferred)


def require_package_accepted(guest: Guest, profile: GuestProfile, package: str) -> None:
    allowed = [AUTO_PACKAGE, *profile.packages]
    if package not in allowed:
        raise PackageNotAcceptedError(guest.name, package, allowed)


def _requested_guest(guests: Sequence[Guest], name: str, *, gate: bool) -> Guest:
    found = next((guest for guest in guests if guest.name == name), None)
    if found is None:
        raise GuestRefusedError(f"There is no guest named {name}")
    runnable = ("ready",) if gate else ("ready", "testing")
    if found.state not in runnable:
        yet = " yet" if found.state in TRANSIENT_STATES else ""
        raise GuestRefusedError(f"{name} is {found.state}: it cannot run an analysis{yet}")
    return found


def _require_nothing_in_transition(guests: Sequence[Guest]) -> None:
    for state, reason in BLOCKING_STATES.items():
        if any(guest.state == state for guest in guests):
            raise GuestRefusedError(reason)


def _default_guest(guests: Sequence[Guest], preferred: str | None) -> Guest:
    ready = [guest for guest in guests if guest.state == "ready"]
    if not ready:
        states = ", ".join(f"{guest.name} is {guest.state}" for guest in guests)
        raise GuestRefusedError(f"No guest is ready ({states})")
    return next((guest for guest in ready if guest.name == preferred), ready[0])
