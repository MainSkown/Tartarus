#!/usr/bin/python3
"""Patches CAPE's guest-side analyzer (analyzer/windows/analyzer.py) so that an interactive analysis
does not inject the monitor into Store apps.

With capemon injected, a packaged app such as the Windows 11 Notepad stops in ntdll lock waits
right after it loads AppxDeploymentClient and never opens a window; the same app opens normally
without the monitor (docs/specs/cape-integration.md, "Store apps in interactive mode"). The analyzer
is zipped from /opt/CAPEv2/analyzer/windows and uploaded to the guest at the start of every task,
so patching it in the image needs no change to the guest or its snapshot.

Usage: skip-packaged-apps.py <analyzer.py>. Every anchor must match exactly once, otherwise nothing
is written and the exit status is non-zero, so a CAPE_REF bump that moves the code fails the build
instead of silently dropping the fix.
"""

import sys
from pathlib import Path

HELPER_ANCHOR = '''def add_protected_path(name: Union[str, bytes]):
    """Adds a pathname to the protected list"""
    PROTECTED_PATH_LIST.append(_normalized_protected_path(name))
'''

HELPER = HELPER_ANCHOR + '''

# Tartarus: the image path of a process is an NT path (\\Device\\HarddiskVolumeN\\Program Files\\...),
# so the match is on the part after the volume.
PACKAGED_APPS_DIRECTORY = b"\\\\program files\\\\windowsapps\\\\"


def skips_packaged_app(image_path: Union[str, bytes], package_name: str) -> bool:
    """Whether an interactive analysis leaves this process without the monitor.

    The msix package runs the sample itself as a Store app, which must stay monitored.
    """
    if not INTERACTIVE_MODE or (package_name or "").endswith(".msix"):
        return False
    if isinstance(image_path, str):
        image_path = image_path.encode()
    return PACKAGED_APPS_DIRECTORY in image_path.lower()
'''

INJECTION_ANCHOR = """                    if not in_protected_path(filename):
                        _ = proc.inject(interest)
"""

INJECTION = """                    if skips_packaged_app(filepath, self.analyzer.package_name):
                        INJECT_LIST.remove(process_id)
                        log.info("Interactive mode: not injecting into packaged app %s (pid %d)", filename, process_id)
                    elif not in_protected_path(filename):
                        _ = proc.inject(interest)
"""

REPLACEMENTS = [(HELPER_ANCHOR, HELPER), (INJECTION_ANCHOR, INJECTION)]


def patched(source: str) -> str:
    for anchor, replacement in REPLACEMENTS:
        found = source.count(anchor)
        if found != 1:
            first_line = anchor.splitlines()[0].strip()
            raise SystemExit(f"skip-packaged-apps: expected the anchor '{first_line}' exactly once, found {found}")
        source = source.replace(anchor, replacement)
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: skip-packaged-apps.py <analyzer.py>")
    target = Path(sys.argv[1])
    target.write_text(patched(target.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
