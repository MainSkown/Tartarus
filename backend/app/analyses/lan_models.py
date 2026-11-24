"""The shape of `summary.lan`, apart from the code that fills it so that `summary` can name it
without importing the ingest.
"""

from datetime import datetime

from pydantic import BaseModel


class LanPresetRef(BaseModel):
    id: str
    name: str


class LanServiceUse(BaseModel):
    """A service of a fake host the sample reached. `service` is None for a port the host does not
    serve (a scan that connected to a closed port); `port` is None for a flood aggregate whose
    service the preset does not list.
    """

    service: str | None
    port: int | None
    attempts: int
    first: datetime
    last: datetime


class LanCredential(BaseModel):
    """One (user, domain, mechanism) the sample tried on a host.

    `secret_as_sent` is the first secret the sample sent with it, exactly as sent: it is the
    sample's password or hash, never one of ours. `count` is the attempts logged one by one; a user
    only a flood aggregate named has 0, and the aggregate's first secret, which names no user, is
    an entry with an empty `user`.
    """

    user: str
    domain: str
    mechanism: str
    count: int
    success: bool
    secret_as_sent: str | None


class LanWrittenFile(BaseModel):
    path: str
    share: str
    size: int | None
    sha256: str | None


class LanHostSummary(BaseModel):
    fqdn: str
    address: str
    role: str
    services: list[LanServiceUse]
    credentials: list[LanCredential]
    credentials_more: int = 0
    files: list[LanWrittenFile]
    files_more: int = 0
    first: datetime
    last: datetime


class LanTotals(BaseModel):
    hosts: int
    attempts: int
    credentials: int
    files: int


class LanSummary(BaseModel):
    """`summary.lan`. Stored only when the analysis asked for a fake LAN; with no `hosts` the
    sample did nothing on it. `truncated` is the daemon's own word that it stopped logging.
    """

    preset: LanPresetRef
    hosts: list[LanHostSummary]
    totals: LanTotals
    truncated: bool = False


def empty_lan_summary(preset_id: str) -> LanSummary:
    """For a run that asked for a preset whose hosts could not be looked up: nothing is known."""
    return LanSummary(
        preset=LanPresetRef(id=preset_id, name=preset_id),
        hosts=[],
        totals=LanTotals(hosts=0, attempts=0, credentials=0, files=0),
    )
