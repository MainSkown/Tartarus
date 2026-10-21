"""Event-log exports the guest could not make; stored in `analysis.summary.missing_exports`.

The CAPE auxiliary `event_logs` writes `aux/event_logs.json` into the analysis folder when a
channel it should have exported (Sysmon above all) could not be, so a gap in the events is
reported instead of looking like a quiet run.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

MARKER_PATH = Path("aux") / "event_logs.json"


class MissingExport(BaseModel):
    channel: str
    reason: str


class _Marker(BaseModel):
    missing: list[MissingExport]


def read_missing_exports(analysis_dir: Path) -> list[MissingExport]:
    """Empty when there is no marker; an unreadable marker is empty too, because a damaged note
    must not fail the ingest of an analysis whose events are fine.
    """
    try:
        return _Marker.model_validate(json.loads((analysis_dir / MARKER_PATH).read_bytes())).missing
    except (OSError, ValueError, ValidationError):
        return []
