import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.ingest.capemon_calls import Call
from app.ingest.ecs import (
    EventShape,
    ProcessIdentity,
    base_name,
    file_fields,
    registry_fields,
)

CURRENT_PROCESS_HANDLES = frozenset({0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF})
KEY_CREATED_DISPOSITION = "1"
FILESYSTEM_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\?\?\\|\\\\(?!\.\\))")
PROCESS_CREATING_APIS = frozenset({"NtCreateUserProcess", "CreateProcessInternalW"})


def _derived_shape(action: str, category: str, event_type: str, lane: str) -> EventShape:
    return EventShape(action, (category,), (event_type,), lane, "capemon.derived")


PROCESS_CREATED = _derived_shape("process-created", "process", "start", "process")
PROCESS_TERMINATED = _derived_shape("process-terminated", "process", "end", "process")
FILE_CREATED = _derived_shape("file-created", "file", "creation", "file")
FILE_WRITTEN = _derived_shape("file-written", "file", "change", "file")
FILE_DELETED = _derived_shape("file-deleted", "file", "deletion", "file")
FILE_MOVED = _derived_shape("file-moved", "file", "change", "file")
REG_KEY_CREATED = _derived_shape("reg-key-created", "registry", "creation", "registry")
REG_KEY_DELETED = _derived_shape("reg-key-deleted", "registry", "deletion", "registry")
REG_VALUE_SET = _derived_shape("reg-value-set", "registry", "change", "registry")
REG_VALUE_DELETED = _derived_shape("reg-value-deleted", "registry", "deletion", "registry")
DNS_QUERY = _derived_shape("dns-query", "network", "protocol", "network")
NETWORK_CONNECTION = _derived_shape("network-connection", "network", "connection", "network")
HTTP_REQUEST = _derived_shape("http-request", "network", "protocol", "network")
INJECT_WRITE_MEMORY = _derived_shape("inject-write-memory", "process", "change", "process")
INJECT_THREAD = _derived_shape("inject-thread", "process", "change", "process")
INJECT_MAP_SECTION = _derived_shape("inject-map-section", "process", "change", "process")
INJECT_APC = _derived_shape("inject-apc", "process", "change", "process")


@dataclass(frozen=True)
class Derived:
    shape: EventShape
    summary: str
    sections: dict[str, Any]
    process: ProcessIdentity | None = None


@dataclass
class DerivationRun:
    """What derivation rules need to remember between calls of one report."""

    processes: dict[int, ProcessIdentity]
    created_children: set[int] = field(default_factory=set)


Handler = Callable[[Call], Derived | None]
HANDLERS: dict[str, Handler] = {}


def _derives(*apis: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        HANDLERS.update(dict.fromkeys(apis, handler))
        return handler

    return register


def _filesystem_path(path: str | None) -> str | None:
    return path if path is not None and FILESYSTEM_PATH.match(path) else None


def _is_current_process(handle: int | None) -> bool:
    return handle in CURRENT_PROCESS_HANDLES


def _foreign_target(call: Call) -> tuple[bool, int | None]:
    """Whether the call acts on another process, and that process's pid when the call says it."""
    target_pid = call.integer("ProcessId") or call.integer("ProcessIdentifier")
    if target_pid is not None:
        return target_pid != call.process.pid, target_pid
    handle = call.integer("ProcessHandle")
    return handle is not None and handle != 0 and not _is_current_process(handle), None


def _process_created(call: Call, run: DerivationRun) -> Derived | None:
    child_pid = call.integer("ProcessId")
    if not call.succeeded or not child_pid or child_pid < 0:
        return None
    # capemon logs both NtCreateUserProcess and CreateProcessInternalW for one child; the
    # earliest call (the one processed first) speaks for it.
    if child_pid in run.created_children:
        return None
    run.created_children.add(child_pid)
    child = _child_identity(call, child_pid, run.processes.get(child_pid))
    summary = f"{call.label} started {child.command_line or child.name or f'pid {child_pid}'}"
    return Derived(PROCESS_CREATED, summary, {}, process=child)


def _child_identity(call: Call, child_pid: int, known: ProcessIdentity | None) -> ProcessIdentity:
    known = known or ProcessIdentity(pid=child_pid)
    executable = known.executable or call.text("ImagePathName") or call.text("ApplicationName")
    name = known.name or (base_name(executable) if executable else None)
    return ProcessIdentity(
        pid=child_pid,
        parent_pid=call.process.pid,
        name=name,
        executable=executable,
        command_line=call.text("CommandLine") or known.command_line,
        start=known.start,
        parent_name=call.process.name,
    )


@_derives("NtTerminateProcess")
def _process_terminated(call: Call) -> Derived | None:
    # Handle 0 is RtlExitUserProcess ending the other threads; only -1 ends this process.
    if not call.succeeded or not _is_current_process(call.integer("ProcessHandle")):
        return None
    return Derived(PROCESS_TERMINATED, f"{call.label} terminated", {})


def _file_derivation(call: Call, shape: EventShape, verb: str, argument: str) -> Derived | None:
    path = _filesystem_path(call.text(argument))
    if not call.succeeded or path is None:
        return None
    return Derived(shape, f"{call.label} {verb} {path}", {"file": file_fields(path)})


@_derives("NtWriteFile")
def _file_written(call: Call) -> Derived | None:
    return _file_derivation(call, FILE_WRITTEN, "wrote", "HandleName")


@_derives("NtCreateFile")
def _file_created(call: Call) -> Derived | None:
    if call.text("ExistedBefore") != "no":
        return None
    return _file_derivation(call, FILE_CREATED, "created", "FileName")


@_derives("NtDeleteFile")
def _file_deleted(call: Call) -> Derived | None:
    return _file_derivation(call, FILE_DELETED, "deleted", "FileName")


@_derives("MoveFileWithProgressW")
def _file_moved(call: Call) -> Derived | None:
    source = _filesystem_path(call.text("ExistingFileName"))
    target = _filesystem_path(call.text("NewFileName"))
    if not call.succeeded or source is None or target is None:
        return None
    summary = f"{call.label} moved {source} to {target}"
    return Derived(FILE_MOVED, summary, {"file": file_fields(source, target)})


def _registry_path(call: Call) -> str | None:
    return call.text("FullName") or call.text("ObjectAttributes")


def _registry_derivation(
    call: Call, shape: EventShape, verb: str, *, with_value: bool
) -> Derived | None:
    path = _registry_path(call)
    if not call.succeeded or path is None:
        return None
    fields = (
        registry_fields(
            path,
            value_name=call.text("ValueName"),
            data_type=call.pretty_text("Type"),
            data=call.text("Buffer"),
        )
        if with_value
        else registry_fields(path)
    )
    return Derived(shape, f"{call.label} {verb} {path}", {"registry": fields})


@_derives("RegCreateKeyExA", "RegCreateKeyExW")
def _registry_key_created(call: Call) -> Derived | None:
    if call.text("Disposition") != KEY_CREATED_DISPOSITION:
        return None
    return _registry_derivation(call, REG_KEY_CREATED, "created key", with_value=False)


@_derives("RegSetValueExA", "RegSetValueExW", "NtSetValueKey")
def _registry_value_set(call: Call) -> Derived | None:
    return _registry_derivation(call, REG_VALUE_SET, "set", with_value=True)


@_derives("RegDeleteValueA", "RegDeleteValueW", "NtDeleteValueKey")
def _registry_value_deleted(call: Call) -> Derived | None:
    return _registry_derivation(call, REG_VALUE_DELETED, "deleted value", with_value=True)


@_derives("RegDeleteKeyA", "RegDeleteKeyW", "RegDeleteKeyExA", "RegDeleteKeyExW", "NtDeleteKey")
def _registry_key_deleted(call: Call) -> Derived | None:
    return _registry_derivation(call, REG_KEY_DELETED, "deleted key", with_value=False)


def _dns_handler(name_argument: str) -> Handler:
    def derive(call: Call) -> Derived | None:
        name = call.text(name_argument)
        if name is None:
            return None
        sections = {"dns": {"question": {"name": name}}}
        return Derived(DNS_QUERY, f"{call.label} resolved {name}", sections)

    return derive


_derives("getaddrinfo", "GetAddrInfoW", "GetAddrInfoExW")(_dns_handler("NodeName"))
_derives("DnsQuery_A", "DnsQuery_W", "DnsQuery_UTF8")(_dns_handler("Name"))


@_derives("connect", "WSAConnect")
def _network_connection(call: Call) -> Derived | None:
    address = call.text("ip")
    if address is None:
        return None
    port = call.integer("port")
    destination = {"ip": address} if port is None else {"ip": address, "port": port}
    summary = f"{call.label} connected to {address}" + ("" if port is None else f":{port}")
    return Derived(NETWORK_CONNECTION, summary, {"destination": destination})


@_derives("InternetOpenUrlA", "InternetOpenUrlW")
def _http_request(call: Call) -> Derived | None:
    url = call.text("URL")
    if url is None:
        return None
    return Derived(HTTP_REQUEST, f"{call.label} requested {url}", {"url": {"full": url}})


def _injection_handler(shape: EventShape, verb: str, *, needs_pid: bool = False) -> Handler:
    def derive(call: Call) -> Derived | None:
        foreign, target_pid = _foreign_target(call)
        if not call.succeeded or not foreign or (needs_pid and target_pid is None):
            return None
        target = "another process" if target_pid is None else f"pid {target_pid}"
        return Derived(shape, f"{call.label} {verb} {target}", {})

    return derive


_derives("NtWriteVirtualMemory", "WriteProcessMemory")(
    _injection_handler(INJECT_WRITE_MEMORY, "wrote memory of")
)
_derives("NtCreateThreadEx", "NtCreateThread", "CreateRemoteThread", "CreateRemoteThreadEx")(
    _injection_handler(INJECT_THREAD, "started a thread in")
)
_derives("NtMapViewOfSection")(_injection_handler(INJECT_MAP_SECTION, "mapped a section into"))
_derives("NtQueueApcThread", "NtQueueApcThreadEx", "QueueUserAPC")(
    _injection_handler(INJECT_APC, "queued an APC in", needs_pid=True)
)


def derive(call: Call, run: DerivationRun) -> Derived | None:
    if call.api in PROCESS_CREATING_APIS:
        return _process_created(call, run)
    handler = HANDLERS.get(call.api)
    return handler(call) if handler else None
