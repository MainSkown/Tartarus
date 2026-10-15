"""Finding, and clearing away, the processes a test left running under its temporary folder."""

import os
import signal
from pathlib import Path


def processes_running_under(directory: Path) -> dict[int, str]:
    """Pid and command line of each live process whose arguments mention `directory`."""
    needle = str(directory).encode()
    found = {}
    for cmdline_file in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            arguments = cmdline_file.read_bytes()
        except OSError:
            continue
        if needle in arguments:
            command = arguments.replace(b"\0", b" ").decode(errors="replace").strip()
            found[int(cmdline_file.parent.name)] = command
    return found


def has_child_processes() -> bool:
    """Whether this process has a child, the cheap precondition of any leak: a test's steps and
    helpers are its children until their parent dies, and listing /proc takes tens of milliseconds.
    Where the kernel does not list children, assume there are some."""
    listings = list(Path("/proc/self/task").glob("*/children"))
    return not listings or any(listing.read_text().strip() for listing in listings)


def kill(pids: list[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
