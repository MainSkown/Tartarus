"""What an analysis says about Windows Defender; stored in `analysis.summary.defender`.

How the verdict is worked out is in `app.ingest.defender_verdict`.
"""

from enum import StrEnum

from pydantic import BaseModel

from app.ingest.defender_export import Outcome, Scope


class DefenderStatus(StrEnum):
    CLEAN = "clean"
    DETECTED = "detected"
    REMOVED = "removed"
    FAILED = "failed"
    NO_EXPORT = "no_export"


class DefenderThreat(BaseModel):
    detection_id: str
    threat_id: int | None
    name: str | None
    severity: int
    category_id: int | None
    scope: Scope
    path: str | None
    process: str | None
    user: str | None
    detected_at: str | None
    action: str
    outcome: Outcome
    removed_at: str | None


class DefenderVerdict(BaseModel):
    """`no_export` means the guest left no Defender export (agent unreachable, module not
    enabled, an older analysis); `clean` means the export ran and holds no detection of the
    sample or of what it dropped. CAPE's own tooling is never listed as a threat.
    """

    status: DefenderStatus
    sample_removed: bool
    blocked_before_run: bool
    threats: list[DefenderThreat]
