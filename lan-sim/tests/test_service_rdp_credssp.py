import asyncio
import contextlib
import random
import time

import pytest

from lan_sim.services.rdp_credssp import (
    MAX_TS_REQUEST_BYTES,
    SERVER_VERSION,
    STATUS_LOGON_FAILURE,
    build_ts_request,
    parse_ts_request,
    read_ts_request,
)
from lan_sim.services.rdp_format import RdpFormatError


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


def test_a_ts_request_with_a_nego_token_round_trips():
    packet = build_ts_request(6, nego_token=b"NTLMSSP\x00token")

    request = parse_ts_request(packet)

    assert request.version == 6
    assert request.nego_token == b"NTLMSSP\x00token"
    assert request.error_code is None


def test_the_logon_failure_reply_is_a_ts_request_with_error_code_c000006d():
    packet = build_ts_request(6, error_code=STATUS_LOGON_FAILURE)

    request = parse_ts_request(packet)

    assert request.error_code == STATUS_LOGON_FAILURE == 0xC000006D
    assert request.nego_token is None


def test_the_error_code_is_a_four_byte_integer_as_the_spike_clients_expect():
    packet = build_ts_request(6, error_code=STATUS_LOGON_FAILURE)

    assert packet.endswith(bytes.fromhex("a4060204c000006d"))


def test_a_real_clients_request_with_pub_key_auth_and_nonce_is_parsed():
    # version 6, one nego token, pubKeyAuth [3] and clientNonce [5], as a CredSSP v6 client sends
    token = b"NTLMSSP\x00" + bytes(10)
    nego = b"\xa1\x14\x30\x12\x30\x10\xa0\x0e\x04\x0c" + token[:12]
    body = (
        b"\xa0\x03\x02\x01\x06" + nego + b"\xa3\x04\x04\x02\xab\xcd" + b"\xa5\x04\x04\x02\x01\x02"
    )
    packet = b"\x30" + bytes([len(body)]) + body

    request = parse_ts_request(packet)

    assert request.version == 6
    assert request.nego_token == token[:12]
    assert request.has_pub_key_auth
    assert not request.has_auth_info


def test_long_form_lengths_are_read_from_a_stream_and_parsed():
    token = b"N" * 3000
    packet = build_ts_request(SERVER_VERSION, nego_token=token)

    request = parse_ts_request(asyncio.run(read_ts_request(reader_of(packet))))

    assert request.nego_token == token


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"\x30",
        b"\x30\x00",
        b"\x31\x03\xa0\x01\x06",
        b"\x30\x05\xa0\x03\x02\x01\x06\x00",
        b"\x30\x80\xa0\x03\x02\x01\x06\x00\x00",
        b"\x30\x03\xa0\x03\x02\x01",
        b"\x30\x84\xff\xff\xff\xff",
        b"\x30\x05\xa0\x03\x04\x01\x06",
        b"\x30\x0a\xa0\x03\x02\x01\x06\xa1\x03\x04\x01\x00",
    ],
    ids=[
        "empty",
        "tag-only",
        "no-version",
        "wrong-tag",
        "trailing-bytes",
        "indefinite-length",
        "truncated",
        "huge-length",
        "version-not-an-integer",
        "nego-tokens-not-a-sequence",
    ],
)
def test_a_malformed_ts_request_is_refused(packet):
    with pytest.raises(RdpFormatError):
        parse_ts_request(packet)


def test_a_length_over_the_cap_is_refused_before_the_body_is_read():
    declared = MAX_TS_REQUEST_BYTES + 1
    header = b"\x30\x83" + declared.to_bytes(3, "big")

    with pytest.raises(RdpFormatError):
        asyncio.run(read_ts_request(reader_of(header)))


def test_a_five_byte_der_length_is_refused():
    with pytest.raises(RdpFormatError):
        asyncio.run(read_ts_request(reader_of(b"\x30\x85\x01\x00\x00\x00\x00")))


def test_a_stream_that_is_not_der_is_refused_at_the_first_byte():
    with pytest.raises(RdpFormatError):
        asyncio.run(read_ts_request(reader_of(b"\x16\x03\x01" + bytes(100))))


def test_random_bytes_never_raise_anything_but_the_format_error_and_finish_fast():
    generator = random.Random(99)  # noqa: S311
    started = time.monotonic()

    for _ in range(3000):
        blob = generator.randbytes(generator.randrange(0, 120))
        for candidate in (blob, b"\x30" + bytes([len(blob)]) + blob):
            with contextlib.suppress(RdpFormatError):
                parse_ts_request(candidate)

    assert time.monotonic() - started < 2


def test_mutated_valid_requests_never_crash_the_parser():
    generator = random.Random(7)  # noqa: S311
    valid = build_ts_request(6, nego_token=b"NTLMSSP\x00" * 5)

    for _ in range(3000):
        mutated = bytearray(valid)
        for _ in range(generator.randrange(1, 4)):
            mutated[generator.randrange(len(mutated))] = generator.randrange(256)
        with contextlib.suppress(RdpFormatError):
            parse_ts_request(bytes(mutated))
