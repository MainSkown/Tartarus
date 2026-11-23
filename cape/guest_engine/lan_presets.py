"""LAN presets: the fake hosts of a simulated local network, as validated data.

A preset is `<presets dir>/<id>.json`. The control service, the firewall and the fake-host daemon
all read presets through `load_presets`, so a bad file stops at load time and never reaches one of
them: a name INetSim's `dns_static` refuses would stop every INetSim service.
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guest_engine.lan_block import address_at, block_of
from guest_engine.profile import SLUG, _Reader

DEFAULT_PORTS = {"smb": 445, "rdp": 3389, "winrm": 5985, "ssh": 22, "ldap": 389, "mssql": 1433}
MAX_PORT = 65535
IMPLIED_SMB_SHARES = ("ADMIN$", "C$", "IPC$")

SHARE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.$-]{0,79}")
SSH_BANNER = re.compile(r"[\x20-\x7e]{1,200}")
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


@dataclass(frozen=True)
class Account:
    user: str
    password: str


@dataclass(frozen=True)
class Service:
    kind: str
    port: int
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Host:
    fqdn: str
    host_offset: int
    address: str
    role: str
    os_banner: str
    accounts: tuple[Account, ...]
    services: tuple[Service, ...]

    def serves(self, kind: str) -> bool:
        return any(service.kind == kind for service in self.services)

    def public(self) -> dict[str, Any]:
        return {
            "fqdn": self.fqdn,
            "address": self.address,
            "role": self.role,
            "services": [{"kind": service.kind, "port": service.port} for service in self.services],
        }


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    description: str
    domain: str
    hosts: tuple[Host, ...]

    def public(self) -> dict[str, Any]:
        """What the API shows an analyst: never an account, a password or a service option."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "hosts": [host.public() for host in self.hosts],
        }


class PresetError(ValueError):
    """A preset is unusable; `problems` maps each field path to why, `source` is the file."""

    def __init__(self, source: str, problems: dict[str, str]) -> None:
        details = "; ".join(
            f"{path}: {reason}" if path else reason for path, reason in problems.items()
        )
        super().__init__(f"{source}: {details}")
        self.source = source
        self.problems = problems


def dns_records(presets: Iterable[Preset]) -> list[tuple[str, str]]:
    """Every host as an (fqdn, address) pair, for INetSim's `dns_static`."""
    return [(host.fqdn, host.address) for preset in presets for host in preset.hosts]


def load_presets(directory: Path, subnet: str) -> list[Preset]:
    """Load every `*.json` in `directory`, resolving host offsets against `subnet`.

    Raises `PresetError` naming the first bad file; raises `ValueError` if `subnet` cannot hold
    the fake LAN block.
    """
    block_of(subnet)
    if not directory.is_dir():
        raise PresetError(str(directory), {"": "is not a directory"})
    presets = {
        file: _parse_preset(_read_json(file), file, subnet)
        for file in sorted(directory.glob("*.json"))
        if not file.name.startswith(".")
    }
    _check_unique(presets)
    return list(presets.values())


def _read_json(file: Path) -> object:
    try:
        return json.loads(file.read_text())
    except OSError as error:
        raise PresetError(str(file), {"": f"cannot be read ({error.strerror})"}) from None
    except json.JSONDecodeError as error:
        raise PresetError(str(file), {"": f"not valid JSON ({error})"}) from None


def _parse_preset(data: object, file: Path, subnet: str) -> Preset:
    problems: dict[str, str] = {}
    reader = _Reader(data, "", problems)
    preset_id = reader.string("id", rule=SLUG)
    if preset_id and preset_id != file.stem:
        reader.fail("id", f"'{preset_id}' does not match its file name '{file.stem}'")
    domain = reader.string("domain")
    _check_fqdn(reader, "domain", domain)
    preset = Preset(
        id=preset_id,
        name=reader.string("name"),
        description=reader.string("description"),
        domain=domain,
        hosts=tuple(
            _host(host, domain, subnet) for host in reader.objects("hosts", non_empty=True)
        ),
    )
    reader.done()
    if problems:
        raise PresetError(str(file), problems)
    return preset


def _fqdn_problem(name: str) -> str | None:
    if "." not in name:
        return "must have at least two labels (INetSim's dns_static refuses a single-label name)"
    if name != name.lower():
        return "must be lower case"
    if "_" in name:
        return "must not contain an underscore (INetSim's dns_static refuses it)"
    if not all(DNS_LABEL.fullmatch(label) for label in name.split(".")):
        return "may hold only a-z, 0-9 and hyphens in each label, none starting or ending with one"
    return None


def _check_fqdn(reader: _Reader, key: str, name: str) -> None:
    if name and (problem := _fqdn_problem(name)):
        reader.fail(key, problem)


def _host(reader: _Reader, domain: str, subnet: str) -> Host:
    fqdn = reader.string("fqdn")
    _check_fqdn(reader, "fqdn", fqdn)
    if domain and not fqdn.endswith(f".{domain}"):
        reader.fail("fqdn", f"must end in the preset's domain .{domain}")
    offset = reader.integer("host_offset", minimum=0)
    host = Host(
        fqdn=fqdn,
        host_offset=offset,
        address=_resolve(reader, offset, subnet),
        role=reader.string("role", rule=SLUG),
        os_banner=reader.string("os_banner"),
        accounts=_accounts(reader),
        services=_services(reader),
    )
    reader.done()
    if host.serves("smb") and not host.accounts:
        reader.fail("accounts", "a host that serves smb needs at least one account")
    return host


def _resolve(reader: _Reader, offset: int, subnet: str) -> str:
    try:
        return address_at(subnet, offset)
    except ValueError as error:
        reader.fail("host_offset", str(error))
        return ""


def _accounts(reader: _Reader) -> tuple[Account, ...]:
    accounts = []
    for index, account in enumerate(reader.optional_objects("accounts")):
        user = account.string("user")
        accounts.append(Account(user=user, password=account.string("password")))
        account.done()
        if user and user in [earlier.user for earlier in accounts[:-1]]:
            reader.fail(f"accounts[{index}]", f"'{user}' is listed twice")
    return tuple(accounts)


def _services(reader: _Reader) -> tuple[Service, ...]:
    services: list[Service] = []
    for index, service in enumerate(reader.objects("services", non_empty=True)):
        kind = service.choice("kind", list(DEFAULT_PORTS))
        port = service.integer("port", minimum=1, maximum=MAX_PORT)
        services.append(Service(kind=kind, port=port, options=_options(service, kind)))
        service.done()
        taken_by = next(
            (i for i, earlier in enumerate(services[:-1]) if earlier.port == port), None
        )
        if port and taken_by is not None:
            reader.fail(
                f"services[{index}].port", f"{port} is already served by services[{taken_by}]"
            )
    return tuple(services)


def _options(service: _Reader, kind: str) -> dict[str, Any]:
    reader = service.optional_object("options")
    if reader is None:
        return {}
    options: dict[str, Any] = {}
    if kind == "smb":
        options["shares"] = _shares(reader)
    if kind == "ssh" and (banner := reader.optional_string("banner", rule=SSH_BANNER)):
        options["banner"] = banner
    reader.done()
    return {key: value for key, value in options.items() if value}


def _shares(reader: _Reader) -> list[str]:
    shares = reader.string_list("shares", rule=SHARE_NAME, default=[])
    for index, share in enumerate(shares):
        if share.upper() in IMPLIED_SMB_SHARES:
            reader.fail(f"shares[{index}]", f"{share.upper()} is implied, do not list it")
    return shares


def _check_unique(presets: Mapping[Path, Preset]) -> None:
    fqdn_owner: dict[str, str] = {}
    address_owner: dict[str, str] = {}
    for file, preset in presets.items():
        problems: dict[str, str] = {}
        for index, host in enumerate(preset.hosts):
            here = f"{file.name} hosts[{index}]"
            if (other := fqdn_owner.setdefault(host.fqdn, here)) != here:
                problems[f"hosts[{index}].fqdn"] = f"'{host.fqdn}' is also used by {other}"
            if (other := address_owner.setdefault(host.address, here)) != here:
                problems[f"hosts[{index}].host_offset"] = (
                    f"address {host.address} is also used by {other}"
                )
        if problems:
            raise PresetError(str(file), problems)
