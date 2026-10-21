#!/usr/bin/python3
"""Patches CAPE's guest-side analyzer (analyzer/windows/analyzer.py) so that an interactive analysis
never injects the monitor into the DCOM launcher service (`svchost.exe -k DcomLaunch`).

The monitor in Explorer reports COM activity (Windows Terminal, Edge, Store apps) and the analyzer
answers by injecting `DcomLaunch`. The monitor stays loaded there after the analyzer exits, and from
then on every new process the agent starts hangs, even `cmd /c echo hi`, so the host-side event-log
export waits out its read timeouts: the run reports 2.5 minutes late with no sysmon.xml
(M9 spike P3, task 3.8). Without the injection the same run reports 20 s after /finish with its
export. Marking the launcher as monitored already is the analyzer's own switch for "do not inject it
again", which its interop, WMI and BITS handlers all test.

Usage: leave-dcom-launch-alone.py <analyzer.py>. The anchor must match exactly once, otherwise
nothing is written and the exit status is non-zero, so a CAPE_REF bump that moves the code fails
the build instead of silently dropping the fix.
"""

import sys
from pathlib import Path

ANCHOR = """            INTERACTIVE_MODE = True
            log.info("Interactive mode enabled"""

REPLACEMENT = """            INTERACTIVE_MODE = True
            # Tartarus: a monitor left in the DCOM launcher stalls every process started after the
            # analyzer exits, which costs an interactive run its event-log exports.
            self.MONITORED_DCOM = True
            log.info("Interactive mode enabled"""


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
