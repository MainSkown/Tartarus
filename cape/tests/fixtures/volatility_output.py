"""Real Volatility3 2.28.2 output (JSON renderer) of the injecting sample, for a fake `vol`."""

import json
from pathlib import Path

from test_control_http import BIN  # noqa: F401 - puts bin/ on sys.path
from volatility import CommandResult

DIRECTORY = Path(__file__).parent / "volatility"
BANNER = "Volatility 3 Framework 2.28.2\n"
UNSATISFIED = (
    "\nUnsatisfied requirement plugins.Info.kernel.symbol_table_name: Symbol table\n"
    "\nA symbol table requirement was not fulfilled.  Please verify that:\n"
)


def fixture_rows(plugin: str) -> list[dict]:
    return json.loads((DIRECTORY / f"{plugin}.json").read_text())


def success(plugin: str) -> CommandResult:
    return CommandResult(0, (DIRECTORY / f"{plugin}.json").read_text(), BANNER)


def failure(returncode: int = 1, stdout: str = "", stderr: str = BANNER) -> CommandResult:
    return CommandResult(returncode, stdout, stderr)
