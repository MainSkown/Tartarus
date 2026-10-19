"""Tests of `bin/guest-symbols`, the command the Windows profile's `symbols` build step runs."""

import io
import os
import subprocess
import sys
import tempfile

import pytest
import symbols_logic
from test_control_http import BIN, load_script
from test_symbols_logic import FILE_NAME, GUID, FakeConvert, FakeFetch

guest_symbols = load_script("guest-symbols")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return symbols_logic.SymbolStore(tmp_path / "symbols", FakeFetch(), FakeConvert())


def test_it_prints_the_line_the_build_logs_and_exits_with_the_status(store):
    out = io.StringIO()

    status = guest_symbols.main(["ensure", GUID, "1"], store, out)

    assert status == 0
    assert out.getvalue() == f"symbols: ready {FILE_NAME} (created)\n"


def test_a_failure_is_one_line_and_a_nonzero_status(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    failing = symbols_logic.SymbolStore(
        tmp_path / "symbols", FakeFetch(symbols_logic.FetchFailedError("no DNS")), FakeConvert()
    )
    out = io.StringIO()

    status = guest_symbols.main(["ensure", GUID, "1"], failing, out)

    assert (status, out.getvalue()) == (1, "symbols: unavailable (no DNS)\n")


def test_run_as_a_program_it_is_executable_and_finds_its_sibling_modules_in_isolated_mode():
    assert os.access(BIN / "guest-symbols", os.X_OK)

    done = subprocess.run(  # noqa: S603 - fixed argv, a script of this repository
        [sys.executable, "-I", str(BIN / "guest-symbols")],
        capture_output=True,
        text=True,
        check=False,
        env={},
    )

    assert done.returncode == 2
    assert "usage: guest-symbols ensure GUID AGE" in done.stdout
