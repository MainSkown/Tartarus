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


# The kernel of the S3 spike's Windows 11 dump; the age is appended to the GUID in decimal, as
# Volatility prints it in the PDB's URL.
KERNEL_GUID = "24DE61DB3A27C5B383DFF181CB51F7E1"


def missing_symbols_log(
    guid: str = KERNEL_GUID, age: int | str = 1, pdb: str = "ntkrnlmp.pdb"
) -> str:
    """The INFO line `vol -v --offline` (2.28.2) logs when no ISF matches the kernel it found.

    Read from a real run on a Windows 11 dump (M8 real-run proof). The "symbols can be downloaded
    later" line that `pdbutil` logs when online never appears with `--offline`.
    """
    return (
        "INFO     volatility3.framework.layers.resources: Not accessing"
        f" http://msdl.microsoft.com/download/symbols/{pdb}/{guid}{age}/{pdb} in offline mode\n"
    )
