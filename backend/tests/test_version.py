import json
from pathlib import Path

from app.version import read_backend_version

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_package_json_matches_the_backend_version_and_license() -> None:
    backend = read_backend_version()
    frontend = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))

    assert frontend["version"] == backend.version, (
        f"frontend/package.json has version {frontend['version']!r} but backend/pyproject.toml "
        f"has {backend.version!r}: bump both to the same release"
    )
    assert frontend["license"] == backend.license, (
        f"frontend/package.json has license {frontend['license']!r} but backend/pyproject.toml "
        f"has {backend.license!r}: they must name the same license"
    )
