import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "cape" / "live_logs_45"
PIDS = (2476, 9708)


@pytest.fixture(scope="session")
def report_processes() -> dict[int, dict[str, Any]]:
    report = json.loads((FIXTURES / "report_calls.json").read_text())
    return {entry["process_id"]: entry for entry in report["behavior"]["processes"]}


@pytest.fixture(scope="session")
def log_bytes() -> dict[int, bytes]:
    return {pid: (FIXTURES / f"{pid}.bson").read_bytes() for pid in PIDS}
