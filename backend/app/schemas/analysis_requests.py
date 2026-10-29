import unicodedata
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.analyses.guest_choice import AUTO_PACKAGE
from app.schemas.analysis import AnalysisRead
from app.schemas.guest_name import GuestName
from app.schemas.settings import Route

type PackageName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,64}$")]

MAX_ARCHIVE_PASSWORD_LENGTH = 256
MAX_ARCHIVE_ENTRY_LENGTH = 512
ZIP_PACKAGE = "zip"


def _require_carriable_by_cape(value: str, name: str, max_length: int) -> str:
    """CAPE splits its option string on `,` and strips every value (`parse_options` in
    `lib/cuckoo/common/config.py`), so a value with a comma or edge whitespace cannot be carried.
    The messages never repeat the value: a password must not reach an error body or a log.
    """
    if not 1 <= len(value) <= max_length:
        raise ValueError(f"{name} must be 1 to {max_length} characters")
    if "," in value:
        raise ValueError(f"{name} must not contain a comma: CAPE cannot carry it")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{name} must not contain control characters")
    if value != value.strip():
        raise ValueError(f"{name} must not start or end with whitespace: CAPE strips it")
    return value


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
    archive_password: str | None = Field(
        default=None,
        description=(
            "The password of the zip being submitted (1 to 256 characters, no comma, no control "
            "character, no leading or trailing whitespace). Only together with `archive_entry`. "
            "Never returned by the API."
        ),
    )
    archive_entry: str | None = Field(
        default=None,
        description=(
            "The file of the zip to run, as `POST /analyses/archive-members` lists it (1 to 512 "
            "characters, no comma, no control character, no leading or trailing whitespace). "
            "Only together with `archive_password`; the zip is then unpacked in the guest and "
            "`package` is stored as `zip`."
        ),
    )

    @field_validator("archive_password")
    @classmethod
    def password_cape_can_carry(cls, password: str | None) -> str | None:
        if password is None:
            return None
        return _require_carriable_by_cape(password, "archive_password", MAX_ARCHIVE_PASSWORD_LENGTH)

    @field_validator("archive_entry")
    @classmethod
    def entry_cape_can_carry(cls, entry: str | None) -> str | None:
        if entry is None:
            return None
        return _require_carriable_by_cape(entry, "archive_entry", MAX_ARCHIVE_ENTRY_LENGTH)

    @model_validator(mode="after")
    def archive_fields_come_together_and_run_as_a_zip(self) -> Self:
        if (self.archive_password is None) != (self.archive_entry is None):
            raise ValueError("archive_password and archive_entry can only be set together")
        if self.archive_password is None:
            return self
        if self.package not in (AUTO_PACKAGE, ZIP_PACKAGE):
            raise ValueError(f"package must be auto or zip for an archive, not {self.package}")
        self.package = ZIP_PACKAGE
        return self

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
