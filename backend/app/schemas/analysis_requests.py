from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

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
    memory_dump: bool = Field(
        default=False,
        description=(
            "Dump the guest's RAM at the end of the run and read it with Volatility3. The dump "
            "is as big as the guest's RAM, so it is refused (409) without room on the CAPE storage."
        ),
    )
    keep_memory_dump: bool = Field(
        default=False,
        description="Keep the dump after its findings are read; only with `memory_dump`.",
    )
    guest: GuestName | None = Field(
        default=None,
        description="The guest to run on; the default guest when omitted. Always stored resolved.",
    )

    @field_validator("keep_memory_dump")
    @classmethod
    def only_a_dump_can_be_kept(cls, keep: bool, info: ValidationInfo) -> bool:
        if keep and not info.data.get("memory_dump"):
            raise ValueError("can only be set together with memory_dump")
        return keep


class ExtendRequest(BaseModel):
    """How many seconds to move an interactive run's deadline later."""

    seconds: int = Field(ge=1, le=600)


class AnalysisCreated(AnalysisRead):
    warnings: list[str] = Field(
        default_factory=list,
        description="What the analyst should know about the submission, such as little free disk.",
    )


class AnalysisPage(BaseModel):
    items: list[AnalysisRead]
    total: int


class CapeCallback(BaseModel):
    """What CAPE's callback reporting module posts when a task finishes."""

    task_id: int
