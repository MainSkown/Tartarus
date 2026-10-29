"""The analyzer patches the image applies to CAPE's guest-side analyzer (M9 task 3.8)."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

PATCHES = Path(__file__).resolve().parent.parent / "patches"

# The lines of CAPE's `Analyzer.run` the patch anchors on, with the class around them cut down.
ANALYZER = """\
class Analyzer:
    def __init__(self, interactive):
        self.MONITORED_DCOM = False
        self.options = {"interactive": interactive}

    def run(self):
        if self.options.get("interactive", False):
            INTERACTIVE_MODE = True
            log.info("Interactive mode enabled - injecting into explorer shell")
        else:
            INTERACTIVE_MODE = False
"""

# The head of CAPE's `Zip` package: the places it looks for the programs that open archives.
ZIP_PACKAGE = """\
import os


class Zip:
    PATHS = [
        ("SystemRoot", "system32", "cmd.exe"),
        ("ProgramFiles", "7-Zip", "7z.exe"),
        ("SystemRoot", "system32", "xpsrchvw.exe"),
    ]
"""


def load_patch(file_name):
    spec = importlib.util.spec_from_file_location(
        file_name.removesuffix(".py"), PATCHES / file_name
    )
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    return patch


def run_analyzer(source, interactive):
    scope = {"log": SimpleNamespace(info=lambda *_: None)}
    exec(compile(source, "analyzer.py", "exec"), scope)  # noqa: S102 - the test's own fixture
    analyzer = scope["Analyzer"](interactive)
    analyzer.run()
    return analyzer


@pytest.fixture
def leave_dcom_launch_alone():
    return load_patch("leave-dcom-launch-alone.py")


def test_an_interactive_analysis_counts_the_dcom_launcher_as_monitored(
    leave_dcom_launch_alone,
):
    patched = leave_dcom_launch_alone.patched(ANALYZER)

    assert run_analyzer(patched, interactive=True).MONITORED_DCOM is True


def test_a_non_interactive_analysis_counts_the_dcom_launcher_as_monitored_too(
    leave_dcom_launch_alone,
):
    patched = leave_dcom_launch_alone.patched(ANALYZER)

    assert run_analyzer(patched, interactive=False).MONITORED_DCOM is True


def test_the_patch_gives_up_when_the_anchor_moved(leave_dcom_launch_alone):
    with pytest.raises(SystemExit, match="exactly once, found 0"):
        leave_dcom_launch_alone.patched(
            ANALYZER.replace("INTERACTIVE_MODE = True", "INTERACTIVE_MODE = 1")
        )


def test_the_patch_gives_up_when_the_anchor_is_there_twice(leave_dcom_launch_alone):
    with pytest.raises(SystemExit, match="exactly once, found 2"):
        leave_dcom_launch_alone.patched(ANALYZER + ANALYZER)


@pytest.fixture
def zip_bundled_7zip():
    return load_patch("zip-bundled-7zip.py")


def find_in_paths(paths, application):
    """CAPE's `get_path_app_in_path`, for entries that do not start with an environment variable."""
    for path in paths:
        joined = os.path.join(*path)
        if os.path.isfile(joined) and application.lower() in joined.lower():
            return joined
    return None


def zip_package_in(analyzer_dir, source):
    scope = {"__file__": str(analyzer_dir / "modules" / "packages" / "zip.py")}
    exec(compile(source, "zip.py", "exec"), scope)  # noqa: S102 - the test's own fixture
    return scope["Zip"]


def test_the_zip_package_finds_the_7zip_shipped_in_the_analyzer_bin_directory(
    zip_bundled_7zip, tmp_path
):
    bundled = tmp_path / "bin" / "7z.exe"
    bundled.parent.mkdir()
    bundled.write_bytes(b"MZ")
    package = zip_package_in(tmp_path, zip_bundled_7zip.patched(ZIP_PACKAGE))

    found = find_in_paths(package.PATHS, "7z.exe")

    assert found is not None
    assert Path(found).resolve() == bundled.resolve()


def test_the_zip_package_does_not_find_a_7zip_the_analyzer_does_not_ship(
    zip_bundled_7zip, tmp_path
):
    package = zip_package_in(tmp_path, zip_bundled_7zip.patched(ZIP_PACKAGE))

    assert find_in_paths(package.PATHS, "7z.exe") is None


def test_the_zip_package_keeps_every_place_it_looked_in_before(zip_bundled_7zip, tmp_path):
    stock = zip_package_in(tmp_path, ZIP_PACKAGE).PATHS
    patched = zip_package_in(tmp_path, zip_bundled_7zip.patched(ZIP_PACKAGE)).PATHS

    assert [path for path in patched if path in stock] == stock
    assert len(patched) == len(stock) + 1


def test_an_installed_7zip_is_preferred_over_the_bundled_one(zip_bundled_7zip, tmp_path):
    package = zip_package_in(tmp_path, zip_bundled_7zip.patched(ZIP_PACKAGE))

    installed = package.PATHS.index(("ProgramFiles", "7-Zip", "7z.exe"))
    bundled = next(
        i
        for i, path in enumerate(package.PATHS)
        if os.path.join(*path).endswith("7z.exe") and i != installed
    )
    assert installed < bundled


def test_the_7zip_patch_gives_up_when_the_anchor_moved(zip_bundled_7zip):
    with pytest.raises(SystemExit, match="exactly once, found 0"):
        zip_bundled_7zip.patched(ZIP_PACKAGE.replace("7-Zip", "7Zip"))


def test_the_7zip_patch_gives_up_when_the_anchor_is_there_twice(zip_bundled_7zip):
    with pytest.raises(SystemExit, match="exactly once, found 2"):
        zip_bundled_7zip.patched(ZIP_PACKAGE + ZIP_PACKAGE)


def test_the_7zip_patch_writes_nothing_when_the_anchor_moved(
    zip_bundled_7zip, tmp_path, monkeypatch
):
    target = tmp_path / "zip.py"
    moved = ZIP_PACKAGE.replace("7-Zip", "7Zip")
    target.write_text(moved, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["zip-bundled-7zip.py", str(target)])

    with pytest.raises(SystemExit):
        zip_bundled_7zip.main()

    assert target.read_text(encoding="utf-8") == moved
