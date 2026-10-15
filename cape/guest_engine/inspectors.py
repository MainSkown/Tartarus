"""Loads each profile's media inspector from the module file the profile names."""

import importlib.util
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from guest_engine.media import Inspector
from guest_engine.profile import Profile

log = logging.getLogger(__name__)


def load_inspectors(profiles: Mapping[str, Profile]) -> dict[str, Inspector]:
    """The inspector of each profile that has one; a module that will not load is skipped."""
    inspectors: dict[str, Inspector] = {}
    for profile in profiles.values():
        if profile.media.inspector is None or profile.directory is None:
            continue
        file = profile.directory / f"{profile.media.inspector}.py"
        try:
            inspectors[profile.id] = _load_module(profile.id, file)
        except Exception:  # one profile's broken inspector must not stop the engine
            log.exception(
                "the media inspector of profile %s (%s) cannot be loaded", profile.id, file
            )
    return inspectors


def _load_module(profile_id: str, file: Path) -> Inspector:
    spec = importlib.util.spec_from_file_location(f"tartarus_inspector_{profile_id}", file)
    if spec is None or spec.loader is None:
        raise ImportError(f"{file} is not a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A module with `needs_mount` and `inspect` is an Inspector.
    return cast(Inspector, module)
