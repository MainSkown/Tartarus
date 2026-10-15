"""A stand-in for the container's libvirt and CAPE: the command runner the engine is given.

A guest's domain exists once its `define` step has left the marker `<guest dir>/defined` and its
snapshot once `snapshotted` exists, so the fake profile's steps drive what libvirt "has". Restarting
`cape` reads `guests.conf` the way CAPE does: the machines it lists are what `machines()` returns.
"""

from pathlib import Path
from xml.sax.saxutils import quoteattr

from guest_engine.media import CommandResult

DEFINED = "defined"
SNAPSHOTTED = "snapshotted"
SNAPSHOT = "tartarus-clean"
COMPILER = "fake-cc"


def ok(stdout: str = "") -> CommandResult:
    return CommandResult(0, stdout, "")


def failure(stderr: str) -> CommandResult:
    return CommandResult(1, "", stderr)


class FakeHost:
    def __init__(self, libvirt_dir: Path, guests_root: Path, registration_dir: Path) -> None:
        self.libvirt_dir = libvirt_dir
        self.guests_root = guests_root
        self.registration_dir = registration_dir
        self.calls: list[list[str]] = []
        self.events: list[str] = []
        self.cape_restarts = 0
        self.cape_fails = False
        self.listed: list[str] = []
        self.running: set[str] = set()
        self.undefined: list[str] = []
        self.listed_when_undefined: dict[str, list[str]] = {}
        self.extra_domains: dict[str, str] = {}
        self.compiler_error: str | None = None
        self.outside_file = libvirt_dir.parent / "outside" / "iso-of-the-user.iso"

    def define_elsewhere(self, name: str, xml: str) -> None:
        """A domain libvirt has but no step of ours made (an adopted guest)."""
        self.extra_domains[name] = xml

    def machines(self) -> list[str]:
        return list(self.listed)

    def __call__(self, args, timeout=None) -> CommandResult:
        argv = list(args)
        self.calls.append(argv)
        if argv[:1] == ["virsh"]:
            return self._virsh(argv[3], argv[4:])
        if argv[:2] == ["supervisorctl", "restart"]:
            return self._restart_cape()
        if argv[:1] == [COMPILER]:
            return self._compile(argv)
        if argv[:1] == ["pkill"]:
            self.events.append("pkill tcpdump")
            return CommandResult(1, "", "")
        return failure(f"fake host: unexpected command {argv}")

    def files_of(self, name: str) -> list[Path]:
        images = self.libvirt_dir / "images"
        return [
            images / f"{name}.qcow2",
            images / f"{name}.1792073956",
            images / f"{name}-clean.mem",
            images / f"{name}-clean.qcow2",
            self.libvirt_dir / "nvram" / f"{name}_VARS.fd",
        ]

    def create_files(self, name: str) -> None:
        for path in [*self.files_of(name), self.outside_file]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")

    def _defined(self, name: str) -> bool:
        return (self.guests_root / name / DEFINED).exists() or name in self.extra_domains

    def _virsh(self, command: str, rest: list[str]) -> CommandResult:
        name = rest[0] if rest else ""
        if command == "dominfo":
            return (
                ok("Name: " + name)
                if self._defined(name)
                else failure("error: failed to get domain")
            )
        if not self._defined(name):
            return failure(f"error: failed to get domain '{name}'")
        handler = getattr(self, f"_virsh_{command.replace('-', '_')}", None)
        return handler(name, rest[1:]) if handler else failure(f"fake host: virsh {command}")

    def _virsh_domstate(self, name: str, _rest: list[str]) -> CommandResult:
        return ok("running\n" if name in self.running else "shut off\n")

    def _virsh_dumpxml(self, name: str, _rest: list[str]) -> CommandResult:
        if name in self.extra_domains:
            return ok(self.extra_domains[name])
        base, overlay, nvram = (
            self.files_of(name)[0],
            self.files_of(name)[1],
            self.files_of(name)[4],
        )
        return ok(
            f"<domain><name>{name}</name><os><nvram>{nvram}</nvram></os><devices>"
            f"<disk device='disk'><source file={quoteattr(str(overlay))}/>"
            f"<backingStore type='file'><source file={quoteattr(str(base))}/></backingStore></disk>"
            f"<disk device='cdrom'><source file={quoteattr(str(self.outside_file))}/></disk>"
            "</devices></domain>"
        )

    def _virsh_snapshot_list(self, name: str, _rest: list[str]) -> CommandResult:
        snapshotted = (self.guests_root / name / SNAPSHOTTED).exists()
        return ok(f"{SNAPSHOT}\n\n" if snapshotted else "\n")

    def _virsh_snapshot_dumpxml(self, name: str, _rest: list[str]) -> CommandResult:
        memory, overlay = self.files_of(name)[2], self.files_of(name)[3]
        return ok(
            f"<domainsnapshot><name>{SNAPSHOT}</name>"
            f"<memory snapshot='external' file={quoteattr(str(memory))}/>"
            f"<disks><disk name='sda'><source file={quoteattr(str(overlay))}/></disk></disks>"
            "</domainsnapshot>"
        )

    def _virsh_snapshot_revert(self, name: str, _rest: list[str]) -> CommandResult:
        self.events.append(f"revert {name}")
        self.running.add(name)
        return ok()

    def _virsh_destroy(self, name: str, _rest: list[str]) -> CommandResult:
        self.events.append(f"destroy {name}")
        self.running.discard(name)
        return ok()

    def _virsh_undefine(self, name: str, _rest: list[str]) -> CommandResult:
        self.events.append(f"undefine {name}")
        self.undefined.append(name)
        self.listed_when_undefined[name] = list(self.listed)
        (self.guests_root / name / DEFINED).unlink(missing_ok=True)
        self.extra_domains.pop(name, None)
        return ok()

    def _virsh_domdisplay(self, name: str, _rest: list[str]) -> CommandResult:
        if name not in self.running:
            return failure("error: domain is not running")
        return ok("vnc://127.0.0.1:1\n")

    def _compile(self, argv: list[str]) -> CommandResult:
        """The sample build: `fake-cc <source> -o <output>` copies the source to the output."""
        if self.compiler_error:
            return failure(self.compiler_error)
        Path(argv[argv.index("-o") + 1]).write_bytes(b"built from: " + Path(argv[1]).read_bytes())
        return ok()

    def _restart_cape(self) -> CommandResult:
        self.cape_restarts += 1
        self.events.append("restart cape")
        if self.cape_fails:
            return failure("cape: ERROR (spawn error)")
        registration = self.registration_dir / "guests.conf"
        self.listed = _machines_in(registration.read_text()) if registration.exists() else []
        return ok("cape: stopped\ncape: started\n")


def _machines_in(text: str) -> list[str]:
    for line in text.splitlines():
        if line.startswith("machines ="):
            return [name.strip() for name in line.partition("=")[2].split(",") if name.strip()]
    return []
