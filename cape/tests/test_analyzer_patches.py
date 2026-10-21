"""The analyzer patches the image applies to CAPE's guest-side analyzer (M9 task 3.8)."""

import importlib.util
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


def test_a_non_interactive_analysis_still_monitors_the_dcom_launcher(leave_dcom_launch_alone):
    patched = leave_dcom_launch_alone.patched(ANALYZER)

    assert run_analyzer(patched, interactive=False).MONITORED_DCOM is False


def test_the_patch_gives_up_when_the_anchor_moved(leave_dcom_launch_alone):
    with pytest.raises(SystemExit, match="exactly once, found 0"):
        leave_dcom_launch_alone.patched(
            ANALYZER.replace("INTERACTIVE_MODE = True", "INTERACTIVE_MODE = 1")
        )


def test_the_patch_gives_up_when_the_anchor_is_there_twice(leave_dcom_launch_alone):
    with pytest.raises(SystemExit, match="exactly once, found 2"):
        leave_dcom_launch_alone.patched(ANALYZER + ANALYZER)
