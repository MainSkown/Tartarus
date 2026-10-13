from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.ingest.clock import parse_clock
from app.ingest.ecs import ProcessIdentity
from app.ingest.reading import mapping_list, section, text_or_none, to_int


@dataclass(frozen=True)
class Call:
    """One capemon API call with the process that made it, read defensively from the report."""

    raw: Mapping[str, Any]
    index: int
    api: str
    timestamp: datetime
    call_id: int
    process: ProcessIdentity
    thread_id: int | None
    category: str | None
    status: bool | None
    return_value: str | None
    repeated: int | None
    arguments: Mapping[str, str]
    pretty_values: Mapping[str, str]

    @property
    def succeeded(self) -> bool:
        return self.status is True

    def text(self, name: str) -> str | None:
        return self.arguments.get(name) or None

    def integer(self, name: str) -> int | None:
        return to_int(self.arguments.get(name))

    def pretty_text(self, name: str) -> str | None:
        return self.pretty_values.get(name)

    @property
    def label(self) -> str:
        return self.process.name or f"pid {self.process.pid}"


@dataclass(frozen=True)
class CapemonProcess:
    identity: ProcessIdentity
    calls: list[Any]


def read_processes(report: Mapping[str, Any], clock_offset: timedelta) -> list[CapemonProcess]:
    entries = mapping_list(section(report, "behavior").get("processes"))
    entries = [entry for entry in entries if to_int(entry.get("process_id")) is not None]
    names = {
        to_int(entry["process_id"]): text_or_none(entry.get("process_name")) for entry in entries
    }
    return [
        CapemonProcess(
            _identity(entry, names, clock_offset),
            calls if isinstance(calls := entry.get("calls"), list) else [],
        )
        for entry in entries
    ]


def _shifted(value: object, clock_offset: timedelta) -> datetime | None:
    moment = parse_clock(value)
    return None if moment is None else moment + clock_offset


def _identity(
    entry: Mapping[str, Any], names: Mapping[int | None, str | None], clock_offset: timedelta
) -> ProcessIdentity:
    environ = entry.get("environ")
    command_line = (
        text_or_none(environ.get("CommandLine")) if isinstance(environ, Mapping) else None
    )
    parent_pid = to_int(entry.get("parent_id"))
    return ProcessIdentity(
        pid=to_int(entry["process_id"]) or 0,
        parent_pid=parent_pid,
        name=text_or_none(entry.get("process_name")),
        executable=text_or_none(entry.get("module_path")),
        command_line=command_line.strip() if command_line else None,
        start=_shifted(entry.get("first_seen"), clock_offset),
        parent_name=names.get(parent_pid),
    )


def _flat_arguments(raw_arguments: object) -> tuple[dict[str, str], dict[str, str]]:
    values: dict[str, str] = {}
    pretty: dict[str, str] = {}
    for argument in raw_arguments if isinstance(raw_arguments, list) else []:
        name = argument.get("name") if isinstance(argument, Mapping) else None
        if not isinstance(name, str) or name in values:
            continue
        value = argument.get("value")
        values[name] = "" if value is None else str(value)
        if isinstance(pretty_value := argument.get("pretty_value"), str):
            pretty[name] = pretty_value
    return values, pretty


def _read_call(
    raw: object,
    index: int,
    process: ProcessIdentity,
    clock_offset: timedelta,
    fallback_time: datetime,
) -> Call | None:
    if not isinstance(raw, Mapping) or not (api := text_or_none(raw.get("api"))):
        return None
    arguments, pretty = _flat_arguments(raw.get("arguments"))
    status = raw.get("status")
    repeated = raw.get("repeated")
    return Call(
        raw=raw,
        index=index,
        api=api,
        timestamp=_shifted(raw.get("timestamp"), clock_offset) or fallback_time,
        call_id=to_int(raw.get("id")) or 0,
        process=process,
        thread_id=to_int(raw.get("thread_id")),
        category=text_or_none(raw.get("category")),
        status=status if isinstance(status, bool) else None,
        return_value=text_or_none(raw.get("return")),
        repeated=repeated if isinstance(repeated, int) and not isinstance(repeated, bool) else None,
        arguments=arguments,
        pretty_values=pretty,
    )


def calls_in_sequence_order(
    processes: list[CapemonProcess], clock_offset: timedelta, fallback_time: datetime
) -> list[Call]:
    index = 0
    calls: list[Call] = []
    for process in processes:
        for raw in process.calls:
            call = _read_call(raw, index, process.identity, clock_offset, fallback_time)
            index += 1
            if call is not None:
                calls.append(call)
    return sorted(calls, key=lambda call: (call.timestamp, call.call_id, call.index))
