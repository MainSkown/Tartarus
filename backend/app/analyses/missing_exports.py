"""Event-log exports the guest could not make; stored in `analysis.summary.missing_exports`.

The CAPE auxiliary `event_logs` writes `aux/event_logs.json` into the analysis folder when a
channel it should have exported (Sysmon above all) could not be, so a gap in the events is
reported instead of looking like a quiet run.
"""

import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.ingest.json_file import load_json_file

MAX_MARKER_BYTES = 1024**2

MARKER_PATH = Path("aux") / "event_logs.json"
CHANNEL_LABELS = {
    "Microsoft-Windows-Sysmon/Operational": "Sysmon",
    "Microsoft-Windows-Windows Defender/Operational": "Windows Defender",
}
# The module records the agent's own error text (`requests`' wording); only these two shapes are
# worth rewording, anything else is shown as the module wrote it.
READ_TIMEOUT = re.compile(r"Read timed out\. \(read timeout=(\d+)\)")
AGENT_SILENT = re.compile(r"^the guest agent did not answer within \d+ s")


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
        return _Marker.model_validate(
            load_json_file(analysis_dir / MARKER_PATH, MAX_MARKER_BYTES)
        ).missing
    except (OSError, ValueError, ValidationError):
        return []


def export_warnings(missing: list[MissingExport]) -> list[str]:
    """One plain sentence per channel the guest could not export, for the analysis's warnings."""
    return [
        f"{CHANNEL_LABELS.get(gap.channel, gap.channel)} events were not exported: "
        f"{_reason_in_words(gap.reason)}"
        for gap in missing
    ]


def _reason_in_words(reason: str) -> str:
    if timed_out := READ_TIMEOUT.search(reason):
        return f"the guest did not answer within {timed_out.group(1)} s"
    if silent := AGENT_SILENT.match(reason):
        return silent.group(0)
    return reason
