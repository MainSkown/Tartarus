from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

type Route = Literal["none", "drop", "internet", "inetsim", "tor", "vpn", "wireguard", "socks5"]


class SettingsBody(BaseModel):
    default_route: Route = "inetsim"
    default_timeout: int = Field(default=180, ge=60, le=1200)
    default_interactive: bool = True
    # Declared before disk_warn_gb: the warn validator reads it from already-validated data.
    disk_block_gb: int = Field(default=20, gt=0)
    disk_warn_gb: int = Field(default=50, gt=0)

    @field_validator("disk_warn_gb")
    @classmethod
    def warn_fires_before_block(cls, warn: int, info: ValidationInfo) -> int:
        block = info.data.get("disk_block_gb")
        if block is not None and warn <= block:
            raise ValueError("must be greater than disk_block_gb")
        return warn
