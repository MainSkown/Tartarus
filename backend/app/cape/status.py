from collections.abc import Mapping
from enum import StrEnum


class CapeProgress(StrEnum):
    """Where an analysis stands according to CAPE; values are the matching analysis states.

    `done` is absent on purpose: it is reached only after the backend has read the report,
    which CAPE's `reported` status cannot tell.
    """

    STARTING = "starting"
    RUNNING = "running"
    PROCESSING = "processing"
    INGESTING = "ingesting"
    FAILED = "failed"
    REPORT_FAILED = "report_failed"
    UNKNOWN = "unknown"


# Every TASK_* constant of CAPE's lib/cuckoo/core/data/task.py (ALL_DB_STATUSES).
CAPE_STATUS_PROGRESS: Mapping[str, CapeProgress] = {
    "pending": CapeProgress.STARTING,
    # Distributed mode only; Tartarus runs a single node but a worker handoff still has not started.
    "distributed": CapeProgress.STARTING,
    "running": CapeProgress.RUNNING,
    "completed": CapeProgress.PROCESSING,
    "distributed_completed": CapeProgress.PROCESSING,
    "reported": CapeProgress.INGESTING,
    "failed_analysis": CapeProgress.FAILED,
    "failed_processing": CapeProgress.FAILED,
    "failed_reporting": CapeProgress.REPORT_FAILED,
    # A user ban cancels a pending task; a rescheduled task is replaced by a copy with a new id.
    # Either way the tracked task will never report.
    "banned": CapeProgress.FAILED,
    "recovered": CapeProgress.FAILED,
}


def progress_for(cape_status: str) -> CapeProgress:
    return CAPE_STATUS_PROGRESS.get(cape_status, CapeProgress.UNKNOWN)
