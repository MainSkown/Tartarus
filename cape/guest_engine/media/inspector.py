from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from guest_engine.media.commands import Runner


@dataclass(frozen=True)
class MediaContext:
    """What a scan hands to an inspector.

    `runner` runs external tools. `read_inside(image, reader)` looks inside the image without
    mounting it: `reader` is a Python file with a `read(image)` function, run in a short-lived
    unprivileged child process that has the disc open (see `reading.py`); it returns what `read`
    returned, as JSON data, or raises `MediaProblem` when the disc cannot be read.
    """

    runner: Runner
    read_inside: Callable[[Path, Path], Any]


class Inspector(Protocol):
    """A profile's way of recognising its own installation media.

    `inspect` returns None when the file is not this profile's media, a dict of
    `kind` (installer | disk_image), `variants`, `version`, `build`, `language`, `arch` when it is,
    and raises `MediaProblem` when it is this profile's kind of medium but cannot be read.
    """

    def inspect(self, path: Path, context: MediaContext) -> dict[str, Any] | None: ...
