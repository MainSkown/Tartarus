#!/usr/bin/python3
"""Patches CAPE's guest-side analyzer (analyzer/windows/analyzer.py) so that no analysis ever
injects the monitor into the DCOM launcher service (`svchost.exe -k DcomLaunch`).

The monitor in Explorer reports COM activity (Windows Terminal, Edge, Store apps) and the analyzer
answers by injecting `DcomLaunch`. The monitor stays loaded there after the analyzer exits, and from
then on a process the agent starts can hang, even `cmd /c echo hi`, so the host-side event-log
export waits out its read timeouts: the run reports 2.5 minutes late with no sysmon.xml
(M9 spike P3, task 3.8). M9 applied this to interactive analyses only; M10's spike F8 found the same
stall in plain analyses on Windows 10, where the monitor is injected into Explorer and so into the
launcher in 3 of 5 runs, and none in 3 of 3 runs without the injection. Marking the launcher as
monitored already is the analyzer's own switch for "do not inject it again", which its interop, WMI
and BITS handlers all test.

Usage: leave-dcom-launch-alone.py <analyzer.py>. The anchor must match exactly once, otherwise
nothing is written and the exit status is non-zero, so a CAPE_REF bump that moves the code fails
the build instead of silently dropping the fix.
"""

import sys
from pathlib import Path

ANCHOR = """        if self.options.get("interactive", False):
            INTERACTIVE_MODE = True
"""

REPLACEMENT = """        # Tartarus: a monitor left in the DCOM launcher stalls the processes
        # started after the analyzer exits, which costs the run its event-log exports.
        self.MONITORED_DCOM = True
        if self.options.get("interactive", False):
            INTERACTIVE_MODE = True
"""


def patched(source: str) -> str:
    found = source.count(ANCHOR)
    if found != 1:
        raise SystemExit(
            f"leave-dcom-launch-alone: expected the anchor exactly once, found {found}"
        )
    return source.replace(ANCHOR, REPLACEMENT)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: leave-dcom-launch-alone.py <analyzer.py>")
    target = Path(sys.argv[1])
    target.write_text(patched(target.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
