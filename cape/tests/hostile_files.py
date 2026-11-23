"""What a compromised `lan-sim` daemon can leave where a root process of the cape container reads.

The daemon owns `status/` and `logs/`, so it can make any name in them a pipe (a reader that opens
it blocks forever), a link to a file the daemon may not read, a directory, or an enormous file.
`bounded` runs a call in a thread so that a reader which blocks fails its test instead of hanging
the suite.
"""

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

BOUND_S = 5.0
KINDS = ("fifo", "symlink", "dangling-symlink", "directory")


def bounded[T](function: Callable[..., T], *arguments: Any, **options: Any) -> T:
    outcome: list[tuple[str, Any]] = []

    def run() -> None:
        try:
            outcome.append(("result", function(*arguments, **options)))
        except BaseException as error:  # noqa: BLE001 - handed back to the test's thread
            outcome.append(("error", error))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(BOUND_S)
    assert not thread.is_alive(), f"{function.__name__} blocked for more than {BOUND_S} s"
    kind, value = outcome[0]
    if kind == "error":
        raise value
    return value


def plant(kind: str, path: Path, secret: Path) -> None:
    """Puts something hostile at `path`; `secret` is the file a link points at."""
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "symlink":
        secret.write_text('{"state":"closed","error":null}')
        path.symlink_to(secret)
    elif kind == "dangling-symlink":
        path.symlink_to(path.parent / "nowhere")
    elif kind == "directory":
        path.mkdir()
    else:
        raise ValueError(kind)
