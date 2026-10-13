import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.ingest.conftest import FULL_REPORT

DROPPED_SHA256 = "19e19f9e997696d63c3a2ef193633c001b032b3880fd4b487dfea606aa77c196"
PROCDUMP_SHA256 = "06b8f2f53a14e16e10187f14604e813ad7fad0846f9f032248728cca1d1f9e87"
PCAP_SHA256 = "c79656a444d0bd53b8c2b2af439c01c6fe92b4f5f5c38aa09d0519d513d4b7ac"


@pytest.fixture
def report() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FULL_REPORT.read_text())
    return copy.deepcopy(loaded)


@pytest.fixture
def analysis_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "storage" / "analyses" / "6"
    directory.mkdir(parents=True)
    return directory


def put_file(directory: Path, relative: str, content: bytes) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
