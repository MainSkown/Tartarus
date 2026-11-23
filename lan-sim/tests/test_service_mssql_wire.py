"""TDS framing, prelogin and Login7 parsing: hostile input in, a format error or fields out."""

import random
import struct
import time
from contextlib import suppress

import pytest
from mssql_support import (
    SQL_BATCH,
    TDS_71,
    TDS_72,
    TDS_74,
    batch_packet,
    login7_payload,
    packet,
    prelogin_request,
    run_rig,
)

from lan_sim.service import PeerClosed, ReadCapExceeded
from lan_sim.services.mssql_wire import (
    Message,
    TdsFormatError,
    check_prelogin,
    frame_message,
    parse_login7,
    prelogin_response,
    read_message,
    strip_all_headers,
)


def read(data, **limits):
    message, _ = run_rig(data, lambda rig: read_message(rig.connection), **limits)
    return message


def test_a_single_packet_message_is_returned_with_its_type_and_payload():
    assert read(packet(SQL_BATCH, b"abc")) == Message(SQL_BATCH, b"abc")


def test_packets_are_joined_until_the_end_of_message_bit():
    data = packet(SQL_BATCH, b"ab", status=0) + packet(SQL_BATCH, b"cd", status=0)
    data += packet(SQL_BATCH, b"ef", status=1)

    assert read(data) == Message(SQL_BATCH, b"abcdef")


def test_an_empty_message_is_allowed():
    assert read(packet(0x06)) == Message(0x06, b"")


def test_a_message_that_changes_type_between_packets_is_malformed():
    data = packet(SQL_BATCH, b"ab", status=0) + packet(0x03, b"cd")

    with pytest.raises(TdsFormatError):
        read(data)


@pytest.mark.parametrize("packet_type", [0, 5, 4, 0x13, 0x16, 0xFF])
def test_an_unknown_packet_type_is_malformed(packet_type):
    with pytest.raises(TdsFormatError):
        read(packet(packet_type, b"x"))


@pytest.mark.parametrize("length", [0, 1, 7, 32768, 65535])
def test_a_length_outside_the_protocol_range_is_malformed(length):
    header = struct.pack(">BBHHBB", SQL_BATCH, 1, length, 0, 1, 0)

    with pytest.raises(TdsFormatError):
        read(header + b"\x00" * 100)


def test_a_message_over_the_size_cap_is_malformed_before_it_is_all_read():
    chunk = b"\x00" * 8000
    data = b"".join(packet(SQL_BATCH, chunk, status=0) for _ in range(12))

    with pytest.raises(TdsFormatError):
        read(data, max_bytes_read_per_connection=10 * 1024 * 1024)


def test_a_packet_cut_short_ends_the_connection():
    data = packet(SQL_BATCH, b"abcdef")[:-3]

    with pytest.raises(PeerClosed):
        read(data)


def test_a_header_cut_short_ends_the_connection():
    with pytest.raises(PeerClosed):
        read(b"\x01\x01\x00")


def test_ten_megabytes_of_garbage_is_refused_in_bounded_time():
    started = time.monotonic()

    with pytest.raises((TdsFormatError, ReadCapExceeded)):
        read(b"\x01\x00" * (5 * 1024 * 1024))

    assert time.monotonic() - started < 2


def test_a_stream_of_empty_continuation_packets_hits_the_read_cap():
    with pytest.raises(ReadCapExceeded):
        read(packet(SQL_BATCH, b"", status=0) * 20_000)


def test_random_bytes_never_do_anything_but_raise_the_documented_errors():
    generator = random.Random(1234)  # noqa: S311
    for _ in range(300):
        data = generator.randbytes(generator.randrange(0, 200))
        with suppress(TdsFormatError, PeerClosed, ReadCapExceeded):
            read(data)


def test_a_reply_is_one_packet_with_the_end_of_message_bit():
    framed = frame_message(4, b"hello")

    assert framed == struct.pack(">BBHHBB", 4, 1, 13, 52, 1, 0) + b"hello"


def test_a_long_reply_is_split_to_the_negotiated_packet_size():
    framed = frame_message(4, b"x" * 5000)

    first_length = struct.unpack(">H", framed[2:4])[0]
    second = framed[first_length:]
    assert (framed[1], first_length) == (0, 4096)
    assert (second[1], struct.unpack(">H", second[2:4])[0], second[6]) == (1, 8 + 912, 2)


def test_an_empty_reply_is_still_one_packet():
    assert frame_message(4, b"") == struct.pack(">BBHHBB", 4, 1, 8, 52, 1, 0)


# --- prelogin ---------------------------------------------------------------------------------


def test_a_real_prelogin_request_passes_the_check():
    check_prelogin(prelogin_request()[8:])


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x00",
        b"\x00\x00\x06\x00\x06",
        b"\x00\xff\xff\x00\x10\xff",
        b"\x00\x00\x06\x00\x10\xff",
        b"\x00\x00\x00\x00\x00" * 40 + b"\xff",
    ],
)
def test_a_malformed_prelogin_is_refused(payload):
    with pytest.raises(TdsFormatError):
        check_prelogin(payload)


def test_the_prelogin_reply_announces_sql_server_2019_without_encryption():
    reply = prelogin_response()

    options = {}
    position = 0
    while reply[position] != 0xFF:
        token, offset, length = struct.unpack_from(">BHH", reply, position)
        options[token] = reply[offset : offset + length]
        position += 5
    assert options[0] == struct.pack(">BBHH", 15, 0, 2000, 5)
    assert options[1] == b"\x02"
    assert options[2] == b"\x00"
    assert options[4] == b"\x00"


def test_the_prelogin_reply_has_exactly_four_options_for_impackets_fixed_parser():
    reply = prelogin_response()

    assert reply[20] == 0xFF
    assert [reply[position] for position in (0, 5, 10, 15)] == [0, 1, 2, 4]


# --- Login7 -----------------------------------------------------------------------------------


def test_a_login7_record_yields_every_field_and_the_clear_password():
    request = parse_login7(
        login7_payload(
            host="WS01",
            user="sa",
            password="P@ss w0rd",
            app="sqlcmd",
            server="fs01",
            language="us_english",
            database="master",
        )
    )

    assert (request.host, request.user, request.password) == ("WS01", "sa", "P@ss w0rd")
    assert (request.app, request.server) == ("sqlcmd", "fs01")
    assert (request.language, request.database) == ("us_english", "master")
    assert request.integrated_security is False
    assert request.sspi == b""


@pytest.mark.parametrize("version", [TDS_71, TDS_72, 0x730B0003, TDS_74, 0x70000000])
def test_both_login7_layouts_parse(version):
    request = parse_login7(login7_payload(version=version, user="alice", password="x"))

    assert (request.user, request.password) == ("alice", "x")


def test_non_ascii_text_survives_the_round_trip():
    request = parse_login7(login7_payload(user="zoë", password="pässwörd✓"))

    assert (request.user, request.password) == ("zoë", "pässwörd✓")


def test_the_sspi_blob_and_the_integrated_flag_are_read():
    request = parse_login7(login7_payload(integrated=True, sspi=b"NTLMSSP\x00blob", user=""))

    assert request.integrated_security is True
    assert request.sspi == b"NTLMSSP\x00blob"


def test_the_long_sspi_length_is_used_when_the_short_one_is_the_marker():
    request = parse_login7(login7_payload(integrated=True, sspi=b"x" * 600, long_sspi=True))

    assert request.sspi == b"x" * 600


def test_zero_length_fields_are_empty_strings():
    request = parse_login7(login7_payload(host="", user="", password="", app="", server=""))

    assert (request.host, request.user, request.password) == ("", "", "")


@pytest.mark.parametrize(
    ("version", "wire"),
    [(TDS_71, 0x71000001), (TDS_72, 0x72090002), (TDS_74, 0x74000004)],
)
def test_the_version_decides_the_reply_layout_and_is_acknowledged(version, wire):
    parsed = parse_login7(login7_payload(version=version)).version

    assert parsed.legacy_layout is (version == TDS_71)
    assert parsed.acknowledged == wire


@pytest.mark.parametrize("version", [0, 0x6F000000, 0x75000000, 0xFFFFFFFF, 0x08])
def test_an_unsupported_tds_version_is_refused(version):
    with pytest.raises(TdsFormatError):
        parse_login7(login7_payload(version=version))


def test_a_record_shorter_than_the_fixed_part_is_refused():
    with pytest.raises(TdsFormatError):
        parse_login7(login7_payload()[:85])


def _with_field(payload: bytes, index: int, offset: int, characters: int) -> bytes:
    patched = bytearray(payload)
    struct.pack_into("<HH", patched, 36 + 4 * index, offset, characters)
    return bytes(patched)


PARSED_FIELDS = (0, 1, 2, 3, 4, 7, 8)
UNUSED_FIELDS = (5, 6)


@pytest.mark.parametrize("index", PARSED_FIELDS)
@pytest.mark.parametrize(
    ("offset", "characters"),
    [(0xFFFF, 1), (94, 0x7FFF), (400, 4), (10, 2), (0, 1), (86, 129), (0xFFF0, 0xFFFF)],
)
def test_a_field_pointing_outside_the_record_is_refused(index, offset, characters):
    payload = _with_field(login7_payload(), index, offset, characters)

    with pytest.raises(TdsFormatError):
        parse_login7(payload)


@pytest.mark.parametrize("index", UNUSED_FIELDS)
def test_the_fields_the_service_never_reads_cannot_hurt(index):
    payload = _with_field(login7_payload(user="alice"), index, 0xFFFF, 0xFFFF)

    assert parse_login7(payload).user == "alice"


def test_an_sspi_blob_pointing_outside_the_record_is_refused():
    payload = bytearray(login7_payload(integrated=True, sspi=b"abc"))
    struct.pack_into("<HH", payload, 78, 0xFFF0, 40)

    with pytest.raises(TdsFormatError):
        parse_login7(bytes(payload))


def test_an_oversize_sspi_blob_is_refused():
    payload = bytearray(login7_payload(integrated=True, sspi=b"abc", long_sspi=True))
    struct.pack_into("<I", payload, 90, 10_000_000)

    with pytest.raises(TdsFormatError):
        parse_login7(bytes(payload))


def test_random_login7_records_only_raise_the_documented_error():
    generator = random.Random(99)  # noqa: S311
    template = login7_payload(integrated=True, sspi=b"NTLMSSP\x00abc")
    for _ in range(2000):
        record = bytearray(template)
        for _ in range(generator.randrange(1, 6)):
            record[generator.randrange(len(record))] = generator.randrange(256)
        record = bytes(record)[: generator.randrange(60, len(record) + 1)]
        with suppress(TdsFormatError):
            parse_login7(record)


def test_pure_random_bytes_are_never_a_login7_record_that_crashes():
    generator = random.Random(7)  # noqa: S311
    for _ in range(500):
        with suppress(TdsFormatError):
            parse_login7(generator.randbytes(generator.randrange(0, 300)))


# --- ALL_HEADERS ------------------------------------------------------------------------------


def test_the_all_headers_block_is_skipped_by_its_own_length():
    body = "select 1".encode("utf-16le")

    assert strip_all_headers(batch_packet("select 1")[8:]) == body


def test_a_body_without_the_block_is_returned_whole():
    body = "select 1".encode("utf-16le")

    assert strip_all_headers(body) == body
    assert strip_all_headers(b"") == b""
    assert strip_all_headers(b"ab") == b"ab"


def test_a_block_length_past_the_payload_is_not_a_block():
    payload = struct.pack("<I", 500) + b"ab"

    assert strip_all_headers(payload) == payload
