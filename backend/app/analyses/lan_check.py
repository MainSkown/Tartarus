"""The submit-time refusals of a fake-LAN preset: one the control service does not offer, or fake
hosts that cannot be started now.
"""

from typing import Protocol

from app.guest.lan_schemas import LanHealth, LanPreset


class LanPresetUnknownError(Exception):
    """The control service offers no preset with that id; the message lists the ones it does."""


class LanNotReadyError(Exception):
    """The fake hosts cannot be started now; the message gives the control service's reason."""


class LanDirectory(Protocol):
    """The part of the guest control service that checking a preset needs."""

    async def lan_presets(self) -> list[LanPreset]: ...

    async def lan_health(self) -> LanHealth: ...


async def require_lan_ready(lan: LanDirectory, preset_id: str) -> None:
    """Raises `LanPresetUnknownError` or `LanNotReadyError`, and `GuestControlError` when the
    control service cannot be asked; the preset is checked first, as the cheaper mistake to fix.
    """
    offered = [preset.id for preset in await lan.lan_presets()]
    if preset_id not in offered:
        raise LanPresetUnknownError(
            f"There is no fake local network preset {preset_id!r}; the presets are "
            f"{', '.join(offered) or 'none'}"
        )
    health = await lan.lan_health()
    if not health.ready:
        raise LanNotReadyError(
            f"The fake local network is not ready: {health.reason or 'no reason was given'}"
        )
