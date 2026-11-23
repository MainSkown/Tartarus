"""The SMB service end to end: the daemon on loopback, impacket's own SMB client as the peer."""

import socket
import struct

import pytest
from impacket import nt_errors
from impacket.smb3structs import (
    SMB2_DIALECT_002,
    SMB2_DIALECT_21,
    SMB2_DIALECT_30,
    SMB2_DIALECT_311,
)
from impacket.smbconnection import SessionError
from test_service_smb_support import (
    DOMAIN,
    HOST_ADDRESS,
    PASSWORD,
    USER,
    SignatureAudit,
    SmbWorld,
)

DIALECTS = [SMB2_DIALECT_002, SMB2_DIALECT_21, SMB2_DIALECT_30, SMB2_DIALECT_311]


@pytest.fixture
def world(tmp_path):
    with SmbWorld(tmp_path) as running:
        yield running


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_known_account_logs_in_and_every_response_is_signed_correctly(world, dialect):
    smb = world.client(login=False, preferredDialect=dialect)
    audit = SignatureAudit(smb)
    smb.login(USER, PASSWORD, DOMAIN)
    smb.connectTree("IPC$")
    audit.settle()
    assert smb.getDialect() == dialect
    assert smb.isSigningRequired()
    assert audit.failed == []
    assert audit.unsigned == 0
    assert audit.verified >= 2
    [login] = [r for r in world.records("login-attempt") if r["success"]]
    assert (login["user"], login["domain"], login["mechanism"]) == (USER, DOMAIN, "ntlm")
    assert login["secret"].startswith(f"{USER}::{DOMAIN}:")
    smb.logoff()


def test_the_server_presents_the_hosts_identity(world):
    smb = world.client()
    assert smb.getServerName() == "FS01"
    assert smb.getServerDNSDomainName() == "corp.local"
    assert smb.getServerOS().startswith("Windows")
    smb.logoff()


def test_a_wrong_password_is_refused_and_its_hash_is_logged(world):
    with pytest.raises(SessionError) as refused:
        world.client(password="wrong")
    assert refused.value.getErrorCode() == nt_errors.STATUS_LOGON_FAILURE
    [attempt] = world.records("login-attempt")
    assert attempt["success"] is False
    assert attempt["user"] == USER
    assert attempt["secret"].startswith(f"{USER}::{DOMAIN}:")
    assert len(attempt["secret"].split(":")) == 6


def test_an_account_the_host_does_not_list_is_refused_and_logged(world):
    with pytest.raises(SessionError) as refused:
        world.client(user="mallory", password="whatever")
    assert refused.value.getErrorCode() == nt_errors.STATUS_LOGON_FAILURE
    [attempt] = world.records("login-attempt")
    assert (attempt["user"], attempt["success"]) == ("mallory", False)


def test_the_account_name_is_matched_without_case_or_domain(world):
    smb = world.client(user="administrator", domain="OTHER")
    smb.logoff()


def test_a_request_with_a_bad_signature_is_refused(world):
    smb = world.client()
    server = smb.getSMBServer()
    sign = server.signSMB

    def corrupt(packet):
        sign(packet)
        packet["Signature"] = bytes(16)

    server.signSMB = corrupt
    with pytest.raises(SessionError) as refused:
        smb.connectTree("IPC$")
    assert refused.value.getErrorCode() == nt_errors.STATUS_ACCESS_DENIED


def raw_exchange(world, payload: bytes) -> bytes:
    with socket.create_connection((HOST_ADDRESS, world.port), timeout=5) as sock:
        sock.sendall(payload)
        received = b""
        while chunk := sock.recv(4096):
            received += chunk
        return received


def smb1_negotiate(*dialects: bytes) -> bytes:
    names = b"".join(b"\x02" + name + b"\x00" for name in dialects)
    body = b"\xffSMB\x72" + b"\x00" * 27 + b"\x00" + struct.pack("<H", len(names)) + names
    return b"\x00" + len(body).to_bytes(3, "big") + body


def test_an_smb1_only_negotiate_is_refused_cleanly(world):
    reply = raw_exchange(world, smb1_negotiate(b"NT LM 0.12"))
    assert reply[4:9] == b"\xffSMB\x72"
    assert struct.unpack_from("<H", reply, 4 + 33)[0] == 0xFFFF


def test_the_smb1_multiprotocol_negotiate_is_upgraded_to_smb2(world):
    request = smb1_negotiate(b"NT LM 0.12", b"SMB 2.002", b"SMB 2.???")
    with socket.create_connection((HOST_ADDRESS, world.port), timeout=5) as sock:
        sock.sendall(request)
        reply = sock.recv(4096)
    assert reply[4:8] == b"\xfeSMB"
    dialect = struct.unpack_from("<H", reply, 4 + 64 + 4)[0]
    assert dialect == 0x02FF


def test_garbage_ends_the_connection(world):
    assert raw_exchange(world, b"GET / HTTP/1.1\r\n\r\n") == b""
    assert raw_exchange(world, b"\x00\x00\x00\x08" + b"\xfeSMB" + b"\x00" * 4) == b""
