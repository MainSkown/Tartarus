"""The RDP service over real sockets: X.224, TLS, CredSSP, with an impacket NTLM client."""

import asyncio
import ssl
import struct
import time
from contextlib import suppress

from impacket import ntlm as impacket_ntlm
from impacket import spnego
from test_daemon import GUEST_A, World, address_of, host, session

from lan_sim.ntlm import (
    CHALLENGE_MESSAGE,
    NTLMSSP_SIGNATURE,
    ntlm_message_type,
    unwrap_ntlmssp,
)
from lan_sim.services.rdp import SERVICE
from lan_sim.services.rdp_credssp import (
    STATUS_LOGON_FAILURE,
    build_ts_request,
    parse_ts_request,
    read_ts_request,
)
from lan_sim.services.rdp_x224 import (
    FAILURE_HYBRID_REQUIRED_BY_SERVER,
    FAILURE_SSL_REQUIRED_BY_SERVER,
    PROTOCOL_HYBRID,
    PROTOCOL_SSL,
)

ALL_PROTOCOLS = 0x0B
NEG_RSP = 2
NEG_FAILURE = 3


def scenario(**limits):
    def decorate(test):
        def wrapper(tmp_path):
            async def body():
                world = World(tmp_path, services={"rdp": SERVICE}, **limits)
                try:
                    await test(world)
                finally:
                    await world.daemon.shutdown()

            asyncio.run(body())

        wrapper.__name__ = test.__name__
        return wrapper

    return decorate


def rdp_session(**kwargs):
    return session(hosts=[host(kind="rdp", **kwargs)])


def connection_request(cookie=b"Cookie: mstshash=admin\r\n", protocols=ALL_PROTOCOLS):
    negotiation = struct.pack("<BBHI", 1, 0, 8, protocols)
    variable = cookie + negotiation
    x224 = bytes([6 + len(variable), 0xE0, 0, 0, 0, 0, 0]) + variable
    return b"\x03\x00" + struct.pack(">H", 4 + len(x224)) + x224


class RdpClient:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    @classmethod
    async def connect(cls, address, *, source=GUEST_A):
        reader, writer = await asyncio.open_connection(*address, local_addr=(source, 0))
        return cls(reader, writer)

    async def negotiate(self, request=None):
        self.writer.write(request or connection_request())
        header = await asyncio.wait_for(self.reader.readexactly(4), 5)
        size = struct.unpack(">H", header[2:])[0] - 4
        return await asyncio.wait_for(self.reader.readexactly(size), 5)

    async def start_tls(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        await asyncio.wait_for(self.writer.start_tls(context), 5)

    async def send_ts_request(self, **fields):
        self.writer.write(build_ts_request(6, **fields))
        await self.writer.drain()

    async def read_ts_request(self):
        return parse_ts_request(await asyncio.wait_for(read_ts_request(self.reader.readexactly), 5))

    async def at_end(self) -> bool:
        with suppress(ConnectionError, ssl.SSLError):
            return await asyncio.wait_for(self.reader.read(1), 5) == b""
        return True

    def close(self):
        self.writer.close()


def type1_message() -> bytes:
    return impacket_ntlm.getNTLMSSPType1("WS01", "CORP", use_ntlmv2=True).getData()


def spnego_wrapped(ntlm_message: bytes) -> bytes:
    token = spnego.SPNEGO_NegTokenInit()
    token["MechTypes"] = [spnego.TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]]
    token["MechToken"] = ntlm_message
    return bytes(token.getData())


def type3_message(user, password, type2: bytes, domain="CORP") -> bytes:
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", domain, use_ntlmv2=True)
    type3, _ = impacket_ntlm.getNTLMSSPType3(type1, type2, user, password, domain, use_ntlmv2=True)
    return bytes(type3.getData())


def hashcat_line(type3: bytes, type2: bytes) -> str:
    message = impacket_ntlm.NTLMAuthChallengeResponse()
    message.fromString(type3)
    user = message["user_name"].decode("utf-16le")
    domain = message["domain_name"].decode("utf-16le")
    response = message["ntlm"]
    return f"{user}::{domain}:{type2[24:32].hex()}:{response[:16].hex()}:{response[16:].hex()}"


async def login(world, spec, user, password, *, wrap=False):
    """Runs the whole NLA exchange; returns (type2, type3, final TSRequest)."""
    client = await RdpClient.connect(address_of(spec))
    try:
        confirm = await client.negotiate()
        assert confirm[-8:-4] == bytes([NEG_RSP, 0, 8, 0])
        await client.start_tls()
        type1 = type1_message()
        await client.send_ts_request(nego_token=spnego_wrapped(type1) if wrap else type1)
        challenge = await client.read_ts_request()
        type2 = unwrap_ntlmssp(challenge.nego_token)
        type3 = type3_message(user, password, type2)
        await client.send_ts_request(nego_token=spnego_wrapped(type3) if wrap else type3)
        final = await client.read_ts_request()
        assert await client.at_end()
        return challenge, type2, type3, final
    finally:
        client.close()


@scenario()
async def test_a_known_account_is_logged_as_successful_and_still_refused_with_logon_failure(world):
    spec = rdp_session()
    await world.open(spec)

    _, type2, type3, final = await login(world, spec, "admin", "pw")

    await world.settle("task-1")
    [attempt] = world.log_of_type("task-1", "login-attempt")
    assert attempt["success"] is True
    assert attempt["mechanism"] == "ntlm"
    assert attempt["user"] == "admin"
    assert attempt["domain"] == "CORP"
    assert attempt["secret"] == hashcat_line(type3, type2)
    assert attempt["service"] == "rdp"
    assert final.error_code == STATUS_LOGON_FAILURE
    assert final.nego_token is None


@scenario()
async def test_a_wrong_password_is_logged_as_failed_with_a_crackable_hash(world):
    spec = rdp_session()
    await world.open(spec)

    _, type2, type3, final = await login(world, spec, "admin", "not-the-password")

    await world.settle("task-1")
    [attempt] = world.log_of_type("task-1", "login-attempt")
    assert attempt["success"] is False
    assert attempt["secret"] == hashcat_line(type3, type2)
    assert final.error_code == STATUS_LOGON_FAILURE


@scenario()
async def test_an_unknown_user_is_logged_as_failed(world):
    spec = rdp_session()
    await world.open(spec)

    await login(world, spec, "nobody", "pw")

    await world.settle("task-1")
    [attempt] = world.log_of_type("task-1", "login-attempt")
    assert (attempt["user"], attempt["success"]) == ("nobody", False)


@scenario()
async def test_the_challenge_names_the_host_and_is_fresh_for_every_connection(world):
    spec = rdp_session()
    await world.open(spec)

    first, first_type2, *_ = await login(world, spec, "admin", "pw")
    _, second_type2, *_ = await login(world, spec, "admin", "pw")

    assert ntlm_message_type(first_type2) == CHALLENGE_MESSAGE
    assert "FS01".encode("utf-16le") in first_type2
    assert first_type2[24:32] != second_type2[24:32]
    assert first.version == 6


@scenario()
async def test_a_client_that_wraps_ntlm_in_spnego_gets_an_spnego_challenge(world):
    spec = rdp_session()
    await world.open(spec)

    challenge, type2, type3, _ = await login(world, spec, "admin", "pw", wrap=True)

    assert not challenge.nego_token.startswith(NTLMSSP_SIGNATURE)
    await world.settle("task-1")
    [attempt] = world.log_of_type("task-1", "login-attempt")
    assert attempt["secret"] == hashcat_line(type3, type2)


@scenario()
async def test_a_client_that_sends_raw_ntlm_gets_a_raw_challenge(world):
    spec = rdp_session()
    await world.open(spec)

    challenge, *_ = await login(world, spec, "admin", "pw")

    assert challenge.nego_token.startswith(NTLMSSP_SIGNATURE)


@scenario()
async def test_the_connection_request_and_its_cookie_are_logged(world):
    spec = rdp_session()
    await world.open(spec)

    await login(world, spec, "admin", "pw")

    await world.settle("task-1")
    [request] = [
        event
        for event in world.log_of_type("task-1", "service-request")
        if event["name"] == "rdp connection request"
    ]
    assert request["detail"] == "cookie=admin protocols=SSL|HYBRID|HYBRID_EX"


@scenario()
async def test_the_certificate_names_the_host(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        await client.negotiate()
        await client.start_tls()
        der = client.writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    finally:
        client.close()

    assert b"fs01.corp.local" in der


@scenario()
async def test_an_ssl_only_request_is_answered_with_hybrid_required_and_logged(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        reply = await client.negotiate(connection_request(protocols=PROTOCOL_SSL))
        assert reply[-8:] == struct.pack(
            "<BBHI", NEG_FAILURE, 0, 8, FAILURE_HYBRID_REQUIRED_BY_SERVER
        )
        assert await client.at_end()
    finally:
        client.close()

    await world.settle("task-1")
    names = [event["name"] for event in world.log_of_type("task-1", "service-request")]
    assert "rdp connection request" in names
    assert world.log_of_type("task-1", "login-attempt") == []


@scenario()
async def test_a_standard_rdp_security_request_is_answered_with_ssl_required(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        reply = await client.negotiate(connection_request(protocols=0))
        assert reply[-8:] == struct.pack("<BBHI", NEG_FAILURE, 0, 8, FAILURE_SSL_REQUIRED_BY_SERVER)
        assert await client.at_end()
    finally:
        client.close()


@scenario()
async def test_a_hybrid_only_request_is_accepted(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        reply = await client.negotiate(connection_request(protocols=PROTOCOL_HYBRID))
        assert reply[-8:] == struct.pack("<BBHI", NEG_RSP, 0, 8, PROTOCOL_HYBRID)
    finally:
        client.close()


async def flood(client, megabytes=10):
    chunk = bytes(range(256)) * 4096
    with suppress(ConnectionError, ssl.SSLError):
        for _ in range(megabytes):
            client.writer.write(chunk)
            await asyncio.wait_for(client.writer.drain(), 5)
    return await client.at_end()


@scenario()
async def test_ten_megabytes_of_garbage_instead_of_a_connection_request_end_the_connection(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    started = time.monotonic()

    try:
        assert await flood(client)
    finally:
        client.close()

    assert time.monotonic() - started < 5
    await world.settle("task-1")
    assert world.log_of_type("task-1", "login-attempt") == []
    [connection] = world.log_of_type("task-1", "connection")
    assert connection["bytes_in"] <= 4


@scenario()
async def test_ten_megabytes_of_garbage_inside_tls_end_the_connection(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    started = time.monotonic()

    try:
        await client.negotiate()
        await client.start_tls()
        assert await flood(client)
    finally:
        client.close()

    assert time.monotonic() - started < 5
    await world.settle("task-1")
    names = [event["name"] for event in world.log_of_type("task-1", "service-request")]
    assert "rdp malformed request" in names


@scenario()
async def test_a_der_length_of_four_gigabytes_ends_the_connection_without_reading_it(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        await client.negotiate()
        await client.start_tls()
        client.writer.write(b"\x30\x84\xff\xff\xff\xff" + bytes(1000))
        assert await client.at_end()
    finally:
        client.close()

    await world.settle("task-1")
    [connection] = world.log_of_type("task-1", "connection")
    assert connection["bytes_in"] < 2000


@scenario()
async def test_a_negotiate_token_that_is_not_ntlm_ends_the_connection_and_is_logged(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        await client.negotiate()
        await client.start_tls()
        await client.send_ts_request(nego_token=b"\x60\x03kerberos-only")
        assert await client.at_end()
    finally:
        client.close()

    await world.settle("task-1")
    names = [event["name"] for event in world.log_of_type("task-1", "service-request")]
    assert "rdp malformed request" in names


@scenario()
async def test_an_authenticate_sent_without_a_negotiate_is_not_accepted(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        await client.negotiate()
        await client.start_tls()
        authenticate = impacket_ntlm.NTLMAuthChallengeResponse("admin", "pw", bytes(8)).getData()
        await client.send_ts_request(nego_token=authenticate)
        assert await client.at_end()
    finally:
        client.close()

    await world.settle("task-1")
    assert world.log_of_type("task-1", "login-attempt") == []


@scenario()
async def test_a_malformed_authenticate_is_not_logged_as_a_login(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        await client.negotiate()
        await client.start_tls()
        await client.send_ts_request(nego_token=type1_message())
        await client.read_ts_request()
        await client.send_ts_request(nego_token=NTLMSSP_SIGNATURE + struct.pack("<I", 3) + b"x")
        assert await client.at_end()
    finally:
        client.close()

    await world.settle("task-1")
    assert world.log_of_type("task-1", "login-attempt") == []


@scenario(idle_timeout_seconds=0.3)
async def test_a_client_that_stops_mid_packet_is_dropped_after_the_idle_timeout(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    try:
        client.writer.write(connection_request()[:10])
        assert await client.at_end()
    finally:
        client.close()

    await world.settle("task-1")
    names = [event["name"] for event in world.log_of_type("task-1", "service-request")]
    assert "idle-timeout" in names


@scenario(idle_timeout_seconds=0.5)
async def test_a_tls_client_hello_pipelined_with_the_request_does_not_hang_the_connection(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    started = time.monotonic()
    try:
        client.writer.write(connection_request() + b"\x16\x03\x01\x00\x05hello")
        await asyncio.wait_for(client.reader.read(), 5)
    finally:
        client.close()

    assert time.monotonic() - started < 5


@scenario()
async def test_the_daemon_keeps_serving_after_hostile_connections(world):
    spec = rdp_session()
    await world.open(spec)
    client = await RdpClient.connect(address_of(spec))
    await flood(client, megabytes=1)
    client.close()

    _, _, _, final = await login(world, spec, "admin", "pw")

    assert final.error_code == STATUS_LOGON_FAILURE
