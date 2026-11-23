"""A fake service control manager: services are created, started and deleted in memory only.

psexec, smbexec and nxc speak this interface to run a command as a service. The manager records
the service name and binary path, which is the evidence, and answers as if it had obeyed; it never
starts a process and never evaluates the path.
"""

from typing import Protocol
from uuid import UUID

from impacket.dcerpc.v5 import scmr
from impacket.dcerpc.v5.dtypes import NULL

from lan_sim.services.smb_rpc import FAULT_OP_RANGE_ERROR, RpcFaultError, new_call_handle
from lan_sim.services.smb_services import (
    SERVICE_RUNNING,
    SERVICE_STOPPED,
    ServiceError,
    ServiceRecord,
    ServiceTable,
)

ERROR_INVALID_HANDLE = 6
ERROR_MORE_DATA = 234
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_SERVICE_ALREADY_RUNNING = 1056
MAX_HANDLES = 64
MAX_ENUM_BUFFER_BYTES = 256 * 1024
SERVICE_CONTROL_STOP = 1
SERVICE_ACCEPT_STOP = 1
SERVICE_STATE_ACTIVE, SERVICE_STATE_INACTIVE = 1, 2
STATUS_BYTES = 28
ENTRY_BYTES = 8 + STATUS_BYTES
NO_HANDLE = bytes(20)
_HANDLE_FIELDS = {"lpScHandle", "lpServiceHandle", "hSCObject"}
_POINTER_FIELDS = {"lpdwTagId", "lpResumeIndex"}

_OPNUM_CLOSE, _OPNUM_CONTROL, _OPNUM_DELETE, _OPNUM_QUERY_STATUS = 0, 1, 2, 6
_OPNUM_CREATE, _OPNUM_ENUM, _OPNUM_OPEN_SCM, _OPNUM_OPEN_SERVICE, _OPNUM_START = 12, 14, 15, 16, 19


class _Log(Protocol):
    def service_request(self, *, name: str, detail: str) -> bool: ...


def _text(value: object) -> str:
    """An NDR string as text; a NULL pointer is the empty string."""
    return value.rstrip("\x00") if isinstance(value, str) else ""


class SvcctlInterface:
    uuid = UUID("367ABB81-9844-35F1-AD32-98F038001003").bytes_le
    major_version = 2
    pipe_name = "svcctl"

    def __init__(self, services: ServiceTable, log: _Log) -> None:
        self._services = services
        self._log = log
        self._handles: dict[bytes, tuple[str, str]] = {}
        self._calls = {
            _OPNUM_CLOSE: self._close,
            _OPNUM_CONTROL: self._control,
            _OPNUM_DELETE: self._delete,
            _OPNUM_QUERY_STATUS: self._query_status,
            _OPNUM_CREATE: self._create,
            _OPNUM_ENUM: self._enumerate,
            _OPNUM_OPEN_SCM: self._open_manager,
            _OPNUM_OPEN_SERVICE: self._open_service,
            _OPNUM_START: self._start,
        }

    def call(self, opnum: int, stub: bytes) -> bytes:
        handler = self._calls.get(opnum)
        if handler is None:
            raise RpcFaultError(FAULT_OP_RANGE_ERROR)
        try:
            return bytes(handler(stub).getData())
        except ServiceError as error:
            return bytes(self._failure(opnum, error.code).getData())

    def _open_manager(self, stub: bytes) -> scmr.ROpenSCManagerWResponse:
        scmr.ROpenSCManagerW(stub)
        response = scmr.ROpenSCManagerWResponse()
        response["lpScHandle"] = self._new_handle("manager", "")
        response["ErrorCode"] = 0
        return response

    def _open_service(self, stub: bytes) -> scmr.ROpenServiceWResponse:
        request = scmr.ROpenServiceW(stub)
        self._lookup(request["hSCManager"], "manager")
        record = self._services.get(_text(request["lpServiceName"]))
        response = scmr.ROpenServiceWResponse()
        response["lpServiceHandle"] = self._new_handle("service", record.name)
        response["ErrorCode"] = 0
        return response

    def _create(self, stub: bytes) -> scmr.RCreateServiceWResponse:
        request = scmr.RCreateServiceW(stub)
        self._lookup(request["hSCManager"], "manager")
        name, binary = _text(request["lpServiceName"]), _text(request["lpBinaryPathName"])
        record = self._services.create(
            name,
            _text(request["lpDisplayName"]),
            binary,
            service_type=request["dwServiceType"],
            start_type=request["dwStartType"],
        )
        self._log.service_request(name="svcctl CreateService", detail=f"{record.name}, {binary}")
        response = scmr.RCreateServiceWResponse()
        response["lpdwTagId"] = NULL
        response["lpServiceHandle"] = self._new_handle("service", record.name)
        response["ErrorCode"] = 0
        return response

    def _start(self, stub: bytes) -> scmr.RStartServiceWResponse:
        record = self._service_of(scmr.RStartServiceW(stub)["hService"])
        self._log.service_request(
            name="svcctl StartService", detail=f"{record.name}, {record.binary_path}"
        )
        if record.state == SERVICE_RUNNING:
            raise ServiceError(ERROR_SERVICE_ALREADY_RUNNING)
        record.state = SERVICE_RUNNING
        response = scmr.RStartServiceWResponse()
        response["ErrorCode"] = 0
        return response

    def _control(self, stub: bytes) -> scmr.RControlServiceResponse:
        request = scmr.RControlService(stub)
        record = self._service_of(request["hService"])
        if request["dwControl"] == SERVICE_CONTROL_STOP:
            if record.state != SERVICE_RUNNING:
                raise ServiceError(ERROR_SERVICE_NOT_ACTIVE)
            record.state = SERVICE_STOPPED
        response = scmr.RControlServiceResponse()
        self._fill_status(response["lpServiceStatus"], record)
        response["ErrorCode"] = 0
        return response

    def _query_status(self, stub: bytes) -> scmr.RQueryServiceStatusResponse:
        record = self._service_of(scmr.RQueryServiceStatus(stub)["hService"])
        response = scmr.RQueryServiceStatusResponse()
        self._fill_status(response["lpServiceStatus"], record)
        response["ErrorCode"] = 0
        return response

    def _delete(self, stub: bytes) -> scmr.RDeleteServiceResponse:
        record = self._service_of(scmr.RDeleteService(stub)["hService"])
        self._log.service_request(
            name="svcctl DeleteService", detail=f"{record.name}, {record.binary_path}"
        )
        self._services.delete(record.name)
        response = scmr.RDeleteServiceResponse()
        response["ErrorCode"] = 0
        return response

    def _close(self, stub: bytes) -> scmr.RCloseServiceHandleResponse:
        handle = scmr.RCloseServiceHandle(stub)["hSCObject"]
        if self._handles.pop(bytes(handle), None) is None:
            raise ServiceError(ERROR_INVALID_HANDLE)
        response = scmr.RCloseServiceHandleResponse()
        response["hSCObject"] = NO_HANDLE
        response["ErrorCode"] = 0
        return response

    def _enumerate(self, stub: bytes) -> scmr.REnumServicesStatusWResponse:
        request = scmr.REnumServicesStatusW(stub)
        self._lookup(request["hSCManager"], "manager")
        wanted = [r for r in self._services.listing() if _in_state(r, request["dwServiceState"])]
        buffer = _status_buffer(wanted)
        size = min(request["cbBufSize"], MAX_ENUM_BUFFER_BYTES)
        response = scmr.REnumServicesStatusWResponse()
        response["pcbBytesNeeded"] = 0
        response["lpResumeIndex"] = NULL
        response["lpServicesReturned"] = len(wanted)
        response["lpBuffer"] = buffer
        response["ErrorCode"] = 0
        if len(buffer) > size:
            response["lpBuffer"] = bytes(size)
            response["pcbBytesNeeded"] = len(buffer)
            response["lpServicesReturned"] = 0
            response["ErrorCode"] = ERROR_MORE_DATA
        return response

    def _failure(self, opnum: int, code: int):
        """The response of `opnum` carrying only the Win32 error `code`."""
        failures = {
            _OPNUM_CLOSE: scmr.RCloseServiceHandleResponse,
            _OPNUM_CONTROL: scmr.RControlServiceResponse,
            _OPNUM_DELETE: scmr.RDeleteServiceResponse,
            _OPNUM_QUERY_STATUS: scmr.RQueryServiceStatusResponse,
            _OPNUM_CREATE: scmr.RCreateServiceWResponse,
            _OPNUM_OPEN_SERVICE: scmr.ROpenServiceWResponse,
            _OPNUM_OPEN_SCM: scmr.ROpenSCManagerWResponse,
            _OPNUM_START: scmr.RStartServiceWResponse,
            _OPNUM_ENUM: scmr.REnumServicesStatusWResponse,
        }
        response = failures[opnum]()
        for name, _kind in response.structure:
            if name not in ("ErrorCode", "lpServiceStatus"):
                response[name] = _empty(name)
        response["ErrorCode"] = code
        return response

    def _new_handle(self, kind: str, name: str) -> bytes:
        if len(self._handles) >= MAX_HANDLES:
            raise ServiceError(ERROR_INVALID_HANDLE)
        handle = new_call_handle()
        self._handles[handle] = (kind, name)
        return handle

    def _lookup(self, handle: object, kind: str) -> str:
        entry = self._handles.get(bytes(handle) if isinstance(handle, bytes) else b"")
        if entry is None or entry[0] != kind:
            raise ServiceError(ERROR_INVALID_HANDLE)
        return entry[1]

    def _service_of(self, handle: object) -> ServiceRecord:
        return self._services.get(self._lookup(handle, "service"))

    @staticmethod
    def _fill_status(status, record: ServiceRecord) -> None:
        status["dwServiceType"] = record.service_type
        status["dwCurrentState"] = record.state
        status["dwControlsAccepted"] = SERVICE_ACCEPT_STOP if record.state == SERVICE_RUNNING else 0
        status["dwWin32ExitCode"] = 0
        status["dwServiceSpecificExitCode"] = 0
        status["dwCheckPoint"] = 0
        status["dwWaitHint"] = 0


def _empty(field: str):
    """A neutral value for a response field of a call that failed."""
    if field in _HANDLE_FIELDS:
        return NO_HANDLE
    if field in _POINTER_FIELDS:
        return NULL
    if field == "lpBuffer":
        return b""
    return 0


def _in_state(record: ServiceRecord, wanted: int) -> bool:
    running = record.state == SERVICE_RUNNING
    return bool(
        (wanted & SERVICE_STATE_ACTIVE and running)
        or (wanted & SERVICE_STATE_INACTIVE and not running)
    )


def _status_buffer(records: list[ServiceRecord]) -> bytes:
    """ENUM_SERVICE_STATUSW entries followed by their strings; offsets count from the buffer."""
    strings = b""
    entries = b""
    base = len(records) * ENTRY_BYTES
    for record in records:
        name = (record.name + "\x00").encode("utf-16le")
        display = (record.display_name + "\x00").encode("utf-16le")
        name_at = base + len(strings)
        display_at = name_at + len(name)
        strings += name + display
        controls = SERVICE_ACCEPT_STOP if record.state == SERVICE_RUNNING else 0
        status = _pack_status(record.service_type, record.state, controls)
        entries += _pack_offsets(name_at, display_at) + status
    return entries + strings


def _pack_offsets(name_at: int, display_at: int) -> bytes:
    return name_at.to_bytes(4, "little") + display_at.to_bytes(4, "little")


def _pack_status(service_type: int, state: int, controls: int) -> bytes:
    fields = (service_type, state, controls, 0, 0, 0, 0)
    return b"".join(value.to_bytes(4, "little") for value in fields)
