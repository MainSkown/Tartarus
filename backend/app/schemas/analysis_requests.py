from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.analysis import AnalysisRead
from app.schemas.guest_name import GuestName
from app.schemas.settings import Route

type PackageName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,64}$")]


class AnalysisOptions(BaseModel):
    """The `options` JSON of a submission; stored as `analysis.options`."""

    model_config = ConfigDict(extra="forbid")

    route: Route = "inetsim"
    timeout: int = Field(default=180, ge=60, le=1200)
    package: PackageName = "auto"
    interactive: bool = False
    guest: GuestName | None = Field(
        default=None,
        description="The guest to run on; the default guest when omitted. Always stored resolved.",
    )


class AnalysisPage(BaseModel):
    items: list[AnalysisRead]
    total: int


class CapeCallback(BaseModel):
    """What CAPE's callback reporting module posts when a task finishes."""

    task_id: int
