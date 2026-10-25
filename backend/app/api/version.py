from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas.version import VersionInfo
from app.version import read_backend_version

router = APIRouter(tags=["system"])


@router.get("/version")
def version(settings: Annotated[Settings, Depends(get_settings)]) -> VersionInfo:
    """The release this backend runs, the git commit it was built from when the image says so
    (`TARTARUS_COMMIT`), and the license the code is under."""
    backend = read_backend_version()
    return VersionInfo(
        version=backend.version, commit=settings.tartarus_commit, license=backend.license
    )
