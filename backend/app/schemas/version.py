from app.schemas.base import ApiModel


class VersionInfo(ApiModel):
    version: str
    commit: str | None
    license: str
