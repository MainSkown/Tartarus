import contextlib
import shutil
from pathlib import Path
from typing import Any


def analysis_exports_dir(root: Path, analysis_id: int) -> Path:
    return root / str(analysis_id)


def file_result(root: Path, produced: Path, filename: str, media_type: str) -> dict[str, Any]:
    """The `result` of a job that produced a downloadable file (see `GET /jobs/{id}/download`)."""
    try:
        relative = produced.relative_to(root)
    except ValueError:
        raise ValueError(f"{produced} is outside the exports directory {root}") from None
    return {"file": relative.as_posix(), "filename": filename, "media_type": media_type}


def resolve_export(root: Path, name: str) -> Path | None:
    """The existing file `name` (relative to `root`) points at, or None if it is missing or
    resolves, through `..`, an absolute name or a symlink, to somewhere outside `root`."""
    if not name:
        return None
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        return None
    return resolved


def remove_analysis_exports(root: Path, analysis_id: int) -> None:
    """A directory that is already gone counts as removed; any other failure raises."""
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(analysis_exports_dir(root, analysis_id))
