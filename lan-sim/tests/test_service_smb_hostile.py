"""What a hostile or broken client can and cannot do to the SMB service.

Every test has a time bound: a server that hangs is a failing server. The signed raw requests are
built with the key the impacket client derived, so they get past the signature check and reach the
handlers.
"""

import random
import socket
import struct
import time

import pytest
from impacket import nt_errors
from impacket.nmb import NetBIOSError
from test_service_smb_support import HOST_ADDRESS, SmbWorld

from lan_sim.services import smb as smb_module
from lan_sim.services import smb_messages as messages
from lan_sim.services.smb_signing import sign_message
from lan_sim.services.smb_wire import (
    FLAG_RELATED,
    HEADER_SIZE,
    Header,
    frame_message,
    pack_message,
    parse_header,
)

ANY_FILE = b"\xff" * 16


@pytest.fixture
def world(tmp_path):
    with SmbWorld(tmp_path) as running:
        yield running


def raw_socket(world) -> socket.socket:
    return socket.create_connection((HOST_ADDRESS, world.port), timeout=5)


def exchange(sock: socket.socket, payload: bytes) -> bytes:
    sock.sendall(payload)
    return sock.recv(65536)


class Signed:
    """Builds signed SMB2 requests on an authenticated impacket connection."""

    def __init__(self, smb) -> None:
        server = smb.getSMBServer()
        self.net = server._NetBIOSSession
        self.dialect = server._Connection["Dialect"]
        self.key = server._Session["SigningKey"] or server._Session["SessionKey"]
        self.session_id = server._Session["SessionID"]
        self.message_id = 1000
        self.tree_id = smb.connectTree("C$")

    def message(self, command, body, *, flags=0, tree_id=None, next_command=0) -> bytes:
        self.message_id += 1
        header = Header(
            command=command,
            flags=flags,
            message_id=self.message_id,
            tree_id=self.tree_id if tree_id is None else tree_id,
            session_id=self.session_id,
            credit_request=1,
            next_command=next_command,
        )
        return sign_message(self.dialect, self.key, pack_message(header, body))

    def send(self, payload: bytes) -> list[tuple[int, bytes]]:
        self.net.send_packet(payload)
        frame = self.net.recv_packet(5).get_trailer()
        return _split(frame)


def _split(frame: bytes) -> list[tuple[int, bytes]]:
    replies, offset = [], 0
    while True:
        header = parse_header(frame[offset : offset + HEADER_SIZE])
        end = offset + header.next_command if header.next_command else len(frame)
        replies.append((header.status, frame[offset + HEADER_SIZE : end]))
        if not header.next_command:
            return replies
        offset = end


def create_body(name: str, *, disposition=2, options=0) -> bytes:
    raw = name.encode("utf-16le")
    fixed = struct.pack(
        "<HBBIQQIIIIIHHII",
        57,
        0,
        0,
        2,
        0,
        0,
        0x12019F,
        0x80,
        7,
        disposition,
        options,
        HEADER_SIZE + 56,
        len(raw),
        0,
        0,
    )
    return fixed + raw


def close_body(file_id: bytes) -> bytes:
    return struct.pack("<HHI16s", 24, 0, 0, file_id)


def query_info_body(file_id: bytes) -> bytes:
    return struct.pack("<HBBIHHIII16s", 41, 1, 5, 1024, 0, 0, 0, 0, 0, file_id)


def test_a_compound_of_create_query_and_close_runs_as_one_related_chain(world):
    smb = world.client()
    signed = Signed(smb)
    create = _padded(signed, messages.CREATE, create_body("chain.txt"), 0)
    query = _padded(signed, messages.QUERY_INFO, query_info_body(ANY_FILE), FLAG_RELATED)
    close = signed.message(messages.CLOSE, close_body(ANY_FILE), flags=FLAG_RELATED)
    replies = signed.send(create + query + close)
    assert [status for status, _ in replies] == [0, 0, 0]
    assert any(r["path"] == "\\chain.txt" for r in world.records("share-access"))


def _padded(signed: Signed, command, body, flags) -> bytes:
    """A message that is followed by another one: padded to 8 bytes, NextCommand set, signed."""
    length = HEADER_SIZE + len(body)
    padded_body = body + bytes(-length % 8)
    return signed.message(
        command, padded_body, flags=flags, next_command=HEADER_SIZE + len(padded_body)
    )


def test_a_failed_create_fails_the_rest_of_its_chain_with_the_same_status(world):
    smb = world.client()
    signed = Signed(smb)
    create = _padded(signed, messages.CREATE, create_body("missing.txt", disposition=1), 0)
    close = signed.message(messages.CLOSE, close_body(ANY_FILE), flags=FLAG_RELATED)
    statuses = [status for status, _ in signed.send(create + close)]
    assert statuses == [nt_errors.STATUS_OBJECT_NAME_NOT_FOUND] * 2


def test_requests_without_a_session_are_refused_not_served(world):
    smb = world.client(login=False)
    server = smb.getSMBServer()
    net = server._NetBIOSSession
    header = Header(command=messages.TREE_CONNECT, message_id=2, credit_request=1)
    path = "\\\\fs01\\C$".encode("utf-16le")
    body = struct.pack("<HHHH", 9, 0, 72, len(path)) + path
    net.send_packet(pack_message(header, body))
    status, _ = _split(net.recv_packet(5).get_trailer())[0]
    assert status == nt_errors.STATUS_USER_SESSION_DELETED


def test_a_request_with_an_unknown_session_id_is_refused(world):
    smb = world.client()
    signed = Signed(smb)
    signed.session_id += 1
    [(status, _)] = signed.send(signed.message(messages.ECHO, struct.pack("<HH", 4, 0)))
    assert status == nt_errors.STATUS_USER_SESSION_DELETED


def test_an_unsigned_request_on_a_signing_session_is_refused(world):
    smb = world.client()
    signed = Signed(smb)
    header = Header(command=messages.ECHO, message_id=9, session_id=signed.session_id)
    [(status, _)] = signed.send(pack_message(header, struct.pack("<HH", 4, 0)))
    assert status == nt_errors.STATUS_ACCESS_DENIED


def test_an_oversized_frame_ends_the_connection_without_being_read(world):
    with raw_socket(world) as sock:
        sock.sendall(b"\x00\xff\xff\xff" + b"\xfeSMB")
        assert sock.recv(4096) == b""


def test_a_flood_before_login_is_cut_at_the_framework_budget(world):
    started = time.monotonic()
    junk = frame_message(b"\xfeSMB" + bytes(10_000))
    with raw_socket(world) as sock:
        for _ in range(20):
            try:
                sock.sendall(junk)
            except OSError:
                break
        sock.settimeout(5)
        while True:
            try:
                if not sock.recv(65536):
                    break
            except OSError:
                break
    assert time.monotonic() - started < 10


def test_an_smb1_negotiate_offering_only_smb_2002_gets_that_dialect(world):
    names = b"\x02NT LM 0.12\x00\x02SMB 2.002\x00"
    body = b"\xffSMB\x72" + b"\x00" * 27 + b"\x00" + struct.pack("<H", len(names)) + names
    with raw_socket(world) as sock:
        reply = exchange(sock, frame_message(body))
    assert reply[4:8] == b"\xfeSMB"
    assert struct.unpack_from("<H", reply, 4 + 64 + 4)[0] == 0x0202


def test_random_signed_requests_never_hang_or_break_the_service(world):
    generator = random.Random(11)  # noqa: S311 - seeded, repeatable
    commands = [
        messages.TREE_CONNECT,
        messages.TREE_DISCONNECT,
        messages.CREATE,
        messages.CLOSE,
        messages.FLUSH,
        messages.READ,
        messages.WRITE,
        messages.LOCK,
        messages.IOCTL,
        messages.QUERY_DIRECTORY,
        messages.CHANGE_NOTIFY,
        messages.QUERY_INFO,
        messages.SET_INFO,
        messages.OPLOCK_BREAK,
        messages.ECHO,
        77,
    ]
    sizes = {
        messages.CREATE: 57,
        messages.CLOSE: 24,
        messages.READ: 49,
        messages.WRITE: 49,
        messages.IOCTL: 57,
        messages.QUERY_DIRECTORY: 33,
        messages.QUERY_INFO: 41,
        messages.SET_INFO: 33,
        messages.TREE_CONNECT: 9,
        messages.FLUSH: 24,
        messages.LOCK: 48,
        messages.ECHO: 4,
    }
    started = time.monotonic()
    answered = 0
    smb = world.client()
    signed = Signed(smb)
    for _ in range(600):
        command = generator.choice(commands)
        body = struct.pack("<H", sizes.get(command, 4)) + generator.randbytes(
            generator.choice((4, 30, 70, 200))
        )
        try:
            signed.send(signed.message(command, body))
            answered += 1
        except (NetBIOSError, OSError):
            smb = world.client()
            signed = Signed(smb)
    assert time.monotonic() - started < 60
    assert answered > 100
    world.client().logoff()
    errors = [r for r in world.records("service-request") if r["name"] == "service-error"]
    assert errors == []


def test_the_authenticated_read_budget_still_has_an_end(world, monkeypatch):
    monkeypatch.setattr(smb_module, "AUTHENTICATED_READ_BUDGET", 2 * 1024 * 1024)
    smb = world.client()
    tree = smb.connectTree("C$")
    handle = smb.createFile(tree, "toobig.bin")

    def write_until_cut():
        for number in range(60):
            smb.writeFile(tree, handle, bytes(60_000), number * 60_000)

    with pytest.raises(Exception):  # noqa: B017, PT011 - impacket raises its own socket errors
        write_until_cut()
    for _ in range(100):
        if world.records("file-write"):
            break
        time.sleep(0.05)
    [written] = world.records("file-write")
    assert 0 < written["size"] < 3 * 1024 * 1024
    assert any(r["name"] == "read-cap-exceeded" for r in world.records("service-request"))
