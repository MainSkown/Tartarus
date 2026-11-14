"""Opt-in: reads the real Windows ISOs in data/iso (multi-gigabyte user files, so not in CI)."""

import time
from pathlib import Path

import pytest
from test_windows_inspector import inspector

from guest_engine.media import run_command, scan_media

ISO_DIRECTORY = Path(__file__).parents[2] / "data" / "iso"
WINDOWS_ISOS = [
    path for path in sorted(ISO_DIRECTORY.glob("*.iso")) if path.stat().st_size > 1_000_000_000
]

pytestmark = pytest.mark.skipif(not WINDOWS_ISOS, reason="no real ISO in data/iso")


@pytest.fixture(scope="module")
def entries():
    started = time.monotonic()
    found = scan_media(ISO_DIRECTORY, {"windows": inspector}, run_command)
    return {
        "by_file": {entry["file"]: entry for entry in found},
        "seconds": time.monotonic() - started,
    }


@pytest.mark.parametrize("iso", WINDOWS_ISOS, ids=lambda path: path.name)
def test_a_real_iso_is_read_to_the_end_without_a_mount(entries, iso):
    entry = entries["by_file"][iso.name]

    assert entry["profile"] == "windows", entry.get("error")
    assert entry["kind"] == "installer"
    assert [variant["index"] for variant in entry["variants"]] == list(
        range(1, len(entry["variants"]) + 1)
    )
    assert {variant["build"] for variant in entry["variants"]} == {entry["build"]}
    assert entry["version"].endswith(f".{entry['build']}")
    assert entry["compression"] in {"LZX", "LZMS", "XPRESS"}
    assert entry["size"] == iso.stat().st_size


def test_the_wizard_can_list_the_real_media_in_about_a_second(entries):
    assert entries["seconds"] < 1.5 * len(WINDOWS_ISOS)
