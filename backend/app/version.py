import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

# The image copies pyproject.toml next to app/ (backend/Dockerfile), and the project is not
# installed as a package (`[tool.uv] package = false`), so importlib.metadata has no record.
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


@dataclass(frozen=True)
class BackendVersion:
    version: str
    license: str


@cache
def read_backend_version(pyproject: Path = PYPROJECT_PATH) -> BackendVersion:
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    return BackendVersion(version=project["version"], license=project["license"])
