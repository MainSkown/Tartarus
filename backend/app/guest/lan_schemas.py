"""The fake local network as the guest control service answers about it.

Like the rest of the control service's JSON, the models ignore fields they do not name.
"""

from pydantic import Field

from app.guest.schemas import ControlModel


class LanService(ControlModel):
    kind: str
    port: int


class LanHost(ControlModel):
    fqdn: str
    address: str
    role: str
    services: list[LanService]


class LanPreset(ControlModel):
    """A set of fake hosts an analysis can ask for; `GET /lan-presets` lists them."""

    id: str = Field(description="The id to put in an analysis's `lan_preset` option.")
    name: str
    description: str
    hosts: list[LanHost]


class LanPresetList(ControlModel):
    presets: list[LanPreset]


class LanHealth(ControlModel):
    """Whether fake hosts can be started now; `reason` says why not."""

    ready: bool
    reason: str | None = None


class LanSessionKeys(ControlModel):
    keys: list[str]


class LanSessionOpened(ControlModel):
    key: str


class LanSessionClosed(ControlModel):
    copied: bool
