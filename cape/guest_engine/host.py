"""What the engine does to libvirt and to `cape`, through the injected command runner."""

import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from guest_engine.media import CommandResult, Runner
from guest_engine.media.errors import MediaProblem

COMMAND_NOT_FOUND = 127
VNC_BASE_PORT = 5900
LOCAL_HOST = "127.0.0.1"
WILDCARD_HOSTS = ("0.0.0.0", "::")  # noqa: S104 - a listen address to translate, never one we bind
CAPE_PROGRAM = "cape"
SNIFFER = "tcpdump"
# `virsh undefine` leaves the nvram, the swtpm state and the snapshot metadata unless asked.
UNDEFINE_FLAGS = ("--nvram", "--tpm", "--snapshots-metadata")


class HostError(RuntimeError):
    """A command the engine needs failed; the message says which and why."""


def files_referenced_by(xml: str) -> list[Path]:
    """Every disk, memory and nvram file that a domain's or snapshot's XML names."""
    try:
        root = ET.fromstring(xml)  # noqa: S314 - libvirt's own output
    except ET.ParseError:
        return []
    paths = [
        element.get("file")
        for element in root.iter()
        if element.tag in ("source", "memory") and element.get("file")
    ]
    paths += [element.text.strip() for element in root.iter("nvram") if element.text]
    return [Path(path) for path in dict.fromkeys(paths) if path]


def guest_files(libvirt_dir: Path, name: str) -> list[Path]:
    """The files a build of `name` lays down under the fixed names its step scripts use.

    Undefining a domain forgets the files it named, so a build whose domain is already gone, or
    never existed, would otherwise leave its disk and firmware behind.
    """
    images, nvram = libvirt_dir / "images", libvirt_dir / "nvram"
    return [
        images / f"{name}.qcow2",
        images / f"{name}-clean.mem",
        images / f"{name}-clean.qcow2",
        nvram / f"{name}_VARS.fd",
    ]


def parse_display(printed: str) -> dict[str, str | int] | None:
    """`{host, port}` from `virsh domdisplay` (`vnc://127.0.0.1:1` is display 1, port 5901)."""
    parts = urlsplit(printed.strip())
    if parts.scheme != "vnc":
        return None
    try:
        display = parts.port
    except ValueError:
        return None
    if display is None or not parts.hostname:
        return None
    host = LOCAL_HOST if parts.hostname in WILDCARD_HOSTS else parts.hostname
    return {"host": host, "port": VNC_BASE_PORT + display if display < VNC_BASE_PORT else display}


class Host:
    def __init__(self, runner: Runner, libvirt_uri: str) -> None:
        self._runner = runner
        self._uri = libvirt_uri

    def domain_exists(self, name: str) -> bool:
        return self._virsh("dominfo", name).returncode == 0

    def is_running(self, name: str) -> bool:
        result = self._virsh("domstate", name)
        return result.returncode == 0 and result.stdout.strip().startswith("running")

    def snapshot_names(self, name: str) -> list[str]:
        result = self._virsh("snapshot-list", name, "--name")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def domain_xml(self, name: str, inactive: bool = False) -> str | None:
        flags = ["--inactive"] if inactive else []
        result = self._virsh("dumpxml", name, *flags)
        return result.stdout if result.returncode == 0 else None

    def snapshot_xml(self, name: str, snapshot: str) -> str | None:
        result = self._virsh("snapshot-dumpxml", name, snapshot)
        return result.stdout if result.returncode == 0 else None

    def current_snapshot(self, name: str) -> str | None:
        result = self._virsh("snapshot-current", name, "--name")
        return result.stdout.strip() or None if result.returncode == 0 else None

    def define(self, xml: str) -> None:
        self._require(self._virsh_with_file("define", xml), "define a domain")

    def redefine_snapshot(self, name: str, xml: str, keep_current: bool) -> None:
        """Replace a snapshot's metadata only; no disk or memory file is touched."""
        flags = ["--redefine", *(["--current"] if keep_current else [])]
        self._require(
            self._virsh_with_file("snapshot-create", xml, name, flags),
            f"redefine a snapshot of {name}",
        )

    def owned_files(self, name: str) -> list[Path]:
        """The files of the domain and of all its snapshots, read before they are undefined."""
        documents = [self.domain_xml(name) or ""]
        for snapshot in self.snapshot_names(name):
            result = self._virsh("snapshot-dumpxml", name, snapshot)
            documents.append(result.stdout if result.returncode == 0 else "")
        paths = [path for document in documents for path in files_referenced_by(document)]
        return list(dict.fromkeys(paths))

    def display(self, name: str) -> dict[str, str | int] | None:
        result = self._virsh("domdisplay", name)
        return parse_display(result.stdout) if result.returncode == 0 else None

    def revert(self, name: str, snapshot: str) -> None:
        self._require(self._virsh("snapshot-revert", name, snapshot), f"revert {name}")

    def destroy(self, name: str) -> None:
        self._virsh("destroy", name)

    def undefine(self, name: str) -> None:
        if not self.domain_exists(name):
            return
        self._require(self._virsh("undefine", name, *UNDEFINE_FLAGS), f"undefine {name}")

    def restart_cape(self) -> None:
        self._require(self._run(["supervisorctl", "restart", CAPE_PROGRAM]), "restart cape")
        # The sniffer of a task that the restart cut short outlives it (S0b).
        self._run(["pkill", "-x", SNIFFER])

    def _virsh_with_file(
        self, command: str, text: str, domain: str | None = None, flags: Sequence[str] = ()
    ) -> CommandResult:
        with tempfile.NamedTemporaryFile("w", suffix=".xml") as file:
            file.write(text)
            file.flush()
            arguments = [command, *([domain] if domain else []), file.name, *flags]
            return self._virsh(*arguments)

    def _virsh(self, *arguments: str) -> CommandResult:
        return self._run(["virsh", "-c", self._uri, *arguments])

    def _run(self, command: Sequence[str]) -> CommandResult:
        try:
            return self._runner(command)
        except MediaProblem as problem:
            return CommandResult(COMMAND_NOT_FOUND, "", f"{command[0]}: {problem.fault}")

    @staticmethod
    def _require(result: CommandResult, what: str) -> None:
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise HostError(f"could not {what}: {detail}")
