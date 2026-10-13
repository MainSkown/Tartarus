from typing import Annotated

from fastapi import APIRouter, Depends

from app.analyses.ports import RunnerControl
from app.api.dependencies import get_runner
from app.schemas.analysis_requests import CapeCallback

# Tagged only because every route needs a tag for its operation id; it is not in the schema.
router = APIRouter(prefix="/internal/cape", tags=["internal"], include_in_schema=False)


@router.post("/callback")
async def callback(
    _callback: CapeCallback, runner: Annotated[RunnerControl, Depends(get_runner)]
) -> dict[str, bool]:
    """A hint that CAPE has something to report. The runner asks CAPE itself before acting."""
    runner.nudge()
    return {"ok": True}
