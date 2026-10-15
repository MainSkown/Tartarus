import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def captured(name: str) -> Any:
    """JSON the control service answered, or, for cases a live stack cannot produce on demand
    (a broken guest, an unrecognised file, a check result), the shape its source says it answers."""
    return json.loads((FIXTURES / name).read_text())
