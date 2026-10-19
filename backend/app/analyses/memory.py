"""What an analysis says about its memory dump; stored in `analysis.summary.memory`.

The step that fills it in is `app.analyses.memory_step`.
"""

from enum import StrEnum

from pydantic import BaseModel


class MemoryFindings(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class MemorySummary(BaseModel):
    """`unavailable` means there was no dump to read (CAPE skips the dump when the storage is
    nearly full); `failed` means the control service could not run Volatility3 on one; `error`
    then says why, or names the plugins that failed when the others still gave findings.
    `dump_deleted` is null when the dump was not deleted on purpose (kept, or never taken).
    """

    dump_taken: bool
    findings: MemoryFindings
    error: str | None = None
    dump_bytes: int | None = None
    dump_deleted: bool | None = None
