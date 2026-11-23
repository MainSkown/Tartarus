"""SMB2/3 for the fake LAN's file servers: sessions that really sign, shares in memory, pipes.

Authentication is NTLM through SPNEGO against the host's own accounts only: a login that is not
one of them fails with STATUS_LOGON_FAILURE and its NetNTLMv2 line is logged. A verified login
gets a session whose messages are signed with a key derived from the password, because Windows'
client rejects a server that cannot sign. Nothing a client sends reaches the host: files live in
`smb_store`, the service control manager in `smb_svcctl`, and nothing is ever started.
"""

import hashlib
import secrets
import struct
from dataclasses import dataclass, field, replace

from impacket import nt_errors, spnego

from lan_sim import ntlm
from lan_sim.service import Connection
from lan_sim.services import smb_messages as messages
from lan_sim.services.smb_files import FileHandler, PipeOverflowError
from lan_sim.services.smb_pipes import PipeContext
from lan_sim.services.smb_rpc import RpcFormatError
from lan_sim.services.smb_signing import (
    DIALECT_2_0_2,
    DIALECT_2_1,
    DIALECT_3_0,
    DIALECT_3_0_2,
    DIALECT_3_1_1,
    PreauthHash,
    derive_signing_key,
    sign_message,
    signature_matches,
)
from lan_sim.services.smb_srvsvc import STYPE_DISK, STYPE_HIDDEN_DISK, STYPE_HIDDEN_IPC, ShareEntry
from lan_sim.services.smb_state import HostState, SmbStates
from lan_sim.services.smb_store import MIB, SESSION_BYTE_CAP, filetime
from lan_sim.services.smb_types import RefusalError, Reply, Request, Session, Tree
from lan_sim.services.smb_wire import (
    FLAG_RELATED,
    FLAG_RESPONSE,
    FLAG_SIGNED,
    HEADER_SIZE,
    SMB1_MAGIC,
    Header,
    SmbFormatError,
    frame_message,
    pack_message,
    parse_header,
    parse_smb1_negotiate,
    read_frame,
    smb1_negotiate_refusal,
    split_compound,
)

MAX_FRAME_BYTES = 128 * 1024
MAX_IO_SIZE = 65536
MAX_CREDITS = 64
MAX_SESSIONS_PER_CONNECTION = 8
MAX_TREES_PER_SESSION = 16
MAX_EXTRA_SHARES = 16
# What a verified login may send on top of the framework's 64 KiB: the session's write cap plus
# the protocol around it. The framework has no hook to raise its per-connection budget, so the
# service replaces the connection's limits once, after a login that proved a password.
AUTHENTICATED_READ_BUDGET = SESSION_BYTE_CAP + 16 * MIB

SUPPORTED_DIALECTS = (DIALECT_3_1_1, DIALECT_3_0_2, DIALECT_3_0, DIALECT_2_1, DIALECT_2_0_2)
WILDCARD_DIALECT = 0x02FF
STATUS_INSUFFICIENT_RESOURCES = 0xC000009A
NT_SEVERITY_SHIFT = 30
NT_SEVERITY_ERROR = 3

FSCTL_VALIDATE_NEGOTIATE_INFO = 0x00140204
FSCTL_PIPE_TRANSCEIVE = 0x0011C017
FSCTL_DFS_GET_REFERRALS = 0x00060194
SIGNING_ENABLED_AND_REQUIRED = 3

FULL_ACCESS = 0x001F01FF
IPC_ACCESS = 0x0012019F
_FILE_ID_OFFSETS = {
    messages.CLOSE: 8,
    messages.FLUSH: 8,
    messages.LOCK: 8,
    messages.IOCTL: 8,
    messages.QUERY_DIRECTORY: 8,
    messages.CHANGE_NOTIFY: 8,
    messages.READ: 16,
    messages.WRITE: 16,
    messages.SET_INFO: 16,
    messages.QUERY_INFO: 24,
}
_NO_TREE_NEEDED = (messages.LOGOFF, messages.TREE_CONNECT, messages.ECHO)
_ADMIN_SHARES = ("ADMIN$", "C$")
IPC_SHARE = "IPC$"
_REMARKS = {"ADMIN$": "Remote Admin", "C$": "Default share", IPC_SHARE: "Remote IPC"}


@dataclass
class _Chain:
    """What a related compound request inherits from the one before it."""

    session_id: int = 0
    tree_id: int = 0
    file_id: bytes | None = None
    failed: int | None = None


@dataclass
class _Outgoing:
    request: Header
    reply: Reply
    session: Session | None
    session_id: int
    tree_id: int


@dataclass
class _Connection:
    connection: Connection
    state: HostState
    dialect: int | None = None
    preauth: PreauthHash = field(default_factory=PreauthHash)
    sessions: dict[int, Session] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pipes = PipeContext(
            host=self.connection.host,
            clock=self.connection.clock,
            log=self.connection.log,
            services=self.state.services,
            shares=self._share_entries,
        )
        self.files = FileHandler(self.connection.log, self._now, pipes)
        self.guid = hashlib.md5(self.connection.host.fqdn.encode(), usedforsecurity=False).digest()
        self._handlers = {
            messages.NEGOTIATE: self._negotiate,
            messages.SESSION_SETUP: self._session_setup,
            messages.LOGOFF: self._logoff,
            messages.TREE_CONNECT: self._tree_connect,
            messages.TREE_DISCONNECT: self._tree_disconnect,
            messages.CREATE: self.files.create,
            messages.CLOSE: self.files.close,
            messages.FLUSH: self.files.flush,
            messages.READ: self.files.read,
            messages.WRITE: self.files.write,
            messages.LOCK: self.files.lock,
            messages.IOCTL: self._ioctl,
            messages.ECHO: lambda _request: Reply(body=messages.empty_response()),
            messages.QUERY_DIRECTORY: self.files.query_directory,
            messages.QUERY_INFO: self.files.query_info,
            messages.SET_INFO: self.files.set_info,
        }

    async def run(self) -> None:
        try:
            first = True
            while True:
                frame = await read_frame(self.connection, MAX_FRAME_BYTES)
                if first and frame.startswith(SMB1_MAGIC):
                    if not await self._answer_smb1(frame):
                        return
                else:
                    await self._answer_smb2(frame)
                first = False
        finally:
            self.files.release_all()

    def _now(self) -> int:
        return filetime(self.connection.clock.now())

    # --- SMB1 negotiate ---------------------------------------------------------------------------

    async def _answer_smb1(self, frame: bytes) -> bool:
        offered = parse_smb1_negotiate(frame)
        if offered.offers_smb2_wildcard:
            body = self._negotiate_body(WILDCARD_DIALECT, salt=None)
        elif offered.offers_smb2_002:
            self.dialect = DIALECT_2_0_2
            body = self._negotiate_body(DIALECT_2_0_2, salt=None)
        else:
            await self.connection.write(frame_message(smb1_negotiate_refusal()))
            return False
        header = Header(command=messages.NEGOTIATE, flags=FLAG_RESPONSE, credit_request=1)
        await self.connection.write(frame_message(pack_message(header, body)))
        return True

    # --- SMB2 -------------------------------------------------------------------------------------

    async def _answer_smb2(self, frame: bytes) -> None:
        chain = _Chain()
        outgoing = [
            item for raw in split_compound(frame) if (item := self._process(raw, chain)) is not None
        ]
        if outgoing:
            await self.connection.write(frame_message(self._assemble(outgoing)))

    def _process(self, raw: bytes, chain: _Chain) -> _Outgoing | None:
        header = parse_header(raw)
        if header.command == messages.CANCEL:
            return None
        request = Request(header, raw[HEADER_SIZE:], raw)
        related = bool(header.flags & FLAG_RELATED) and chain.session_id != 0
        try:
            reply = self._route(request, chain, related)
        except RefusalError as refusal:
            reply = Reply(refusal.status)
        if reply.status >> NT_SEVERITY_SHIFT == NT_SEVERITY_ERROR:
            chain.failed = reply.status
        session_id = reply.session_id or (chain.session_id if related else header.session_id)
        tree_id = reply.tree_id or (chain.tree_id if related else header.tree_id)
        chain.session_id, chain.tree_id = session_id, tree_id
        chain.file_id = reply.file_id or chain.file_id
        return _Outgoing(header, reply, request.session, session_id, tree_id)

    def _route(self, request: Request, chain: _Chain, related: bool) -> Reply:
        command = request.header.command
        if self.dialect is None and command != messages.NEGOTIATE:
            raise SmbFormatError("a request before the negotiate")
        handler = self._handlers.get(command)
        if handler is None:
            raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)
        if command in (messages.NEGOTIATE, messages.SESSION_SETUP):
            return handler(request)
        if related and chain.failed is not None:
            raise RefusalError(chain.failed)
        self._authorise(request, chain, related)
        if related and chain.file_id is not None:
            request.body = _with_file_id(command, request.body, chain.file_id)
        return handler(request)

    def _authorise(self, request: Request, chain: _Chain, related: bool) -> None:
        header = request.header
        session = self.sessions.get(chain.session_id if related else header.session_id)
        if session is None or not session.active:
            raise RefusalError(nt_errors.STATUS_USER_SESSION_DELETED)
        request.session = session
        assert session.signing_key is not None  # noqa: S101 - `active` means it has one
        if not self._signed_correctly(request, session.signing_key):
            raise RefusalError(nt_errors.STATUS_ACCESS_DENIED)
        if header.command in _NO_TREE_NEEDED:
            return
        tree_id = chain.tree_id if related else header.tree_id
        tree = session.trees.get(tree_id)
        if tree is None:
            raise RefusalError(nt_errors.STATUS_NETWORK_NAME_DELETED)
        request.tree = tree

    def _signed_correctly(self, request: Request, key: bytes) -> bool:
        assert self.dialect is not None  # noqa: S101 - set by the negotiate that came first
        if not request.header.flags & FLAG_SIGNED:
            return False
        return signature_matches(self.dialect, key, request.raw)

    def _assemble(self, outgoing: list[_Outgoing]) -> bytes:
        parts: list[bytes] = []
        for index, item in enumerate(outgoing):
            body = item.reply.body or messages.error_response()
            if index < len(outgoing) - 1:
                body += bytes(-(HEADER_SIZE + len(body)) % 8)
            parts.append(self._response_message(item, body, last=index == len(outgoing) - 1))
        return b"".join(parts)

    def _response_message(self, item: _Outgoing, body: bytes, *, last: bool) -> bytes:
        request = item.request
        header = Header(
            command=request.command,
            status=item.reply.status,
            flags=FLAG_RESPONSE | (request.flags & FLAG_RELATED),
            next_command=0 if last else HEADER_SIZE + len(body),
            message_id=request.message_id,
            tree_id=item.tree_id,
            session_id=item.session_id,
            credit_charge=request.credit_charge,
            credit_request=max(1, min(request.credit_request, MAX_CREDITS)),
        )
        message = pack_message(header, body)
        key = item.session.signing_key if item.session else None
        if key is not None and self.dialect is not None:
            message = sign_message(self.dialect, key, message)
        if item.reply.transcript is not None:
            item.reply.transcript.update(message)
        return message

    # --- negotiate and authentication -------------------------------------------------------------

    def _negotiate(self, request: Request) -> Reply:
        if self.dialect is not None:
            raise SmbFormatError("a second negotiate")
        parsed = messages.parse_negotiate(request.body)
        dialect = max((d for d in parsed.dialects if d in SUPPORTED_DIALECTS), default=None)
        if dialect is None:
            raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)
        if dialect == DIALECT_3_1_1 and not parsed.offers_sha512:
            raise RefusalError(nt_errors.STATUS_INVALID_PARAMETER)
        self.dialect = dialect
        if dialect != DIALECT_3_1_1:
            return Reply(body=self._negotiate_body(dialect, salt=None))
        self.preauth.update(request.raw)
        body = self._negotiate_body(dialect, salt=secrets.token_bytes(messages.PREAUTH_SALT_BYTES))
        return Reply(body=body, transcript=self.preauth)

    def _negotiate_body(self, dialect: int, *, salt: bytes | None) -> bytes:
        return messages.negotiate_response(
            dialect=dialect,
            guid=self.guid,
            now=self._now(),
            max_size=MAX_IO_SIZE,
            security=_initial_security_token(),
            salt=salt,
        )

    def _session_setup(self, request: Request) -> Reply:
        blob = ntlm.unwrap_ntlmssp(messages.parse_session_setup(request.body))
        if blob is None:
            raise RefusalError(nt_errors.STATUS_LOGON_FAILURE)
        try:
            kind = ntlm.ntlm_message_type(blob)
            if kind == ntlm.NEGOTIATE_MESSAGE:
                return self._challenge(request)
            if kind == ntlm.AUTHENTICATE_MESSAGE:
                return self._authenticate(request, blob)
        except ntlm.NtlmFormatError as error:
            raise SmbFormatError(str(error)) from error
        raise SmbFormatError("an unexpected NTLM message")

    def _challenge(self, request: Request) -> Reply:
        if request.header.session_id != 0:
            raise RefusalError(nt_errors.STATUS_USER_SESSION_DELETED)
        if len(self.sessions) >= MAX_SESSIONS_PER_CONNECTION:
            raise RefusalError(STATUS_INSUFFICIENT_RESOURCES)
        session = Session(self._new_session_id(), ntlm.new_challenge(), self.preauth.copy())
        self.sessions[session.session_id] = session
        request.session = session
        if self.dialect == DIALECT_3_1_1:
            session.preauth.update(request.raw)
        challenge = ntlm.challenge_message(
            self.connection.host, session.challenge, self.connection.clock
        )
        return Reply(
            nt_errors.STATUS_MORE_PROCESSING_REQUIRED,
            messages.session_setup_response(ntlm.spnego_challenge(challenge)),
            session_id=session.session_id,
            transcript=session.preauth if self.dialect == DIALECT_3_1_1 else None,
        )

    def _authenticate(self, request: Request, blob: bytes) -> Reply:
        session = self.sessions.get(request.header.session_id)
        if session is None or session.active:
            raise RefusalError(nt_errors.STATUS_USER_SESSION_DELETED)
        request.session = session
        if self.dialect == DIALECT_3_1_1:
            session.preauth.update(request.raw)
        attempt = ntlm.parse_authenticate(blob, session.challenge)
        verdict = ntlm.verify(attempt, self.connection.host)
        self.connection.log.login_attempt(
            user=attempt.user,
            domain=attempt.domain,
            mechanism="ntlm",
            secret=attempt.hashcat,
            success=verdict.verified,
        )
        if not verdict.verified or verdict.session_base_key is None:
            del self.sessions[session.session_id]
            raise RefusalError(nt_errors.STATUS_LOGON_FAILURE)
        self._activate(session, attempt, verdict.session_base_key)
        return Reply(
            body=messages.session_setup_response(ntlm.spnego_accept()),
            session_id=session.session_id,
        )

    def _activate(self, session: Session, attempt: ntlm.NtlmAttempt, base_key: bytes) -> None:
        assert self.dialect is not None  # noqa: S101 - a session setup follows the negotiate
        exported = ntlm.exported_session_key(attempt, base_key)
        session.user = attempt.user
        session.signing_key = derive_signing_key(self.dialect, exported, session.preauth.value)
        limits = self.connection.limits
        if limits.max_bytes_read_per_connection < AUTHENTICATED_READ_BUDGET:
            self.connection.limits = replace(
                limits, max_bytes_read_per_connection=AUTHENTICATED_READ_BUDGET
            )

    def _new_session_id(self) -> int:
        while True:
            candidate = secrets.randbits(64)
            if candidate and candidate not in self.sessions:
                return candidate

    # --- sessions and trees -----------------------------------------------------------------------

    def _logoff(self, request: Request) -> Reply:
        session = request.session
        assert session is not None  # noqa: S101 - authorised before the handler runs
        self.files.release_matching(session.session_id)
        del self.sessions[session.session_id]
        return Reply(body=messages.empty_response())

    def _tree_connect(self, request: Request) -> Reply:
        session = request.session
        assert session is not None  # noqa: S101 - authorised before the handler runs
        unc = messages.parse_tree_connect(request.body)
        name = self._share_named(unc)
        if name is None or len(session.trees) >= MAX_TREES_PER_SESSION:
            self.connection.log.share_access(
                share=unc.rpartition("\\")[2], path="", operation="tree-connect-refused"
            )
            raise RefusalError(nt_errors.STATUS_BAD_NETWORK_NAME)
        is_pipe = name.upper() == IPC_SHARE
        tree = Tree(
            session.next_tree_id, name, None if is_pipe else self.state.share(name, self._now())
        )
        session.next_tree_id += 1
        session.trees[tree.tree_id] = tree
        self.connection.log.share_access(share=name, path="", operation="tree-connect")
        share_type = messages.SHARE_TYPE_PIPE if is_pipe else messages.SHARE_TYPE_DISK
        access = IPC_ACCESS if is_pipe else FULL_ACCESS
        return Reply(body=messages.tree_connect_response(share_type, access), tree_id=tree.tree_id)

    def _share_entries(self) -> list[ShareEntry]:
        hidden = [ShareEntry(name, STYPE_HIDDEN_DISK, _REMARKS[name]) for name in _ADMIN_SHARES]
        listed = [ShareEntry(name, STYPE_DISK, "") for name in _extra_shares(self.connection)]
        return [*hidden, ShareEntry(IPC_SHARE, STYPE_HIDDEN_IPC, _REMARKS[IPC_SHARE]), *listed]

    def _share_named(self, unc: str) -> str | None:
        """The canonical share name for a `\\\\server\\share` path, or None if there is none."""
        pieces = unc.split("\\")
        if len(pieces) != 4 or pieces[:2] != ["", ""] or not pieces[2]:  # noqa: PLR2004
            return None
        wanted = pieces[3].upper()
        known = (IPC_SHARE, *_ADMIN_SHARES, *_extra_shares(self.connection))
        return next((name for name in known if name.upper() == wanted), None)

    def _tree_disconnect(self, request: Request) -> Reply:
        session, tree = request.session, request.tree
        assert session is not None  # noqa: S101 - authorised before the handler runs
        assert tree is not None  # noqa: S101
        self.files.release_matching(session.session_id, tree.tree_id)
        del session.trees[tree.tree_id]
        return Reply(body=messages.empty_response())

    # --- ioctl ------------------------------------------------------------------------------------

    def _ioctl(self, request: Request) -> Reply:
        parsed = messages.parse_ioctl(request.body)
        if parsed.code == FSCTL_VALIDATE_NEGOTIATE_INFO:
            output = struct.pack(
                "<I16sHH", 0, self.guid, SIGNING_ENABLED_AND_REQUIRED, self.dialect or 0
            )
            return Reply(body=messages.ioctl_response(parsed.code, parsed.file_id, output))
        if parsed.code == FSCTL_PIPE_TRANSCEIVE:
            return self._transceive(request, parsed)
        if parsed.code == FSCTL_DFS_GET_REFERRALS:
            raise RefusalError(nt_errors.STATUS_FS_DRIVER_REQUIRED)
        raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)

    def _transceive(self, request: Request, parsed: messages.IoctlRequest) -> Reply:
        try:
            output = self.files.transceive(request, parsed.data, parsed.max_output, parsed.file_id)
        except PipeOverflowError as partial:
            body = messages.ioctl_response(parsed.code, parsed.file_id, partial.output)
            return Reply(nt_errors.STATUS_BUFFER_OVERFLOW, body)
        return Reply(body=messages.ioctl_response(parsed.code, parsed.file_id, output))


def _initial_security_token() -> bytes:
    token = spnego.SPNEGO_NegTokenInit()
    token["MechTypes"] = [spnego.TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]]
    return bytes(token.getData())


def _extra_shares(connection: Connection) -> list[str]:
    listed = connection.service.options.get("shares", [])
    if not isinstance(listed, list):
        return []
    return [name for name in listed[:MAX_EXTRA_SHARES] if isinstance(name, str) and name]


def _with_file_id(command: int, body: bytes, file_id: bytes) -> bytes:
    offset = _FILE_ID_OFFSETS.get(command)
    end = None if offset is None else offset + messages.FILE_ID_BYTES
    if offset is None or end is None or body[offset:end] != messages.ANY_FILE:
        return body
    return body[:offset] + file_id + body[end:]


class SmbService:
    kind = "smb"

    def __init__(self, states: SmbStates | None = None) -> None:
        self._states = states or SmbStates()

    async def serve(self, connection: Connection) -> None:
        """Speaks SMB2/3 on `connection`: negotiate, NTLM session setup, shares and pipes."""
        state = self._states.host(connection.session.key, connection.host.fqdn)
        try:
            await _Connection(connection, state).run()
        except (SmbFormatError, RpcFormatError, ntlm.NtlmFormatError) as error:
            connection.log.service_request(name="malformed-smb", detail=str(error))


SERVICE = SmbService()
