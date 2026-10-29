import re
from collections.abc import Iterable
from typing import Any

TIMESTAMP = "@timestamp"


def entry_sha256(process_created_events: Iterable[dict[str, Any]], entry: str) -> str | None:
    """SHA256 of the file a zip analysis ran, from the first process started from `%TEMP%\\<entry>`.

    CAPE leaves the entry out of its report when `file=` is set, but Sysmon logs the hash of every
    process image. An entry that is not an executable (a dll, bat or js is run through rundll32,
    cmd or wscript) has no process of its own, so the answer is None, not the interpreter's hash.
    """
    in_temp = re.compile(rf"\\temp\\{re.escape(_windows_path(entry))}$", re.IGNORECASE)
    started = [
        event
        for event in process_created_events
        if in_temp.search(event.get("process", {}).get("executable", ""))
    ]
    if not started:
        return None
    # `format_timestamp` writes a fixed-width UTC string, which sorts as time does.
    earliest = min(started, key=lambda event: event[TIMESTAMP])
    sha256: str | None = earliest["process"].get("hash", {}).get("sha256")
    return sha256


def _windows_path(entry: str) -> str:
    return entry.replace("/", "\\")
