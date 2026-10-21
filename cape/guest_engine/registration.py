"""The single `guests.conf` that registers every testing and ready guest with CAPE's kvm module."""

from collections.abc import Iterable, Mapping
from pathlib import Path

from guest_engine.errors import Conflict, GuestNotFound
from guest_engine.profile import Profile
from guest_engine.registry import Guest, write_atomically

REGISTRATION_FILE = "guests.conf"
REGISTERED_STATES = ("testing", "ready")
INTERFACE = "tt-guest"


def _section(guest: Guest, profile: Profile) -> str:
    return (
        f"[{guest.name}]\n"
        f"label = {guest.name}\n"
        f"platform = {profile.cape.platform}\n"
        f"ip = {guest.ip}\n"
        f"snapshot = {guest.snapshot}\n"
        f"arch = {profile.arch}\n"
        f"interface = {INTERFACE}\n"
        f"tags = {','.join(profile.cape.tags_for(guest.media.version))}\n"
    )


def _refuse_shared_addresses(guests: list[Guest]) -> None:
    owners: dict[str, str] = {}
    for guest in guests:
        if guest.ip in owners:
            raise Conflict(f"{owners[guest.ip]} and {guest.name} both have the address {guest.ip}")
        owners[guest.ip] = guest.name


def render_registration(guests: Iterable[Guest], profiles: Mapping[str, Profile]) -> str:
    """The text of `guests.conf` for the testing and ready guests, in name order.

    Raises `Conflict` when two of them share an address (CAPE accepts that silently and then
    cannot tell them apart) and `GuestNotFound` for a guest whose profile is not installed.
    """
    registered = sorted(
        (guest for guest in guests if guest.state in REGISTERED_STATES), key=lambda g: g.name
    )
    _refuse_shared_addresses(registered)
    names = ",".join(guest.name for guest in registered)
    # `machines =` with nothing after it is what cape/conf/kvm.conf ships: CAPE waits for a guest.
    machines = f"machines = {names}" if names else "machines ="
    header = f"[kvm]\n{machines}\n"
    sections = []
    for guest in registered:
        if guest.profile not in profiles:
            raise GuestNotFound(f"profile {guest.profile} of guest {guest.name} is not installed")
        sections.append(_section(guest, profiles[guest.profile]))
    return "\n".join([header, *sections])


def apply_registration(directory: Path, text: str) -> list[str]:
    """Write `guests.conf` and remove every other `*.conf`; return the names removed.

    CAPE merges all `*.conf` files of the directory in sorted order and the last `machines` key
    wins, so a leftover file silently un-registers guests.
    """
    write_atomically(directory / REGISTRATION_FILE, text)
    removed = sorted(
        path.name for path in directory.glob("*.conf") if path.name != REGISTRATION_FILE
    )
    for name in removed:
        (directory / name).unlink()
    return removed
