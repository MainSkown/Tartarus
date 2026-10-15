"""The two profile fixtures every engine test builds on: a Windows one and a Linux one."""

import copy
import json
from pathlib import Path
from typing import Any

from guest_engine.profile import Profile, parse_profile

FIXTURE_DIR = Path(__file__).parent
PROFILE_FIXTURES = FIXTURE_DIR / "profiles"


def profile_data(name: str) -> dict[str, Any]:
    return json.loads((PROFILE_FIXTURES / f"{name}.json").read_text())


def sample_profile(name: str) -> Profile:
    return parse_profile(profile_data(name))


def with_value(data: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """A deep copy of `data` with the value at dotted `path` replaced (list indexes are numbers)."""
    changed = copy.deepcopy(data)
    *parents, last = path.split(".")
    target: Any = changed
    for key in parents:
        target = target[int(key)] if isinstance(target, list) else target[key]
    if isinstance(target, list):
        target[int(last)] = value
    else:
        target[last] = value
    return changed


def without(data: dict[str, Any], path: str) -> dict[str, Any]:
    changed = copy.deepcopy(data)
    *parents, last = path.split(".")
    target: Any = changed
    for key in parents:
        target = target[int(key)] if isinstance(target, list) else target[key]
    del target[int(last) if isinstance(target, list) else last]
    return changed
