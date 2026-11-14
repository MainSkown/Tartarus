import logging
import os
from collections.abc import Iterator, Mapping
from functools import partial
from pathlib import Path
from typing import Any

from guest_engine.media.commands import Runner
from guest_engine.media.errors import Fault, MediaProblem
from guest_engine.media.inspector import Inspector, MediaContext
from guest_engine.media.reading import read_inside

log = logging.getLogger(__name__)

type Entry = dict[str, Any]


def scan_media(
    directory: Path,
    inspectors: Mapping[str, Inspector],
    runner: Runner,
) -> list[Entry]:
    """Every medium in `directory` that an inspector recognises, and every file that none does.

    One entry per (file, profile) that recognised it; a file nobody recognised, or that could not
    be read, has one entry with `profile: None` and an `error` message. No cache: reading an image
    takes a child process and a few hundredths of a second.
    """
    context = MediaContext(runner, partial(read_inside, runner))
    entries: list[Entry] = []
    for name, path in _regular_files(directory):
        stat = path.stat()
        identity = {"file": name, "size": stat.st_size, "mtime": int(stat.st_mtime)}
        recognised, problem = _ask_inspectors(path, inspectors, context)
        if recognised:
            entries.extend(
                {**identity, "profile": profile, **found, "sha256": None}
                for profile, found in recognised
            )
        else:
            entries.append({**identity, "profile": None, "error": str(problem)})
    return entries


def _regular_files(directory: Path) -> Iterator[tuple[str, Path]]:
    if not directory.is_dir():
        return
    root = directory.resolve()
    for name in sorted(os.listdir(root)):
        if name.startswith("."):
            continue
        resolved = (root / name).resolve()
        if resolved.is_file() and resolved.is_relative_to(root):
            yield name, resolved


def _ask_inspectors(
    path: Path, inspectors: Mapping[str, Inspector], context: MediaContext
) -> tuple[list[tuple[str, Entry]], MediaProblem]:
    recognised: list[tuple[str, Entry]] = []
    problem = MediaProblem(Fault.UNRECOGNISED)
    for profile, inspector in inspectors.items():
        try:
            found = inspector.inspect(path, context)
        except MediaProblem as raised:
            problem = _more_specific(problem, raised)
        except Exception:  # one inspector's bug must not take the whole listing down
            log.exception("inspector %r failed on %s", profile, path)
            problem = _more_specific(problem, MediaProblem(Fault.INSPECTION_FAILED))
        else:
            if found is not None:
                recognised.append((profile, found))
    return recognised, problem


def _more_specific(current: MediaProblem, raised: MediaProblem) -> MediaProblem:
    return raised if current.fault is Fault.UNRECOGNISED else current
