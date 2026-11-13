"""build/runtime-packages.sh names the packages behind a binary's libraries (ldd, dpkg faked)."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build" / "runtime-packages.sh"

FAKE_LDD = """#!/bin/sh
printf '\\tlibfoo.so.1 => /lib/x86_64-linux-gnu/libfoo.so.1 (0x1)\\n'
printf '\\tlibbar.so.2 => /usr/lib/x86_64-linux-gnu/libbar.so.2 (0x2)\\n'
printf '\\tlibgone.so.3 => /opt/libgone.so.3 (0x3)\\n'
"""

# On a usr-merged system dpkg -S matches the /lib/... name of a t64 library only through the
# diversion it made for it, which names no owner, and finds the owner under /usr/lib/...
FAKE_DPKG = """#!/bin/sh
case "$2" in
/lib/x86_64-linux-gnu/libfoo.so.1)
    echo "diversion by libfoo1t64 from: $2"
    echo "diversion by libfoo1t64 to: $2.usr-is-merged" ;;
/usr/lib/x86_64-linux-gnu/libfoo.so.1) echo "libfoo1t64:amd64: $2" ;;
/usr/lib/x86_64-linux-gnu/libbar.so.2) echo "libbar2, libbar-common: $2" ;;
*) echo "dpkg-query: no path found matching pattern $2" >&2; exit 1 ;;
esac
"""


def run_script(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    fakes = tmp_path / "bin"
    fakes.mkdir()
    for name, body in (("ldd", FAKE_LDD), ("dpkg", FAKE_DPKG)):
        (fakes / name).write_text(body)
        (fakes / name).chmod(0o755)
    environment = {"PATH": f"{fakes}:/usr/bin:/bin"}
    return subprocess.run(  # noqa: S603
        ["/usr/bin/bash", str(SCRIPT), "/usr/bin/anything"],
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )


def test_a_library_found_only_through_a_diversion_is_attributed_to_its_owner(tmp_path):
    assert "libfoo1t64" in run_script(tmp_path).stdout.split()


def test_a_file_owned_by_several_packages_names_each_once(tmp_path):
    assert run_script(tmp_path).stdout.split() == ["libbar-common", "libbar2", "libfoo1t64"]


def test_a_library_no_package_owns_is_reported_not_listed(tmp_path):
    result = run_script(tmp_path)

    assert "unowned: /opt/libgone.so.3" in result.stderr
    assert "libgone" not in result.stdout
