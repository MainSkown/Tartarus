from functools import cache
from pathlib import Path

import yaml

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@cache
def _services() -> dict[str, dict[str, object]]:
    return yaml.safe_load(COMPOSE_FILE.read_text())["services"]


def compose_image(service: str) -> str:
    return str(_services()[service]["image"])
