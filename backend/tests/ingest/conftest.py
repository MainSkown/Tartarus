import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.ingest.protocol import IngestContext

FULL_REPORT = Path(__file__).parent.parent / "fixtures" / "cape" / "report_full_trimmed.json"
ANALYSIS_ID = 6


@pytest.fixture(scope="session")
def full_report() -> dict[str, Any]:
    report: dict[str, Any] = json.loads(FULL_REPORT.read_text())
    return report


@pytest.fixture
def context() -> IngestContext:
    return IngestContext(
        analysis_id=ANALYSIS_ID, started_at=datetime(2026, 10, 13, 12, 12, 18, tzinfo=UTC)
    )
