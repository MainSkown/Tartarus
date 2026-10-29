#!/usr/bin/python3
"""Patches CAPE's `zip` analysis package (analyzer/windows/modules/packages/zip.py) so that it finds
the 7-Zip console build this image ships in the analyzer's `bin` directory.

Python's `zipfile` cannot read AES-encrypted zips, so `Zip.start()` falls back to 7-Zip, and the guest
has none: the run dies with "Unable to find any 7z.exe executable" and CAPE still reports the task as
done (zip spike, tasks 22 to 24). The fallback itself already works. CAPE's lookup
(`get_path_app_in_path`) matches the substring `7z.exe` in each path of `Zip.PATHS`, so the Dockerfile
installs the standalone `7za.exe` as `bin/7z.exe` and this patch adds that path, resolved from the
package's own location because the analyzer is extracted to a random directory on every task. It goes
after the stock `ProgramFiles` entry, so a 7-Zip installed in the guest is still preferred.

Usage: zip-bundled-7zip.py <zip.py>. The anchor must match exactly once, otherwise nothing is written
and the exit status is non-zero, so a CAPE_REF bump that moves the code fails the build instead of
silently dropping the fix.
"""

import sys
from pathlib import Path

ANCHOR = """        ("ProgramFiles", "7-Zip", "7z.exe"),
"""

REPLACEMENT = (
    ANCHOR
    + """        # Tartarus: the 7z.exe the image ships in the analyzer's bin directory.
        (os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bin", "7z.exe"),
"""
)


def patched(source: str) -> str:
    found = source.count(ANCHOR)
    if found != 1:
        raise SystemExit(f"zip-bundled-7zip: expected the anchor exactly once, found {found}")
    return source.replace(ANCHOR, REPLACEMENT)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: zip-bundled-7zip.py <zip.py>")
    target = Path(sys.argv[1])
    target.write_text(patched(target.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
