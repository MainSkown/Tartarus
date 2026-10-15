"""`guest-record set <field> <json value>`: how a step records a fact about its guest.

Only a few fields may be written, and only through the registry's own writer, so a step can neither
touch the guest's identity or credentials nor leave a half-written record.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# The image installs guest_engine beside the steps; a checkout keeps it under cape/.
ENGINE_DIRECTORIES = (Path("/usr/local/lib/tartarus"), Path(__file__).resolve().parents[3] / "cape")
for directory in ENGINE_DIRECTORIES:
    if (directory / "guest_engine").is_dir():
        sys.path.insert(0, str(directory))
        break

from guest_engine.registry import Registry  # noqa: E402

REFUSED = 2

ALLOWED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "disk_path": (str, type(None)),
    "nvram_path": str,
    "snapshot": str,
    "display": dict,
    "tpm_dir": str,
}


class RefusedError(Exception):
    pass


def parse_value(field: str, text: str) -> Any:
    if field not in ALLOWED_FIELDS:
        allowed = ", ".join(ALLOWED_FIELDS)
        raise RefusedError(f"{field} may not be recorded by a step (allowed: {allowed})")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        raise RefusedError(f"the value of {field} is not valid JSON") from None
    if not isinstance(value, ALLOWED_FIELDS[field]):
        raise RefusedError(f"the value of {field} has the wrong type")
    return value


def record(guest_directory: Path, field: str, text: str) -> None:
    value = parse_value(field, text)
    Registry(guest_directory.parent).update(guest_directory.name, **{field: value})


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="guest-record")
    commands = parser.add_subparsers(dest="command", required=True)
    setter = commands.add_parser("set", help="set one allowed field of $TT_GUEST_DIR/guest.json")
    setter.add_argument("field")
    setter.add_argument("value", help="a JSON value")
    arguments = parser.parse_args(argv)
    guest_directory = os.environ.get("TT_GUEST_DIR")
    if not guest_directory:
        sys.stderr.write("guest-record: TT_GUEST_DIR is not set\n")
        return REFUSED
    try:
        record(Path(guest_directory), arguments.field, arguments.value)
    except RefusedError as refusal:
        sys.stderr.write(f"guest-record: {refusal}\n")
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
