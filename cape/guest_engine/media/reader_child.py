"""The child process of `reading.read_inside`: opens the disc on stdin and runs a reader over it.

Run as `python3 -I reader_child.py READER ADDRESS_SPACE_BYTES CPU_SECONDS` with the disc image as
standard input. It imports nothing but the standard library and pycdlib, so that the only code that
meets the untrusted image is this file, pycdlib and the profile's reader.

READER is a Python file with `read(image)`, where `image` is an `IsoImage`; whatever it returns
must be JSON data. The child prints `{"result": ...}`, or `{"fault": ...}` when the image cannot be
read at all; any other failure is an uncaught exception, which exits non-zero.
"""

import importlib.util
import json
import resource
import sys
from collections.abc import Callable
from typing import Any, BinaryIO

NOT_AN_ISO = "not_an_iso"
UNSUPPORTED_FILESYSTEM = "unsupported_filesystem"
TOOL_MISSING = "tool_missing"

# The order the filesystems of a disc are tried in: Microsoft's media are UDF, a rebuilt or older
# image may have only Joliet or plain ISO 9660 names. (pycdlib keyword, the name of one entry)
NAMESPACES = (
    ("udf_path", lambda entry: _decode(entry, entry.file_ident.encoding or "latin-1")),
    ("joliet_path", lambda entry: _decode(entry, "utf-16-be")),
    ("iso_path", lambda entry: _decode(entry, "latin-1")),
)


class Unreadable(Exception):  # noqa: N818 - carries the fault the child answers with
    def __init__(self, fault: str) -> None:
        super().__init__(fault)
        self.fault = fault


class IsoImage:
    """A disc image whose files are found by name, in any case, whichever filesystem has them."""

    def __init__(self, iso: Any) -> None:
        self._iso = iso
        self._available = [
            (keyword, name_of)
            for (keyword, name_of), present in zip(
                NAMESPACES, (iso.has_udf(), iso.has_joliet(), True), strict=True
            )
            if present
        ]

    def exists(self, *path: str) -> bool:
        """Whether the disc has a file at `path`; raises `Unreadable` as `open` does."""
        return self._locate(path) is not None

    def open(self, *path: str) -> BinaryIO | None:
        """The file at `path` as a seekable binary file, or None when the disc has no such file.

        Raises `Unreadable` when no filesystem of the disc can be listed at all.
        """
        located = self._locate(path)
        if located is None:
            return None
        keyword, found = located
        # pycdlib sets the file up only in `__enter__`; the child exits long before it matters.
        return self._iso.open_file_from_iso(**{keyword: found}).__enter__()  # type: ignore[no-any-return]

    def _locate(self, path: tuple[str, ...]) -> tuple[str, str] | None:
        broken = 0
        for keyword, name_of in self._available:
            try:
                found = self._find(keyword, name_of, path)
            except Exception:  # noqa: BLE001 - a damaged tree in one filesystem; the next may be fine
                broken += 1
                continue
            if found is not None:
                return keyword, found
        if broken == len(self._available):
            raise Unreadable(UNSUPPORTED_FILESYSTEM)
        return None

    def _find(
        self, keyword: str, name_of: Callable[[Any], str], path: tuple[str, ...]
    ) -> str | None:
        directory = ""
        for position, wanted in enumerate(path):
            is_last = position == len(path) - 1
            match = self._child_named(keyword, name_of, directory or "/", wanted)
            if match is None:
                return None
            identifier, is_directory = match
            if (
                is_directory == is_last
            ):  # a file in the middle of the path, or a directory at its end
                return None
            directory = f"{directory}/{identifier}"
        return directory

    def _child_named(
        self, keyword: str, name_of: Callable[[Any], str], directory: str, wanted: str
    ) -> tuple[str, bool] | None:
        for child in self._iso.list_children(**{keyword: directory}):
            if child is None:
                continue
            identifier = name_of(child)
            if _plain_name(identifier) == wanted.lower():
                return identifier, child.is_dir()
        return None


def _decode(entry: Any, encoding: str) -> str:
    return bytes(entry.file_identifier()).decode(encoding, errors="replace")


def _plain_name(identifier: str) -> str:
    """The name as a person reads it: no ISO 9660 version (`;1`), no dot of an empty extension."""
    return identifier.partition(";")[0].lower().removesuffix(".")


def limit_resources(address_space_bytes: int, cpu_seconds: int) -> None:
    for kind, limit in (
        (resource.RLIMIT_AS, address_space_bytes),
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, 0),
        (resource.RLIMIT_CORE, 0),
    ):
        resource.setrlimit(kind, (limit, limit))


def load_reader(path: str) -> Any:
    spec = importlib.util.spec_from_file_location("media_reader", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path} is not a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(arguments: list[str]) -> None:
    reader_path, address_space_bytes, cpu_seconds = arguments
    # A reader that prints would corrupt the answer, so print goes to stderr from here on.
    output, sys.stdout = sys.stdout, sys.stderr

    def answer(payload: dict[str, Any]) -> None:
        output.write(json.dumps(payload))

    limit_resources(int(address_space_bytes), int(cpu_seconds))
    try:
        import pycdlib  # noqa: PLC0415 - after the limits, and a missing library is an answer
    except ImportError:
        answer({"fault": TOOL_MISSING})
        return
    reader = load_reader(reader_path)
    iso = pycdlib.PyCdlib()
    try:
        iso.open_fp(sys.stdin.buffer)
    except Exception:  # noqa: BLE001 - pycdlib raises more than its own exceptions on garbage
        answer({"fault": NOT_AN_ISO})
        return
    try:
        answer({"result": reader.read(IsoImage(iso))})
    except Unreadable as unreadable:
        answer({"fault": unreadable.fault})


if __name__ == "__main__":
    main(sys.argv[1:])
