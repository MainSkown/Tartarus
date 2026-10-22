import json
from pathlib import Path


class JsonFileTooLargeError(ValueError):
    """The file is bigger than the caller is willing to hold in memory."""


def load_json_file(path: Path, max_bytes: int) -> object:
    """Parse a JSON file written by something the backend does not trust.

    Raises ``ValueError`` (``JsonFileTooLargeError`` for size) for anything that is not strict
    JSON, so a caller catches ``OSError, ValueError`` and nothing else: Python's parser would
    otherwise accept ``Infinity``/``NaN`` and fail on deep nesting with ``RecursionError``.
    """
    size = path.stat().st_size
    if size > max_bytes:
        raise JsonFileTooLargeError(f"{path.name} is {size} bytes, over the {max_bytes} limit")
    try:
        return json.loads(path.read_bytes(), parse_constant=_reject_constant)
    except RecursionError as error:
        raise ValueError(f"{path.name} is nested too deeply") from error


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not valid JSON")
