import re
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.live.bson_document import BsonError, decode_document
from app.live.log_values import (
    clock_text,
    filetime_to_datetime,
    hex_word,
    render_argument,
    render_return,
    render_text,
)

MAX_MESSAGE_SIZE = 20 * 1024 * 1024
_LENGTH_PREFIX = struct.Struct("<I")
_MIN_MESSAGE_SIZE = 5
_UNKNOWN_CATEGORY = "unknown"
_STATUS_ARGUMENT = "is_success"
_RETURN_ARGUMENT = "retval"
_PROCESS_API = "__process__"
_THREAD_API = "__thread__"
_ENVIRON_API = "__environ__"
_PROCESS_FIELDS = (
    "TimeLow",
    "TimeHigh",
    "ProcessIdentifier",
    "ParentProcessIdentifier",
    "ModulePath",
)
_DWORD_MASK = 2**32 - 1
_TAGGED_ARGUMENT_LENGTH = 2
_PATH_SEPARATORS = re.compile(r"[\\/]")


@dataclass(frozen=True)
class Argument:
    name: str
    value: str
    tag: str | None


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    name: str
    module_path: str
    parent_pid: int
    first_seen: datetime
    first_seen_text: str


@dataclass(frozen=True)
class ThreadRecord:
    pid: int
    thread_id: int


@dataclass(frozen=True)
class EnvironRecord:
    values: dict[str, str]


@dataclass(frozen=True)
class CallRecord:
    index: int
    api: str
    category: str
    thread_id: int
    timestamp: datetime
    timestamp_text: str
    caller: str
    parent_caller: str
    status: bool
    return_value: str
    repeated: int
    arguments: tuple[Argument, ...]


@dataclass(frozen=True)
class UnknownRecord:
    kind: str
    reason: str
    offset: int
    document: dict[str, Any]


type LogRecord = ProcessRecord | ThreadRecord | EnvironRecord | CallRecord | UnknownRecord


class LogFormatError(Exception):
    """The log is not a valid stream of capemon BSON messages; the parser cannot continue.

    ``offset`` is the stream position of the offending message and ``parsed`` holds the records
    that were complete before it in the same ``feed`` call.
    """

    def __init__(self, offset: int, reason: str) -> None:
        super().__init__(f"invalid capemon log at byte {offset}: {reason}")
        self.offset = offset
        self.reason = reason
        self.parsed: list[LogRecord] = []


@dataclass(frozen=True)
class _ArgumentSpec:
    name: str
    tag: str | None


@dataclass(frozen=True)
class _ApiInfo:
    name: str
    category: str
    arguments: tuple[_ArgumentSpec, ...]


class BsonLogParser:
    """Turns the bytes of one process's ``logs/<pid>.bson`` into records, as they arrive.

    Use one parser per log file: the info messages that explain each API index are remembered
    for the file's lifetime. A trailing partial message waits for more bytes. After a
    ``LogFormatError`` every further ``feed`` raises that same error.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._consumed = 0
        self._apis: dict[int, _ApiInfo] = {}
        self._process_start: datetime | None = None
        self._call_count = 0
        self._failure: LogFormatError | None = None

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, chunk: bytes) -> list[LogRecord]:
        if self._failure is not None:
            raise self._failure
        self._buffer += chunk
        records: list[LogRecord] = []
        try:
            self._drain(records)
        except LogFormatError as error:
            error.parsed = records
            self._failure = error
            raise
        return records

    def _drain(self, records: list[LogRecord]) -> None:
        position = 0
        try:
            while (size := self._complete_message_size(position)) is not None:
                document = self._decode(position, size)
                if (record := self._record(document, self._consumed + position)) is not None:
                    records.append(record)
                position += size
        finally:
            del self._buffer[:position]
            self._consumed += position

    def _complete_message_size(self, position: int) -> int | None:
        if len(self._buffer) - position < _LENGTH_PREFIX.size:
            return None
        size: int = _LENGTH_PREFIX.unpack_from(self._buffer, position)[0]
        offset = self._consumed + position
        if size > MAX_MESSAGE_SIZE:
            raise LogFormatError(offset, f"message of {size} bytes exceeds {MAX_MESSAGE_SIZE}")
        if size < _MIN_MESSAGE_SIZE:
            raise LogFormatError(offset, f"message length {size} is below the BSON minimum")
        return size if len(self._buffer) - position >= size else None

    def _decode(self, position: int, size: int) -> dict[str, Any]:
        try:
            return decode_document(self._buffer[position : position + size])
        except BsonError as error:
            raise LogFormatError(self._consumed + position, str(error)) from error

    def _record(self, document: dict[str, Any], offset: int) -> LogRecord | None:
        try:
            return self._record_for(document, offset)
        except (ArithmeticError, ValueError, TypeError) as error:
            # Guest-controlled values (a FILETIME or elapsed time past year 9999) can break the
            # record building; that is a corrupt log, not a bug to retry on every poll.
            raise LogFormatError(offset, f"{type(error).__name__}: {error}") from error

    def _record_for(self, document: dict[str, Any], offset: int) -> LogRecord | None:
        kind = document.get("type")
        if kind is None:
            return self._call_message(document, offset)
        if kind == "info":
            return self._define_api(document, offset)
        return UnknownRecord(str(kind), "message type not understood", offset, document)

    def _define_api(self, document: dict[str, Any], offset: int) -> UnknownRecord | None:
        index, name = document.get("I"), document.get("name", "NONAME")
        specs = _argument_specs(document.get("args", []))
        if not isinstance(index, int) or not isinstance(name, str) or specs is None:
            return UnknownRecord("info", "malformed api description", offset, document)
        category = document.get("category")
        self._apis[index] = _ApiInfo(
            name,
            category if isinstance(category, str) and category else _UNKNOWN_CATEGORY,
            specs,
        )
        return None

    def _call_message(self, document: dict[str, Any], offset: int) -> LogRecord:
        index = document.get("I")
        api = self._apis.get(index) if isinstance(index, int) else None
        if api is None:
            reason = f"call refers to api index {index} that no info message explained"
            return UnknownRecord("call", reason, offset, document)
        values = document.get("args", [])
        if not isinstance(values, list) or len(values) != len(api.arguments):
            carried = len(values) if isinstance(values, list) else type(values).__name__
            reason = f"{api.name} carries {carried} values for {len(api.arguments)} names"
            return UnknownRecord("call", reason, offset, document)
        named = [(spec, value) for spec, value in zip(api.arguments, values, strict=True)]
        named += _auxiliary_values(document.get("aux"))
        return self._record_from_named_values(api, document, named, offset)

    def _record_from_named_values(
        self,
        api: _ApiInfo,
        document: dict[str, Any],
        named: list[tuple[_ArgumentSpec, Any]],
        offset: int,
    ) -> LogRecord:
        context = _integers(document, ("T", "t", "R", "P", "r"))
        if context is None:
            return UnknownRecord("call", "call context fields are not integers", offset, document)
        if api.name == _PROCESS_API:
            return self._process_record(named, offset, document)
        if api.name == _THREAD_API:
            return _thread_record(named, context[0], offset, document)
        if api.name == _ENVIRON_API:
            return EnvironRecord(
                {arg.name: arg.value for arg in _rendered(named) if not _is_bookkeeping(arg.name)}
            )
        return self._call_record(api, named, context, offset, document)

    def _process_record(
        self, named: list[tuple[_ArgumentSpec, Any]], offset: int, document: dict[str, Any]
    ) -> LogRecord:
        fields = _process_fields(named)
        if fields is None:
            return UnknownRecord("process", "process record lacks its fields", offset, document)
        low, high, pid, parent_pid, path = fields
        module_path = render_text(path)
        first_seen = filetime_to_datetime(low, high)
        self._process_start = first_seen
        return ProcessRecord(
            pid=_dword(pid),
            name=_PATH_SEPARATORS.split(module_path)[-1],
            module_path=module_path,
            parent_pid=_dword(parent_pid),
            first_seen=first_seen,
            first_seen_text=clock_text(first_seen),
        )

    def _call_record(
        self,
        api: _ApiInfo,
        named: list[tuple[_ArgumentSpec, Any]],
        context: list[int],
        offset: int,
        document: dict[str, Any],
    ) -> LogRecord:
        if self._process_start is None:
            return UnknownRecord("call", "call precedes the process record", offset, document)
        thread_id, elapsed_ms, caller, parent_caller, repeated = context
        status, returned = _status_and_return(named)
        moment = self._process_start + timedelta(milliseconds=elapsed_ms)
        index, self._call_count = self._call_count, self._call_count + 1
        return CallRecord(
            index=index,
            api=api.name,
            category=api.category,
            thread_id=thread_id,
            timestamp=moment,
            timestamp_text=clock_text(moment),
            caller=hex_word(caller),
            parent_caller=hex_word(parent_caller),
            status=status,
            return_value=returned,
            repeated=repeated,
            arguments=tuple(arg for arg in _rendered(named) if not _is_bookkeeping(arg.name)),
        )


def _argument_specs(raw: Any) -> tuple[_ArgumentSpec, ...] | None:
    if not isinstance(raw, list):
        return None
    specs: list[_ArgumentSpec] = []
    for item in raw:
        if isinstance(item, str):
            specs.append(_ArgumentSpec(item, None))
        elif (
            isinstance(item, list)
            and len(item) == _TAGGED_ARGUMENT_LENGTH
            and all(isinstance(x, str) for x in item)
        ):
            specs.append(_ArgumentSpec(item[0], item[1]))
        else:
            return None
    return tuple(specs)


def _process_fields(
    named: list[tuple[_ArgumentSpec, Any]],
) -> tuple[int, int, int, int, bytes | str] | None:
    values = {spec.name: value for spec, value in named}
    low, high, pid, parent_pid, path = (values.get(name) for name in _PROCESS_FIELDS)
    if (
        isinstance(low, int)
        and isinstance(high, int)
        and isinstance(pid, int)
        and isinstance(parent_pid, int)
        and isinstance(path, bytes | str)
    ):
        return low, high, pid, parent_pid, path
    return None


def _auxiliary_values(raw: Any) -> list[tuple[_ArgumentSpec, Any]]:
    if not isinstance(raw, dict):
        return []
    return [(_ArgumentSpec(name, None), value) for name, value in raw.items()]


def _integers(document: dict[str, Any], names: tuple[str, ...]) -> list[int] | None:
    values = [document.get(name, 0) for name in names]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return None
    return values


def _dword(value: int) -> int:
    # The monitor stores 32-bit ids in 64-bit slots whose upper half is uninitialised.
    return value & _DWORD_MASK


def _is_bookkeeping(name: str) -> bool:
    return name in (_STATUS_ARGUMENT, _RETURN_ARGUMENT)


def _rendered(named: list[tuple[_ArgumentSpec, Any]]) -> list[Argument]:
    return [Argument(spec.name, render_argument(raw, spec.tag), spec.tag) for spec, raw in named]


def _status_and_return(named: list[tuple[_ArgumentSpec, Any]]) -> tuple[bool, str]:
    raw = {spec.name: value for spec, value in named}
    success = raw.get(_STATUS_ARGUMENT, 1)
    return (success != 0 if isinstance(success, int) else True), render_return(
        raw.get(_RETURN_ARGUMENT, 0)
    )


def _thread_record(
    named: list[tuple[_ArgumentSpec, Any]], thread_id: int, offset: int, document: dict[str, Any]
) -> LogRecord:
    pid = {spec.name: value for spec, value in named}.get("ProcessIdentifier")
    if not isinstance(pid, int):
        return UnknownRecord("thread", "thread record lacks its process", offset, document)
    return ThreadRecord(pid=_dword(pid), thread_id=thread_id)
