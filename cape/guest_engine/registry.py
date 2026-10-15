"""Guest records: one directory per guest under the registry root, `guests/<name>/guest.json`.

`guest.json` is the single source of truth for a guest; the libvirt domain, the CAPE registration
and the backend's view are derived from it. The sequencer's `state.json` lives beside it and is not
touched here.
"""

import configparser
import ipaddress
import json
import os
import random
import shutil
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Collection
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters
from guest_engine.giveaways import find_giveaway
from guest_engine.names import UPPER_ALNUM, generate
from guest_engine.profile import SLUG, MediaRef, Profile

GUEST_FILE = "guest.json"
SNAPSHOT_NAME = "tartarus-clean"
MAX_GUESTS = 5
STATES = ("building", "testing", "ready", "failed")
KINDS = ("build", "clone")
FIRST_HOST, LAST_HOST = 10, 99
NIC_OUI = "00:14:22"
DISK_SERIAL_PREFIX = "S4EWNX0"
KIB_PER_MIB = 1024


@dataclass(frozen=True)
class GuestIdentity:
    account: str
    machine: str
    password: str


@dataclass(frozen=True)
class GuestResources:
    vcpus: int
    ram_mb: int
    disk_gb: int


@dataclass(frozen=True)
class MachineIdentity:
    uuid: str
    mac: str
    smbios_serial: str
    board_serial: str
    disk_serial: str


@dataclass(frozen=True)
class GuestSpec:
    """What was asked for, fully resolved and validated; `new_guest` adds what is generated."""

    name: str
    profile: str
    kind: str
    cloned_from: str | None
    media: MediaRef
    options: dict[str, Any]
    identity: GuestIdentity
    resources: GuestResources
    work_dir: str | None = None


@dataclass(frozen=True)
class Guest:
    name: str
    profile: str
    kind: str
    cloned_from: str | None
    state: str
    created: str
    media: MediaRef
    options: dict[str, Any]
    identity: GuestIdentity
    resources: GuestResources
    ip: str
    machine: MachineIdentity
    work_dir: str
    snapshot: str
    disk_path: str | None = None
    selftest: dict[str, Any] | None = None
    adopted: bool = False
    giveaways: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["giveaways"] = list(self.giveaways)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Guest":
        return cls(
            **{
                **data,
                "media": MediaRef(**data["media"]),
                "identity": GuestIdentity(**data["identity"]),
                "resources": GuestResources(**data["resources"]),
                "machine": MachineIdentity(**data["machine"]),
                "giveaways": tuple(data.get("giveaways", ())),
            }
        )


def _timestamp(now: datetime | None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alphanumerics(rng: random.Random, length: int) -> str:
    return "".join(rng.choices(UPPER_ALNUM, k=length))


def generate_machine_identity(rng: random.Random | None = None) -> MachineIdentity:
    """A Dell-style machine identity (service tag, board and disk serials, Dell NIC OUI)."""
    source = rng or random.SystemRandom()
    serial = _alphanumerics(source, 7)
    host_bytes = ":".join(f"{source.randrange(256):02x}" for _ in range(3))
    return MachineIdentity(
        uuid=str(uuid.UUID(int=source.getrandbits(128), version=4)),
        mac=f"{NIC_OUI}:{host_bytes}",
        smbios_serial=serial,
        board_serial=f"/{serial}/CN{_alphanumerics(source, 12)}/",
        disk_serial=f"{DISK_SERIAL_PREFIX}{_alphanumerics(source, 6)}",
    )


def new_work_dir(profile: Profile, rng: random.Random | None = None) -> str:
    """A neutral per-guest working folder under the profile's work root (decision 16)."""
    return profile.agent.work_root + profile.agent.path_separator + generate("folder_name", rng)


def new_guest(
    spec: GuestSpec,
    profile: Profile,
    ip: str,
    *,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> Guest:
    return Guest(
        name=spec.name,
        profile=spec.profile,
        kind=spec.kind,
        cloned_from=spec.cloned_from,
        state="building",
        created=_timestamp(now),
        media=spec.media,
        options=spec.options,
        identity=spec.identity,
        resources=spec.resources,
        ip=ip,
        machine=generate_machine_identity(rng),
        work_dir=spec.work_dir or new_work_dir(profile, rng),
        snapshot=SNAPSHOT_NAME,
    )


def next_free_ip(subnet: str, taken: Collection[str]) -> str:
    """The lowest unused address from `.10` to `.99` of the /24 `subnet`."""
    network = ipaddress.ip_network(subnet)
    candidates = [network.network_address + host for host in range(FIRST_HOST, LAST_HOST + 1)]
    for candidate in candidates:
        if str(candidate) not in taken:
            return str(candidate)
    raise Conflict(f"no free guest address between {candidates[0]} and {candidates[-1]}")


def write_atomically(path: Path, text: str, mode: int = 0o644) -> None:
    """Replace `path` with `text` so a reader sees the old file or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Registry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _file(self, name: str) -> Path:
        if not SLUG.fullmatch(name):
            raise GuestNotFound(name)
        return self.root / name / GUEST_FILE

    def _write(self, guest: Guest) -> None:
        text = json.dumps(guest.to_dict(), indent=2) + "\n"
        write_atomically(self.root / guest.name / GUEST_FILE, text, mode=0o600)

    def exists(self, name: str) -> bool:
        return SLUG.fullmatch(name) is not None and self._file(name).is_file()

    def create(self, guest: Guest) -> Guest:
        if not SLUG.fullmatch(guest.name):
            raise InvalidParameters(
                {"name": "must be 2 to 32 lower-case letters, digits or hyphens"}
            )
        if self.exists(guest.name):
            raise Conflict(f"a guest named {guest.name} already exists")
        self._write(guest)
        return guest

    def get(self, name: str) -> Guest:
        try:
            return Guest.from_dict(json.loads(self._file(name).read_text()))
        except FileNotFoundError:
            raise GuestNotFound(name) from None

    def list(self) -> list[Guest]:
        if not self.root.is_dir():
            return []
        guests = [self.get(path.name) for path in self.root.iterdir() if self.exists(path.name)]
        return sorted(guests, key=lambda guest: (guest.created, guest.name))

    def update(self, name: str, **changes: Any) -> Guest:
        if "state" in changes and changes["state"] not in STATES:
            raise InvalidParameters({"state": f"must be one of {', '.join(STATES)}"})
        guest = replace(self.get(name), **changes)
        self._write(guest)
        return guest

    def update_state(self, name: str, state: str) -> Guest:
        return self.update(name, state=state)

    def store_selftest(self, name: str, result: dict[str, Any]) -> Guest:
        return self.update(name, selftest=result)

    def delete(self, name: str) -> None:
        self.get(name)
        shutil.rmtree(self.root / name)

    def allocate_ip(self, subnet: str) -> str:
        return next_free_ip(subnet, {guest.ip for guest in self.list()})

    def adopt(
        self, domain_xml: str, registration: str, profile: Profile, now: datetime | None = None
    ) -> Guest:
        """Record an existing guest once; adopting it again returns the record unchanged."""
        guest = adopt(domain_xml, registration, profile, now=now)
        if self.exists(guest.name):
            return self.get(guest.name)
        return self.create(guest)


def _domain_text(domain: ET.Element, path: str) -> str:
    text = domain.findtext(path)
    if not text:
        raise ValueError(f"the domain XML has no {path}")
    return text


def _base_disk_path(domain: ET.Element) -> str:
    # A revert leaves a new overlay on top of the base image, which is the file a clone copies.
    layer: ET.Element | None = domain.find("devices/disk[@device='disk']")
    path = ""
    while layer is not None:
        source = layer.find("source")
        if source is None:
            break
        path = source.get("file", path)
        layer = layer.find("backingStore")
    if not path:
        raise ValueError("the domain XML has no system disk")
    return path


def _registered_machine(
    registration: str, domain_name: str, profile: Profile
) -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read_string(registration)
    machines = [
        name.strip()
        for name in parser.get("kvm", "machines", fallback="").split(",")
        if name.strip()
    ]
    if len(machines) != 1:
        raise ValueError(
            f"the registration must list exactly one machine to adopt, not {len(machines)}"
        )
    section = parser[machines[0]]
    if section["label"] != domain_name:
        raise ValueError(
            f"the registration is for '{section['label']}', the domain is '{domain_name}'"
        )
    if section["platform"] != profile.cape.platform:
        raise ValueError(f"the registration's platform {section['platform']} is not {profile.id}'s")
    return section


def _carried_giveaways(guest: Guest) -> tuple[str, ...]:
    fields = {
        "identity.account": guest.identity.account,
        "identity.machine": guest.identity.machine,
        "identity.password": guest.identity.password,
        "work_dir": guest.work_dir,
    }
    return tuple(
        f"{field} '{value}' contains '{word}'"
        for field, value in fields.items()
        if (word := find_giveaway(value))
    )


def adopt(
    domain_xml: str, registration: str, profile: Profile, now: datetime | None = None
) -> Guest:
    """Describe a guest that exists already from its `virsh dumpxml` and registration file."""
    if profile.adoption is None:
        raise ValueError(f"profile {profile.id} has no adoption data")
    domain = ET.fromstring(domain_xml)  # noqa: S314
    name = _domain_text(domain, "name")
    section = _registered_machine(registration, name, profile)
    adoption = profile.adoption
    guest = Guest(
        name=name,
        profile=profile.id,
        kind="build",
        cloned_from=None,
        state="ready",
        created=_timestamp(now),
        media=adoption.media,
        options={**profile.option_defaults(), **adoption.options},
        identity=GuestIdentity(adoption.account, adoption.machine, adoption.password),
        resources=GuestResources(
            vcpus=int(_domain_text(domain, "vcpu")),
            ram_mb=int(_domain_text(domain, "memory")) // KIB_PER_MIB,
            disk_gb=profile.resources.disk_gb,
        ),
        ip=section["ip"],
        machine=MachineIdentity(
            uuid=_domain_text(domain, "uuid"),
            mac=_attribute(domain, "devices/interface/mac", "address"),
            smbios_serial=_domain_text(domain, "sysinfo/system/entry[@name='serial']"),
            board_serial=_domain_text(domain, "sysinfo/baseBoard/entry[@name='serial']"),
            disk_serial=_domain_text(domain, "devices/disk[@device='disk']/serial"),
        ),
        work_dir=adoption.work_dir,
        snapshot=section["snapshot"],
        disk_path=_base_disk_path(domain),
        adopted=True,
    )
    return replace(guest, giveaways=_carried_giveaways(guest))


def _attribute(domain: ET.Element, path: str, attribute: str) -> str:
    element = domain.find(path)
    value = element.get(attribute) if element is not None else None
    if not value:
        raise ValueError(f"the domain XML has no {path}/@{attribute}")
    return value
