"""Tests that the image ships the Volatility3 the control service runs: a pinned, hash-checked
wheel installed into the CAPE venv, where `volatility.VOLATILITY_COMMAND` points.
"""

import re
from pathlib import Path

from test_control_http import BIN  # noqa: F401 - puts bin/ on sys.path
from volatility import VOLATILITY_COMMAND

CAPE = Path(__file__).resolve().parents[1]
REQUIREMENTS = CAPE / "build" / "volatility3.requirements"
# From PyPI's JSON API for volatility3 2.28.2 (the wheel's digest).
WHEEL_SHA256 = "0461d6dd71b9ddbaf70c96e079c06efdf174ac65383b3dcf10dd165181fbd3c3"


def requirement_lines() -> list[str]:
    lines = REQUIREMENTS.read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def build_stage() -> str:
    dockerfile = (CAPE / "Dockerfile").read_text()
    stage = re.search(r"FROM ubuntu:24.04 AS cape-build\n(.*?)\nFROM ", dockerfile, re.DOTALL)
    assert stage
    return stage.group(1)


def test_the_requirement_is_one_exact_version_with_the_wheels_hash():
    assert requirement_lines() == [f"volatility3==2.28.2 --hash=sha256:{WHEEL_SHA256}"]


def test_the_dockerfile_installs_it_in_the_cape_venv_without_dependencies_and_only_by_hash():
    stage = build_stage()

    assert "COPY cape/build/volatility3.requirements /build/" in stage
    assert (
        "uv pip install --python .venv/bin/python --no-deps --require-hashes"
        " -r /build/volatility3.requirements"
    ) in stage


def test_it_is_installed_after_the_venv_is_synced_so_the_lock_decides_its_dependencies():
    stage = build_stage()

    assert stage.index("uv sync --frozen --no-dev") < stage.index("volatility3.requirements")


def test_the_image_build_fails_if_the_installed_volatility_cannot_start():
    assert "RUN .venv/bin/vol --help >/dev/null" in build_stage()


def test_the_service_runs_the_console_script_uv_puts_in_that_venv():
    assert "WORKDIR /opt/CAPEv2" in build_stage()
    assert VOLATILITY_COMMAND == "/opt/CAPEv2/.venv/bin/vol"
