from pydantic import BaseModel, ConfigDict, Field


class ArchiveMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(description="The member's path inside the zip, as the archive writes it.")
    size: int = Field(
        ge=0,
        description="The uncompressed size the central directory declares. The data is not read.",
    )
    encrypted: bool = Field(description="The member is encrypted, so the password is needed.")
    unsafe: bool = Field(
        description=(
            "The name escapes the guest's directory: `..`, an absolute path, a drive letter or a "
            "NUL byte. Shown, but it cannot be chosen to run."
        ),
    )
    unsupported: bool = Field(
        description=(
            "The name holds a comma or leading or trailing whitespace, which the CAPE option "
            "string cannot carry. Shown, but it cannot be chosen to run."
        ),
    )


class ArchiveMembersRead(BaseModel):
    members: list[ArchiveMemberRead] = Field(description="In the archive's order.")
    password_ok: bool | None = Field(
        description=(
            "Whether the password opens the encrypted members. `null` when there is no verdict: "
            "no member is encrypted, or every encrypted member is unsafe, so none is checked."
        ),
    )
