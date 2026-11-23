"""Parsers of the SMB2 command bodies against truncated, oversized and random input."""

import contextlib
import random
import struct

import pytest

from lan_sim.services import smb_messages as messages
from lan_sim.services.smb_wire import SmbFormatError

PARSERS = {
    "negotiate": (messages.parse_negotiate, 36),
    "session setup": (messages.parse_session_setup, 25),
    "tree connect": (messages.parse_tree_connect, 9),
    "create": (messages.parse_create, 57),
    "close": (messages.parse_close, 24),
    "read": (messages.parse_read, 49),
    "write": (lambda body: messages.parse_write(body, 65536), 49),
    "query info": (messages.parse_query_info, 41),
    "set info": (messages.parse_set_info, 33),
    "query directory": (messages.parse_query_directory, 33),
    "ioctl": (messages.parse_ioctl, 57),
}


def tree_connect_body(path: str) -> bytes:
    raw = path.encode("utf-16le")
    return struct.pack("<HHHH", 9, 0, 72, len(raw)) + raw


def test_a_well_formed_tree_connect_parses():
    assert messages.parse_tree_connect(tree_connect_body("\\\\fs01\\C$")) == "\\\\fs01\\C$"


def test_a_name_that_points_outside_the_message_is_refused():
    body = struct.pack("<HHHH", 9, 0, 72, 400) + b"x" * 8
    with pytest.raises(SmbFormatError):
        messages.parse_tree_connect(body)
    behind_the_header = struct.pack("<HHHH", 9, 0, 10, 4) + b"x" * 8
    with pytest.raises(SmbFormatError):
        messages.parse_tree_connect(behind_the_header)


def test_an_oversized_name_and_an_odd_length_name_are_refused():
    with pytest.raises(SmbFormatError):
        messages.parse_tree_connect(tree_connect_body("a" * 600))
    odd = struct.pack("<HHHH", 9, 0, 72, 3) + b"abc"
    with pytest.raises(SmbFormatError):
        messages.parse_tree_connect(odd)


def test_a_lone_surrogate_in_a_name_is_refused():
    body = struct.pack("<HHHH", 9, 0, 72, 2) + b"\x00\xd8"
    with pytest.raises(SmbFormatError):
        messages.parse_tree_connect(body)


def test_a_negotiate_with_no_dialects_or_too_many_is_refused():
    fixed = struct.pack("<HHHHI16s8s", 36, 0, 1, 0, 0, bytes(16), bytes(8))
    with pytest.raises(SmbFormatError):
        messages.parse_negotiate(fixed)
    too_many = struct.pack("<HHHHI16s8s", 36, 500, 1, 0, 0, bytes(16), bytes(8)) + bytes(1000)
    with pytest.raises(SmbFormatError):
        messages.parse_negotiate(too_many)


def test_negotiate_contexts_are_bounded_and_checked():
    tail = struct.pack("<IHH", 70, 200, 0)
    body = struct.pack("<HHHHI16s8s", 36, 1, 1, 0, 0, bytes(16), tail)
    with pytest.raises(SmbFormatError):
        messages.parse_negotiate(body + struct.pack("<H", 0x0311) + bytes(6))
    cut = struct.pack("<IHH", 64 + 38 + 8, 1, 0)
    body = struct.pack("<HHHHI16s8s", 36, 1, 1, 0, 0, bytes(16), cut)
    with pytest.raises(SmbFormatError):
        messages.parse_negotiate(body + struct.pack("<H", 0x0311) + bytes(6) + b"\x01\x00\xff\xff")


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_every_parser_refuses_truncated_and_empty_bodies(name):
    parse, size = PARSERS[name]
    for body in (b"", b"\x00", struct.pack("<H", size), struct.pack("<H", size) + b"\x00" * 5):
        with pytest.raises(SmbFormatError):
            parse(body)


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_every_parser_only_ever_raises_a_format_error_on_random_bodies(name):
    parse, size = PARSERS[name]
    generator = random.Random(name)  # noqa: S311 - seeded, repeatable
    for _ in range(1500):
        length = generator.choice((8, 24, 40, 56, 64, 80, 200, 1000))
        body = struct.pack("<H", size) + generator.randbytes(length)
        with contextlib.suppress(SmbFormatError):
            parse(body)


def test_the_error_reply_and_empty_reply_have_their_fixed_sizes():
    assert len(messages.error_response()) == 9
    assert len(messages.empty_response()) == 4
    assert len(messages.write_response(5)) == 17
    assert len(messages.read_response(b"abc")) == 16 + 3
