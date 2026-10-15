from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from guest_engine.media.commands import Runner


@dataclass(frozen=True)
class MediaContext:
    """What a scan hands to an inspector.

    `runner` runs external tools; `mounted(path)` is a context manager yielding the directory of
    a read-only loop mount of the image, and is only available to inspectors that declare
    `needs_mount = True`.
    """

    runner: Runner
    mounted: Callable[[Path], AbstractContextManager[Path]]


class Inspector(Protocol):
    """A profile's way of recognising its own installation media.

    `inspect` returns None when the file is not this profile's media, a dict of
    `kind` (installer | disk_image), `variants`, `version`, `build`, `language`, `arch` when it is,
    and raises `MediaProblem` when it is this profile's kind of medium but cannot be read.
    """

    needs_mount: bool

    def inspect(self, path: Path, context: MediaContext) -> dict[str, Any] | None: ...
