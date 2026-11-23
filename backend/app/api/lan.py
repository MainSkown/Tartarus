from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_guest_control
from app.guest.client import GuestControl
from app.guest.lan_schemas import LanPreset

router = APIRouter(prefix="/lan-presets", tags=["lan"])


@router.get("", name="presets_list")
async def presets_list(
    control: Annotated[GuestControl, Depends(get_guest_control)],
) -> list[LanPreset]:
    """The fake local networks a sample can be run against, with each preset's hosts: name,
    address, role and the services it answers on. The `id` of one goes in an analysis's
    `lan_preset` option. `502` when the guest control service is not reachable.
    """
    return await control.lan_presets()
