import asyncio
import contextlib
import random
import struct
import time

import pytest

from lan_sim.services.rdp_format import RdpFormatError
from lan_sim.services.rdp_x224 import (
    FAILURE_HYBRID_REQUIRED_BY_SERVER,
    FAILURE_SSL_REQUIRED_BY_SERVER,
    MAX_COOKIE_BYTES,
    MAX_TPKT_BYTES,
    PROTOCOL_HYBRID,
    PROTOCOL_HYBRID_EX,
    PROTOCOL_SSL,
    connection_confirm,
    connection_failure,
    describe_protocols,
    parse_connection_request,
    read_tpkt,
)

MSTSC_COOKIE = b"Cookie: mstshash=admin\r\n"


def request_body(cookie=MSTSC_COOKIE, protocols=0x0B, *, negotiation=True, trailer=b""):
    var = cookie + (struct.pack("<BBHI", 1, 0, 8, protocols) if negotiation else b"") + trailer
    return bytes([6 + len(var), 0xE0, 0, 0, 0, 0, 0]) + var


def tpkt(body: bytes) -> bytes:
    return b"\x03\x00" + struct.pack(">H", 4 + len(body)) + body


def reader_of(data: bytes):
    position = 0

    async def read_exactly(size: int) -> bytes:
        nonlocal position
        chunk = data[position : position + size]
        if len(chunk) < size:
            raise RdpFormatError("the stream ended")
        position += size
        return chunk

    return read_exactly


def test_a_windows_client_request_yields_its_cookie_and_the_protocols_it_offers():
    request = parse_connection_request(request_body())

    assert request.cookie == "admin"
    assert request.requested_protocols == PROTOCOL_SSL | PROTOCOL_HYBRID | PROTOCOL_HYBRID_EX
    assert request.requests_hybrid


def test_a_request_without_a_cookie_or_negotiation_asks_for_standard_rdp_security():
    request = parse_connection_request(request_body(cookie=b"", negotiation=False))

    assert request.cookie is None
    assert request.requested_protocols == 0
    assert not request.requests_hybrid


def test_an_ssl_only_request_does_not_request_hybrid():
    request = parse_connection_request(request_body(protocols=PROTOCOL_SSL))

    assert request.requested_protocols == PROTOCOL_SSL
    assert not request.requests_hybrid


def test_a_cookie_that_is_not_mstshash_is_kept_whole():
    request = parse_connection_request(request_body(cookie=b"Cookie: msts=3640205\r\n"))

    assert request.cookie == "msts=3640205"


def test_a_binary_routing_token_is_skipped_and_negotiation_still_read():
    request = parse_connection_request(request_body(cookie=b"\x02\xff\xfe\r\n"))

    assert request.cookie is None
    assert request.requested_protocols == 0x0B


def test_the_correlation_info_after_the_negotiation_request_is_ignored():
    request = parse_connection_request(request_body(trailer=bytes([6, 0, 36, 0]) + bytes(32)))

    assert request.requested_protocols == 0x0B


def test_an_overlong_cookie_is_cut_to_the_cap():
    cookie = b"Cookie: mstshash=" + b"A" * 200 + b"\r\n"

    request = parse_connection_request(request_body(cookie=cookie))

    assert request.cookie == "A" * (MAX_COOKIE_BYTES)


def test_a_cookie_with_invalid_utf8_decodes_with_replacement():
    request = parse_connection_request(request_body(cookie=b"Cookie: mstshash=\xff\xfe\r\n"))

    assert request.cookie == "��"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\x06\xe0\x00\x00\x00",
        bytes([5, 0xE0, 0, 0, 0, 0, 0]),
        bytes([9, 0xE0, 0, 0, 0, 0, 0]),
        bytes([6, 0xD0, 0, 0, 0, 0, 0]),
        request_body(cookie=b"Cookie: mstshash=admin"),
        bytes([6 + 9, 0xE0, 0, 0, 0, 0, 0]) + struct.pack("<BBHI", 1, 0, 9, 1) + b"\x00",
    ],
    ids=[
        "empty",
        "short",
        "length-indicator-too-small",
        "length-indicator-too-big",
        "not-a-connection-request",
        "cookie-without-crlf",
        "negotiation-length-not-8",
    ],
)
def test_a_malformed_connection_request_is_refused(body):
    with pytest.raises(RdpFormatError):
        parse_connection_request(body)


def test_random_bytes_never_raise_anything_but_the_format_error_and_finish_fast():
    generator = random.Random(1234)  # noqa: S311
    started = time.monotonic()

    for _ in range(3000):
        blob = generator.randbytes(generator.randrange(0, 200))
        for candidate in (blob, bytes([len(blob), 0xE0]) + blob):
            with contextlib.suppress(RdpFormatError):
                parse_connection_request(candidate)

    assert time.monotonic() - started < 2


def test_read_tpkt_returns_the_body_after_the_header():
    body = request_body()

    assert asyncio.run(read_tpkt(reader_of(tpkt(body)))) == body


@pytest.mark.parametrize(
    "header",
    [
        b"\x00\x00\x00\x2b",
        b"\x03\x00\x00\x0a",
        b"\x03\x00\x00\x00",
        b"\x03\x00" + struct.pack(">H", MAX_TPKT_BYTES + 1),
        b"\x16\x03\x01\x02",
    ],
    ids=["fast-path", "below-minimum", "zero", "above-maximum", "tls-client-hello"],
)
def test_a_bad_tpkt_header_is_refused_before_any_body_is_read(header):
    with pytest.raises(RdpFormatError):
        asyncio.run(read_tpkt(reader_of(header)))


def test_connection_confirm_selects_the_protocol_with_a_neg_rsp():
    packet = connection_confirm(PROTOCOL_HYBRID)

    assert packet == bytes.fromhex("030000130ed000001234000200080002000000")


def test_connection_failure_carries_the_failure_code_in_a_neg_failure():
    packet = connection_failure(FAILURE_HYBRID_REQUIRED_BY_SERVER)

    assert packet[:4] == b"\x03\x00\x00\x13"
    assert packet[11:] == struct.pack("<BBHI", 3, 0, 8, FAILURE_HYBRID_REQUIRED_BY_SERVER)
    assert connection_failure(FAILURE_SSL_REQUIRED_BY_SERVER)[-4:] == b"\x01\x00\x00\x00"


def test_protocols_are_described_by_name_for_the_log():
    assert describe_protocols(0x0B) == "SSL|HYBRID|HYBRID_EX"
    assert describe_protocols(0) == "RDP"
    assert describe_protocols(0x10) == "0x10"
