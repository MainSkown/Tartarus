"""Connection-oriented DCERPC over a named pipe: bind, authenticate, request, response.

One `RpcServer` serves one interface on one pipe handle. PDUs go in whole (an SMB write or ioctl
carries one) and come out as a list of PDUs. A malformed PDU raises `RpcFormatError`; a failing
call becomes a fault PDU, so a client always gets an answer and nothing here can hang.

Only NTLM authentication at the connect level is served: it is checked against the host's
accounts like any other login. The packet-integrity and privacy levels (what `sc.exe` asks for)
need sealing with the session key and are refused with a bind_nak.
"""

import secrets
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from lan_session import HostSpec
from lan_sim import ntlm
from lan_sim.clock import Clock

PTYPE_REQUEST, PTYPE_RESPONSE, PTYPE_FAULT = 0, 2, 3
PTYPE_BIND, PTYPE_BIND_ACK, PTYPE_BIND_NAK = 11, 12, 13
PTYPE_ALTER_CONTEXT, PTYPE_ALTER_CONTEXT_RESP, PTYPE_AUTH3 = 14, 15, 16
PFC_FIRST_FRAG, PFC_LAST_FRAG, PFC_OBJECT_UUID = 0x01, 0x02, 0x80
LITTLE_ENDIAN_DREP = 0x10
RPC_VERSION = 5
HEADER_BYTES = 16
SEC_TRAILER_BYTES = 8
AUTH_NTLMSSP = 10
AUTH_LEVEL_NONE, AUTH_LEVEL_CONNECT = 1, 2
MAX_CONTEXTS = 16
MAX_TRANSFER_SYNTAXES = 8
MAX_STUB_BYTES = 64 * 1024
MIN_FRAGMENT_BYTES = 128
DEFAULT_FRAGMENT_BYTES = 4280
RESPONSE_OVERHEAD = HEADER_BYTES + 8

RESULT_ACCEPT, RESULT_PROVIDER_REJECT, RESULT_NEGOTIATE_ACK = 0, 2, 3
REASON_ABSTRACT_SYNTAX_NOT_SUPPORTED = 1
REASON_TRANSFER_SYNTAX_NOT_SUPPORTED = 2
NAK_REASON_NOT_SPECIFIED = 0
FAULT_ACCESS_DENIED = 0x00000005
FAULT_OP_RANGE_ERROR = 0x1C010002
FAULT_UNKNOWN_INTERFACE = 0x1C010003
FAULT_NDR = 0x000006F7
FAULT_PROTOCOL_ERROR = 0x1C01000B

NDR32 = UUID("8a885d04-1ceb-11c9-9fe8-08002b104860").bytes_le
NDR32_VERSION = 2
BIND_TIME_FEATURES = UUID("6cb71c2c-9812-4540-0300-000000000000").bytes_le

_COMMON = struct.Struct("<BBBB4sHHI")
_BIND = struct.Struct("<HHIBBH")
_CONTEXT = struct.Struct("<HBB")
_SYNTAX = struct.Struct("<16sHH")
_SEC_TRAILER = struct.Struct("<BBBBI")
_REQUEST = struct.Struct("<IHH")
_RESPONSE = struct.Struct("<IHBB")
_FAULT = struct.Struct("<IHBBI4x")


class RpcFormatError(Exception):
    """The bytes are not a DCERPC PDU this server accepts."""


class RpcFaultError(Exception):
    """A call that fails with a DCERPC fault status instead of a response."""

    def __init__(self, status: int) -> None:
        super().__init__(f"{status:#x}")
        self.status = status


class RpcInterface(Protocol):
    uuid: bytes
    major_version: int
    pipe_name: str

    def call(self, opnum: int, stub: bytes) -> bytes:
        """The response stub for `stub`; raises `RpcFaultError` for a fault."""
        ...


class _Log(Protocol):
    def service_request(self, *, name: str, detail: str) -> bool: ...

    def login_attempt(
        self, *, user: str, domain: str, mechanism: str, secret: str, success: bool
    ) -> bool: ...


@dataclass
class _Pdu:
    ptype: int
    flags: int
    call_id: int
    body: bytes
    auth: tuple[int, int, int, bytes] | None


@dataclass
class _Syntax:
    uuid: bytes
    version: int


@dataclass
class _Context:
    context_id: int
    abstract: _Syntax
    transfers: list[_Syntax]


@dataclass
class _AuthState:
    level: int
    challenge: bytes | None = None
    authenticated: bool = False
    denied: bool = False


@dataclass
class _Fragments:
    context_id: int = 0
    opnum: int = 0
    stub: bytearray = field(default_factory=bytearray)


class RpcServer:
    def __init__(self, interface: RpcInterface, host: HostSpec, clock: Clock, log: _Log) -> None:
        self._interface = interface
        self._host = host
        self._clock = clock
        self._log = log
        self._bound: set[int] = set()
        self._max_fragment = DEFAULT_FRAGMENT_BYTES
        self._auth: _AuthState | None = None
        self._pending = _Fragments()
        self._assembling = False

    def process(self, data: bytes) -> list[bytes]:
        pdu = _parse_pdu(data)
        handlers: dict[int, Callable[[_Pdu], list[bytes]]] = {
            PTYPE_BIND: self._bind,
            PTYPE_ALTER_CONTEXT: self._alter_context,
            PTYPE_AUTH3: self._auth3,
            PTYPE_REQUEST: self._request,
        }
        handler = handlers.get(pdu.ptype)
        if handler is None:
            return [_fault(pdu.call_id, 0, FAULT_PROTOCOL_ERROR)]
        return handler(pdu)

    # --- bind and authentication ------------------------------------------------------------------

    def _bind(self, pdu: _Pdu) -> list[bytes]:
        contexts, max_recv = _parse_bind(pdu.body)
        refusal = self._start_authentication(pdu)
        if refusal is not None:
            return [refusal]
        self._max_fragment = max(MIN_FRAGMENT_BYTES, min(max_recv, DEFAULT_FRAGMENT_BYTES))
        trailer = self._challenge_trailer(pdu)
        return [self._bind_ack(PTYPE_BIND_ACK, pdu, contexts, trailer, address=True)]

    def _alter_context(self, pdu: _Pdu) -> list[bytes]:
        contexts, _ = _parse_bind(pdu.body)
        if pdu.auth is not None:
            self._authenticate(pdu.auth)
        return [self._bind_ack(PTYPE_ALTER_CONTEXT_RESP, pdu, contexts, b"", address=False)]

    def _auth3(self, pdu: _Pdu) -> list[bytes]:
        if pdu.auth is not None:
            self._authenticate(pdu.auth)
        return []

    def _start_authentication(self, pdu: _Pdu) -> bytes | None:
        """A bind_nak if the bind asks for authentication this server cannot give, else None."""
        if pdu.auth is None:
            self._auth = None
            return None
        auth_type, level, _, _ = pdu.auth
        if auth_type != AUTH_NTLMSSP or level not in (AUTH_LEVEL_NONE, AUTH_LEVEL_CONNECT):
            self._log.service_request(
                name=f"{self._interface.pipe_name} bind",
                detail=f"authenticated bind refused: type {auth_type}, level {level}",
            )
            return _pdu(
                PTYPE_BIND_NAK,
                PFC_FIRST_FRAG | PFC_LAST_FRAG,
                pdu.call_id,
                struct.pack("<HBBB", NAK_REASON_NOT_SPECIFIED, 1, 5, 0),
            )
        self._auth = _AuthState(level)
        return None

    def _challenge_trailer(self, pdu: _Pdu) -> bytes:
        if pdu.auth is None or self._auth is None:
            return b""
        auth_type, level, context_id, blob = pdu.auth
        try:
            if ntlm.ntlm_message_type(blob) != ntlm.NEGOTIATE_MESSAGE:
                raise RpcFormatError("authentication did not start with a NEGOTIATE_MESSAGE")
        except ntlm.NtlmFormatError as error:
            raise RpcFormatError(str(error)) from error
        self._auth.challenge = ntlm.new_challenge()
        message = ntlm.challenge_message(self._host, self._auth.challenge, self._clock)
        return _sec_trailer(auth_type, level, context_id) + message

    def _authenticate(self, auth: tuple[int, int, int, bytes]) -> None:
        state = self._auth
        if state is None or state.challenge is None:
            return
        try:
            attempt = ntlm.parse_authenticate(auth[3], state.challenge)
        except ntlm.NtlmFormatError as error:
            raise RpcFormatError(str(error)) from error
        verdict = ntlm.verify(attempt, self._host)
        self._log.login_attempt(
            user=attempt.user,
            domain=attempt.domain,
            mechanism="ntlm",
            secret=attempt.hashcat,
            success=verdict.verified,
        )
        state.authenticated = verdict.verified
        state.denied = not verdict.verified
        state.challenge = None

    def _bind_ack(
        self, ptype: int, pdu: _Pdu, contexts: list[_Context], trailer: bytes, *, address: bool
    ) -> bytes:
        secondary = f"\\PIPE\\{self._interface.pipe_name}".encode() + b"\x00" if address else b""
        body = struct.pack("<HHIH", self._max_fragment, self._max_fragment, 0x1234, len(secondary))
        body += secondary
        body += bytes(-(HEADER_BYTES + len(body)) % 4)
        body += struct.pack("<BBH", len(contexts), 0, 0)
        for context in contexts:
            body += self._context_result(context)
        auth_len = len(trailer) - SEC_TRAILER_BYTES if trailer else 0
        return _pdu(ptype, PFC_FIRST_FRAG | PFC_LAST_FRAG, pdu.call_id, body + trailer, auth_len)

    def _context_result(self, context: _Context) -> bytes:
        no_syntax = bytes(16) + struct.pack("<I", 0)
        ndr = NDR32 + struct.pack("<I", NDR32_VERSION)
        if context.abstract.uuid == BIND_TIME_FEATURES:
            return struct.pack("<HH", RESULT_NEGOTIATE_ACK, 0) + no_syntax
        if (
            context.abstract.uuid != self._interface.uuid
            or context.abstract.version != self._interface.major_version
        ):
            return (
                struct.pack("<HH", RESULT_PROVIDER_REJECT, REASON_ABSTRACT_SYNTAX_NOT_SUPPORTED)
                + no_syntax
            )
        if not any(t.uuid == NDR32 and t.version == NDR32_VERSION for t in context.transfers):
            return (
                struct.pack("<HH", RESULT_PROVIDER_REJECT, REASON_TRANSFER_SYNTAX_NOT_SUPPORTED)
                + no_syntax
            )
        self._bound.add(context.context_id)
        return struct.pack("<HH", RESULT_ACCEPT, 0) + ndr

    # --- requests ---------------------------------------------------------------------------------

    def _request(self, pdu: _Pdu) -> list[bytes]:
        if len(pdu.body) < _REQUEST.size:
            raise RpcFormatError("a request header is cut short")
        _, context_id, opnum = _REQUEST.unpack_from(pdu.body)
        offset = _REQUEST.size + (16 if pdu.flags & PFC_OBJECT_UUID else 0)
        if len(pdu.body) < offset:
            raise RpcFormatError("a request object uuid is cut short")
        stub = pdu.body[offset:]
        if pdu.flags & PFC_FIRST_FRAG:
            self._pending = _Fragments(context_id, opnum)
        self._pending.stub += stub
        if len(self._pending.stub) > MAX_STUB_BYTES:
            raise RpcFormatError("a request stub is too large")
        if not pdu.flags & PFC_LAST_FRAG:
            return []
        assembled, self._pending = self._pending, _Fragments()
        return self._answer(pdu.call_id, assembled)

    def _answer(self, call_id: int, request: _Fragments) -> list[bytes]:
        denied = self._auth is not None and not self._auth.authenticated
        if denied:
            return [_fault(call_id, request.context_id, FAULT_ACCESS_DENIED)]
        if request.context_id not in self._bound:
            return [_fault(call_id, request.context_id, FAULT_UNKNOWN_INTERFACE)]
        try:
            response = self._interface.call(request.opnum, bytes(request.stub))
        except RpcFaultError as fault:
            return [_fault(call_id, request.context_id, fault.status)]
        except Exception:  # noqa: BLE001 - a parser of hostile NDR must never take the pipe down
            return [_fault(call_id, request.context_id, FAULT_NDR)]
        return self._response_fragments(call_id, request.context_id, response)

    def _response_fragments(self, call_id: int, context_id: int, stub: bytes) -> list[bytes]:
        size = self._max_fragment - RESPONSE_OVERHEAD
        pieces = [stub[start : start + size] for start in range(0, len(stub), size)] or [b""]
        fragments = []
        for index, piece in enumerate(pieces):
            flags = (PFC_FIRST_FRAG if index == 0 else 0) | (
                PFC_LAST_FRAG if index == len(pieces) - 1 else 0
            )
            body = _RESPONSE.pack(len(stub), context_id, 0, 0) + piece
            fragments.append(_pdu(PTYPE_RESPONSE, flags, call_id, body))
        return fragments


def new_call_handle() -> bytes:
    """A 20-byte NDR context handle: zero attributes and a random uuid."""
    return bytes(4) + secrets.token_bytes(16)


def _pdu(ptype: int, flags: int, call_id: int, body: bytes, auth_len: int = 0) -> bytes:
    return (
        _COMMON.pack(
            5,
            0,
            ptype,
            flags,
            bytes([LITTLE_ENDIAN_DREP, 0, 0, 0]),
            HEADER_BYTES + len(body),
            auth_len,
            call_id,
        )
        + body
    )


def _fault(call_id: int, context_id: int, status: int) -> bytes:
    body = _FAULT.pack(0, context_id, 0, 0, status)
    return _pdu(PTYPE_FAULT, PFC_FIRST_FRAG | PFC_LAST_FRAG, call_id, body)


def _sec_trailer(auth_type: int, level: int, context_id: int) -> bytes:
    return _SEC_TRAILER.pack(auth_type, level, 0, 0, context_id)


def _parse_pdu(data: bytes) -> _Pdu:
    if len(data) < HEADER_BYTES:
        raise RpcFormatError("a PDU header is cut short")
    version, minor, ptype, flags, drep, frag_len, auth_len, call_id = _COMMON.unpack_from(data)
    if version != RPC_VERSION or minor not in (0, 1) or not drep[0] & LITTLE_ENDIAN_DREP:
        raise RpcFormatError("not a little-endian DCERPC 5 PDU")
    if frag_len != len(data):
        raise RpcFormatError("the fragment length is not the PDU length")
    end = frag_len
    auth = None
    if auth_len:
        trailer_at = frag_len - auth_len - SEC_TRAILER_BYTES
        if trailer_at < HEADER_BYTES:
            raise RpcFormatError("the authentication trailer does not fit")
        auth_type, level, pad, _, context_id = _SEC_TRAILER.unpack_from(data, trailer_at)
        auth = (auth_type, level, context_id, data[frag_len - auth_len :])
        end = max(HEADER_BYTES, trailer_at - pad)
    return _Pdu(ptype, flags, call_id, data[HEADER_BYTES:end], auth)


def _parse_bind(body: bytes) -> tuple[list[_Context], int]:
    if len(body) < _BIND.size:
        raise RpcFormatError("a bind header is cut short")
    _, max_recv, _, count, _, _ = _BIND.unpack_from(body)
    if count > MAX_CONTEXTS:
        raise RpcFormatError("too many presentation contexts")
    position = _BIND.size
    contexts = []
    for _ in range(count):
        context_id, transfer_count, _ = _unpack(_CONTEXT, body, position)
        position += _CONTEXT.size
        if transfer_count > MAX_TRANSFER_SYNTAXES:
            raise RpcFormatError("too many transfer syntaxes")
        abstract, position = _syntax(body, position)
        transfers = []
        for _ in range(transfer_count):
            transfer, position = _syntax(body, position)
            transfers.append(transfer)
        contexts.append(_Context(context_id, abstract, transfers))
    return contexts, max_recv


def _unpack(layout: struct.Struct, data: bytes, position: int) -> tuple:
    if position + layout.size > len(data):
        raise RpcFormatError("a bind is cut short")
    return layout.unpack_from(data, position)


def _syntax(body: bytes, position: int) -> tuple[_Syntax, int]:
    uuid, major, _minor = _unpack(_SYNTAX, body, position)
    return _Syntax(uuid, major), position + _SYNTAX.size
