"""Named pipes on IPC$: which ones exist and what answers on them.

A pipe wraps one `RpcServer`. `write` hands it a PDU and queues the answer; `read` takes the
next queued PDU, in pieces if the client's buffer is smaller. Only `svcctl` and `srvsvc` exist.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from impacket import nt_errors

from lan_session import HostSpec
from lan_sim.clock import Clock
from lan_sim.services.smb_rpc import RpcFormatError, RpcInterface, RpcServer
from lan_sim.services.smb_services import ServiceTable
from lan_sim.services.smb_srvsvc import ShareEntry, SrvsvcInterface
from lan_sim.services.smb_svcctl import SvcctlInterface
from lan_sim.services.smb_types import Pipe, RefusalError
from lan_sim.services.smb_wire import SmbFormatError
from lan_sim.session_log import ConnectionLog

MAX_QUEUED_BYTES = 256 * 1024
KNOWN_BUT_UNSUPPORTED = ("wkssvc", "lsarpc")


@dataclass
class PipeContext:
    host: HostSpec
    clock: Clock
    log: ConnectionLog
    services: ServiceTable
    shares: Callable[[], list[ShareEntry]]


class RpcPipe:
    def __init__(self, server: RpcServer) -> None:
        self._server = server
        self._queue: deque[bytes] = deque()

    def write(self, data: bytes) -> None:
        try:
            self._queue.extend(self._server.process(data))
        except RpcFormatError as error:
            raise SmbFormatError(f"a malformed RPC PDU: {error}") from error
        if sum(len(pdu) for pdu in self._queue) > MAX_QUEUED_BYTES:
            raise SmbFormatError("a client that writes to a pipe and never reads")

    def read(self, size: int) -> tuple[bytes, bool]:
        if not self._queue:
            return b"", False
        pdu = self._queue.popleft()
        if len(pdu) <= size:
            return pdu, False
        self._queue.appendleft(pdu[size:])
        return pdu[:size], True

    def transceive(self, data: bytes, size: int) -> tuple[bytes, bool]:
        self.write(data)
        return self.read(size)


def open_pipe(name: str, context: PipeContext) -> Pipe:
    interface = _interface_named(name, context)
    return RpcPipe(RpcServer(interface, context.host, context.clock, context.log))


def _interface_named(name: str, context: PipeContext) -> RpcInterface:
    if name == "svcctl":
        return SvcctlInterface(context.services, context.log)
    if name == "srvsvc":
        return SrvsvcInterface(context.shares)
    if name in KNOWN_BUT_UNSUPPORTED:
        raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)
    raise RefusalError(nt_errors.STATUS_OBJECT_NAME_NOT_FOUND)
