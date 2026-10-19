"""Streaming reader for the Windows event-log XML a guest's wevtutil or PowerShell exports.

Provider-agnostic: Sysmon and Defender normalisers both build on the events yielded here.
"""

import codecs
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree

MAX_READ_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_BEYOND_MICROSECONDS = re.compile(r"(\.\d{6})\d+")


@dataclass(frozen=True)
class WindowsEvent:
    event_id: int
    record_id: int | None
    system_time: datetime | None
    data: Mapping[str, str]


def read_windows_events(path: Path) -> Iterator[WindowsEvent]:
    """Yield events in file order; an unreadable file yields nothing, a truncated one its prefix."""
    try:
        handle = path.open("rb")
    except OSError:
        return
    with handle:
        yield from _parse_events(_BoundedUtf8Reader(handle, MAX_READ_BYTES))


class _BoundedUtf8Reader:
    """Decodes UTF-8 leniently and stops after `limit` raw bytes, ending the stream there.

    Real exports are not always valid UTF-8 (a Polish-locale Sysmon sample carries cp1250 bytes);
    expat would abort on them, so bytes are decoded with replacement before the parser sees them.
    The byte cap bounds the work on a guest-supplied file.
    """

    def __init__(self, raw: BinaryIO, limit: int) -> None:
        self._raw = raw
        self._remaining = limit
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def read(self, size: int = _READ_CHUNK_BYTES) -> str:
        while True:
            chunk = self._raw.read(min(size, self._remaining)) if self._remaining > 0 else b""
            self._remaining -= len(chunk)
            text = self._decoder.decode(chunk, final=not chunk)
            if text or not chunk:
                return text


def _parse_events(source: _BoundedUtf8Reader) -> Iterator[WindowsEvent]:
    root: ElementTree.Element | None = None
    try:
        for kind, element in ElementTree.iterparse(source, events=("start", "end")):  # noqa: S314
            if kind == "start" and root is None:
                root = element
            elif kind == "end" and root is not None and _local_name(element.tag) == "Event":
                event = _to_event(element)
                element.clear()
                # Finished events stay attached to the root; dropping them keeps the tree flat.
                root.clear()
                if event is not None:
                    yield event
    # stdlib ElementTree does not fetch external entities, but it expands internal entity
    # definitions without limit, so the byte cap in _BoundedUtf8Reader bounds that work.
    # A ParseError is also the normal end of a run cut off mid-file.
    except (ElementTree.ParseError, OSError):
        return


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _to_event(element: ElementTree.Element) -> WindowsEvent | None:
    system = element.find("{*}System")
    if system is None:
        return None
    event_id = _to_int(_child_text(system, "{*}EventID"))
    if event_id is None:
        return None
    return WindowsEvent(
        event_id=event_id,
        record_id=_to_int(_child_text(system, "{*}EventRecordID")),
        system_time=_system_time(system),
        data=_event_data(element),
    )


def _child_text(parent: ElementTree.Element, path: str) -> str | None:
    found = parent.find(path)
    return None if found is None else (found.text or "")


def _to_int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def _system_time(system: ElementTree.Element) -> datetime | None:
    time_created = system.find("{*}TimeCreated")
    if time_created is None:
        return None
    return _parse_timestamp(time_created.get("SystemTime", ""))


def _parse_timestamp(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(_BEYOND_MICROSECONDS.sub(r"\1", text))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _event_data(element: ElementTree.Element) -> dict[str, str]:
    return {
        name: data.text or ""
        for data in element.iterfind("{*}EventData/{*}Data")
        if (name := data.get("Name")) is not None
    }
