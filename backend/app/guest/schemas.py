"""The JSON the guest control service answers with, as the backend (and the GUI) read it.

The control service may grow fields; the models ignore what they do not name. Nothing here is
specific to an operating system: what differs between them arrives as data in `GuestProfile`.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type GuestState = Literal["building", "testing", "ready", "failed", "broken"]
type BuildProgress = Literal["running", "paused", "failed", "succeeded"]
type StepProgress = Literal["pending", "running", "paused", "failed", "succeeded"]


class ControlModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GuestMedia(ControlModel):
    file: str
    variant: str | None = None
    version: str | None = None
    language: str | None = None
    arch: str


class GuestIdentity(ControlModel):
    account: str
    machine: str
    password: str


class GuestResources(ControlModel):
    vcpus: int
    ram_mb: int
    disk_gb: int


class MachineIdentity(ControlModel):
    uuid: str
    mac: str
    smbios_serial: str
    board_serial: str
    disk_serial: str


class Guest(ControlModel):
    """A guest's record. A `broken` one has only a name, the state and the error: its
    `guest.json` could not be read, and it is listed so that it can be seen and deleted."""

    name: str
    state: GuestState
    error: str | None = None
    profile: str | None = None
    kind: str | None = None
    cloned_from: str | None = None
    created: str | None = None
    media: GuestMedia | None = None
    # Secret options (a product key) arrive as "***".
    options: dict[str, Any] = Field(default_factory=dict)
    identity: GuestIdentity | None = None
    resources: GuestResources | None = None
    ip: str | None = None
    machine: MachineIdentity | None = None
    work_dir: str | None = None
    snapshot: str | None = None
    disk_path: str | None = None
    selftest: dict[str, Any] | None = None
    adopted: bool = False
    giveaways: list[str] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)
    build_id: str | None = None


class ProfileResources(ControlModel):
    vcpus: int
    ram_mb: int
    disk_gb: int
    min_disk_gb: int


class ProfileMedia(ControlModel):
    kinds: list[str]


class ProfileOption(ControlModel):
    key: str
    label: str
    type: Literal["bool", "string", "choice", "secret"]
    default: Any = None
    help: str = ""
    choices: list[str] = Field(default_factory=list)
    requires_user_step: bool = False
    changeable_on_clone: bool = False


class IdentityRule(ControlModel):
    label: str
    pattern: str
    reserved: list[str] = Field(default_factory=list)
    generator: str
    optional: bool = True


class ProfileIdentity(ControlModel):
    account: IdentityRule
    machine: IdentityRule
    password: IdentityRule


class ProfileClone(ControlModel):
    computer_name_editable: bool


class BadgeRule(ControlModel):
    option: str
    value: Any
    label: str


class InteractiveOptions(ControlModel):
    options: str
    task_fields: dict[str, bool | int | str] = Field(default_factory=dict)


class ProfileAgent(ControlModel):
    interactive: InteractiveOptions


class GuestProfile(ControlModel):
    """What the GUI renders the build wizard and the guest cards from, for one kind of guest."""

    id: str
    display_name: str
    family: str
    arch: str
    resources: ProfileResources
    media: ProfileMedia
    options: list[ProfileOption]
    identity: ProfileIdentity
    clone: ProfileClone
    badges: list[BadgeRule]
    packages: list[str]
    agent: ProfileAgent


class MediaVariant(ControlModel):
    index: int
    name: str
    edition_id: str | None = None
    arch: str | None = None
    languages: list[str] = Field(default_factory=list)
    default_language: str | None = None
    build: int | None = None
    installation_type: str | None = None


class MediaEntry(ControlModel):
    """One installation medium as one profile read it, or a file nothing recognised (`profile` is
    None and `error` says why)."""

    file: str
    size: int
    mtime: int
    profile: str | None = None
    kind: str | None = None
    variants: list[MediaVariant] = Field(default_factory=list)
    version: str | None = None
    build: int | None = None
    language: str | None = None
    arch: str | None = None
    compression: str | None = None
    sha256: str | None = None
    error: str | None = None


class HealthProbe(ControlModel):
    id: str
    ok: bool
    message: str


class HealthCheckResult(ControlModel):
    name: str
    checks: list[HealthProbe]


class BuildStep(ControlModel):
    name: str
    status: StepProgress
    started: str | None = None
    finished: str | None = None
    exit_code: int | None = None
    weight: int
    timeout_s: int
    desktop: bool
    progress: int


class BuildPause(ControlModel):
    instructions: str


class BuildStatus(ControlModel):
    id: str
    guest: str
    kind: str
    status: BuildProgress
    step: int
    steps: list[BuildStep]
    percent: int
    message: str = ""
    pause: BuildPause | None = None
    # True while the build's current step shows something on the guest's screen.
    desktop: bool = False
    created: str | None = None
    updated: str | None = None


class BuildView(BuildStatus):
    """A build as the GUI shows it: its status and the last lines of its log."""

    log: list[str]


class BuildStarted(BaseModel):
    """What starting, resuming, restarting or continuing a build answers: the job that follows
    the build, which may be one already following it."""

    job_id: int
    build_id: str
    guest: str


class ActiveBuild(BaseModel):
    build_id: str
    guest: str
    job_id: int


class GuestDisplay(ControlModel):
    """Where the guest's screen can be reached inside the control service's container."""

    host: str
    port: int
