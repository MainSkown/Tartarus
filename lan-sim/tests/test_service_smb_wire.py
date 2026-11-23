"""The SMB wire layer: framing, the SMB2 header, compound chains and the SMB1 negotiate."""

import asyncio
import contextlib
import random
import struct

import pytest

from lan_sim.services.smb_wire import (
    FLAG_RELATED,
    HEADER_SIZE,
    Header,
    Smb1Negotiate,
    SmbFormatError,
    frame_message,
    pack_message,
    parse_header,
    parse_smb1_negotiate,
    read_frame,
    smb1_negotiate_refusal,
    split_compound,
)


def message(command=5, body=b"\x00" * 8, **fields) -> bytes:
    return pack_message(Header(command=command, **fields), body)


class FakeConnection:
    """Serves `read_exactly` from a byte string, like Connection does."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    async def read_exactly(self, size: int) -> bytes:
        if len(self.data) < size:
            raise ConnectionResetError
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk


def read(data: bytes, limit: int = 1024):
    return asyncio.run(read_frame(FakeConnection(data), limit))


def test_header_round_trip():
    header = Header(
        command=9,
        status=0xC0000022,
        flags=0x9,
        message_id=77,
        tree_id=5,
        session_id=0x1122334455667788,
        credit_charge=3,
        credit_request=12,
        next_command=128,
        signature=bytes(range(16)),
    )
    packed = pack_message(header, b"body")
    assert len(packed) == HEADER_SIZE + 4
    assert parse_header(packed) == header


def test_header_must_be_complete_and_marked():
    good = message()
    with pytest.raises(SmbFormatError):
        parse_header(good[: HEADER_SIZE - 1])
    with pytest.raises(SmbFormatError):
        parse_header(b"\xffSMB" + good[4:])
    wrong_size = good[:4] + struct.pack("<H", 65) + good[6:]
    with pytest.raises(SmbFormatError):
        parse_header(wrong_size)


def test_frame_has_a_four_byte_length_prefix():
    assert frame_message(b"abc") == b"\x00\x00\x00\x03abc"


def test_read_frame_returns_the_payload():
    assert read(frame_message(b"hello")) == b"hello"


def test_read_frame_skips_keep_alives():
    assert read(b"\x85\x00\x00\x00" + frame_message(b"x")) == b"x"


def test_read_frame_refuses_a_frame_over_the_limit():
    with pytest.raises(SmbFormatError):
        read(frame_message(b"x" * 100), limit=99)


def test_read_frame_refuses_other_netbios_types_and_empty_frames():
    with pytest.raises(SmbFormatError):
        read(b"\x81\x00\x00\x04abcd")
    with pytest.raises(SmbFormatError):
        read(b"\x00\x00\x00\x00")


def test_split_compound_returns_each_message():
    first = pack_message(Header(command=5, next_command=72), b"\x01" * 8)
    second = pack_message(Header(command=6, flags=FLAG_RELATED), b"\x02" * 8)
    parts = split_compound(first + second)
    assert [parse_header(part).command for part in parts] == [5, 6]
    assert parts[0] == first
    assert parts[1] == second


@pytest.mark.parametrize(
    "next_command",
    [1, 7, 8, 63, 64, 10_000],
    ids=["odd", "unaligned", "inside header", "short header", "no room", "past the frame"],
)
def test_split_compound_refuses_bad_offsets(next_command):
    first = pack_message(Header(command=5, next_command=next_command), b"\x01" * 8)
    with pytest.raises(SmbFormatError):
        split_compound(first + message())


def test_split_compound_refuses_a_chain_that_never_ends():
    chain = pack_message(Header(command=13, next_command=72), b"\x00" * 8) * 40
    with pytest.raises(SmbFormatError):
        split_compound(chain)


def smb1_negotiate(*dialects: bytes) -> bytes:
    body = b"".join(b"\x02" + name + b"\x00" for name in dialects)
    header = b"\xffSMB\x72" + b"\x00" * 27
    return header + b"\x00" + struct.pack("<H", len(body)) + body


def test_smb1_negotiate_lists_its_dialects():
    parsed = parse_smb1_negotiate(smb1_negotiate(b"NT LM 0.12", b"SMB 2.002", b"SMB 2.???"))
    assert parsed == Smb1Negotiate(
        dialects=("NT LM 0.12", "SMB 2.002", "SMB 2.???"),
        offers_smb2_wildcard=True,
        offers_smb2_002=True,
    )


def test_smb1_negotiate_without_smb2_offers_neither():
    parsed = parse_smb1_negotiate(smb1_negotiate(b"NT LM 0.12"))
    assert not parsed.offers_smb2_wildcard
    assert not parsed.offers_smb2_002


def test_smb1_negotiate_refuses_other_commands_and_cut_data():
    session_setup = b"\xffSMB\x73" + b"\x00" * 27 + b"\x00\x00\x00"
    with pytest.raises(SmbFormatError):
        parse_smb1_negotiate(session_setup)
    with pytest.raises(SmbFormatError):
        parse_smb1_negotiate(smb1_negotiate(b"NT LM 0.12")[:-3])
    with pytest.raises(SmbFormatError):
        parse_smb1_negotiate(b"\xffSMB\x72")


def test_smb1_negotiate_tolerates_an_unterminated_dialect_by_refusing_it():
    broken = b"\xffSMB\x72" + b"\x00" * 27 + b"\x00" + struct.pack("<H", 6) + b"\x02ABCDE"
    with pytest.raises(SmbFormatError):
        parse_smb1_negotiate(broken)


def test_random_bytes_never_escape_as_anything_but_a_format_error():
    generator = random.Random(1)  # noqa: S311 - seeded, repeatable
    for _ in range(2000):
        blob = generator.randbytes(generator.randrange(0, 200))
        for parser in (parse_header, split_compound, parse_smb1_negotiate):
            with contextlib.suppress(SmbFormatError):
                parser(blob)


def test_smb1_refusal_is_a_well_formed_negotiate_reply_without_a_dialect():
    reply = smb1_negotiate_refusal()
    assert reply[:5] == b"\xffSMB\x72"
    assert len(reply) == 32 + 1 + 2 + 2
    assert reply[32] == 1
    assert struct.unpack_from("<H", reply, 33)[0] == 0xFFFF
