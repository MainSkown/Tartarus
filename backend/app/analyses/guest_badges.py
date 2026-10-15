from collections.abc import Iterable

from app.guest.errors import GuestControlError
from app.guest.health import GuestLister


async def badges_by_guest(
    control: GuestLister, names: Iterable[str | None]
) -> dict[str, list[str]]:
    """The badges the control service gives each guest, by guest name.

    Empty when none of `names` is a guest (no call is made) or when the service cannot be asked:
    a badge is decoration and never a reason to fail a read.
    """
    if not any(names):
        return {}
    try:
        guests = await control.guests()
    except GuestControlError:
        return {}
    return {guest.name: guest.badges for guest in guests}
