"""The analyzer's monitor, as CAPE's storage shows it: its logs appear once it runs in the guest."""

from datetime import UTC, datetime
from pathlib import Path


def monitor_started(storage: Path, cape_task_id: int) -> bool:
    return first_monitor_log_time(storage, cape_task_id) is not None


def first_monitor_log_time(storage: Path, cape_task_id: int) -> datetime | None:
    """When the oldest monitor log was last written, or None while the monitor has not started."""
    logs = storage / "analyses" / str(cape_task_id) / "logs"
    if not logs.is_dir():
        return None
    written = [log.stat().st_mtime for log in logs.glob("*.bson")]
    if not written:
        return None
    return datetime.fromtimestamp(min(written), UTC)
