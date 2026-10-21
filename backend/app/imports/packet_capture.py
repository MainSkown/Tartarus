"""The first packet's time of a classic PCAP or a pcapng file, read from its first bytes."""

import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from app.imports.sniff import ImportKind, sniff_import

_MICROSECONDS = 1_000_000
_NANOSECOND_MAGICS = (bytes.fromhex("a1b23c4d"), bytes.fromhex("4d3cb2a1"))
_LITTLE_ENDIAN_MAGICS = (bytes.fromhex("d4c3b2a1"), bytes.fromhex("4d3cb2a1"))
_CLASSIC_HEADER_SIZE = 24
_BLOCK_HEADER_SIZE = 8
_SECTION_HEADER = 0x0A0D0D0A
_LITTLE_ENDIAN_SECTION_MAGIC = bytes.fromhex("4d3c2b1a")
_INTERFACE_DESCRIPTION = 0x00000001
_ENHANCED_PACKET = 0x00000006
_OPTION_END = 0
_OPTION_TIMESTAMP_RESOLUTION = 9
_DEFAULT_TICKS_PER_SECOND = _MICROSECONDS
# A section header and the interface blocks before the first packet are small; a larger block
# before it is not a capture worth importing.
_MAX_LEADING_BLOCK = 1 << 20
_NO_PACKETS = "The capture holds no packets"


class UnreadableCaptureError(Exception):
    """The file is not a capture or holds no packet; the message says which."""


def first_packet_time(path: Path) -> datetime:
    with path.open("rb") as stream:
        head = stream.read(_BLOCK_HEADER_SIZE)
        stream.seek(0)
        match sniff_import(head):
            case ImportKind.PCAP:
                return _classic_first_packet(stream)
            case ImportKind.PCAPNG:
                return _pcapng_first_packet(stream)
            case _:
                raise UnreadableCaptureError("The file is not a packet capture")


def _classic_first_packet(stream: BinaryIO) -> datetime:
    magic = stream.read(4)
    order = "<" if magic in _LITTLE_ENDIAN_MAGICS else ">"
    ticks_per_second = 1_000_000_000 if magic in _NANOSECOND_MAGICS else _MICROSECONDS
    stream.seek(_CLASSIC_HEADER_SIZE)
    record = stream.read(8)
    if len(record) < 8:  # noqa: PLR2004 - seconds and fraction, two 32-bit fields
        raise UnreadableCaptureError(_NO_PACKETS)
    seconds, fraction = struct.unpack(f"{order}II", record)
    return _moment(seconds * ticks_per_second + fraction, ticks_per_second)


def _pcapng_first_packet(stream: BinaryIO) -> datetime:
    order = "<"
    ticks_per_second: list[int] = []
    while len(header := stream.read(_BLOCK_HEADER_SIZE)) == _BLOCK_HEADER_SIZE:
        if header[:4] == struct.pack(">I", _SECTION_HEADER):
            order = _section_byte_order(stream)
            ticks_per_second = []
            stream.seek(-4, 1)
        kind, length = struct.unpack(f"{order}II", header)
        if length < _BLOCK_HEADER_SIZE + 4 or length > _MAX_LEADING_BLOCK:
            break
        body = stream.read(length - _BLOCK_HEADER_SIZE - 4)
        stream.read(4)
        if kind == _INTERFACE_DESCRIPTION:
            ticks_per_second.append(_interface_ticks_per_second(body, order))
        elif kind == _ENHANCED_PACKET:
            return _enhanced_packet_time(body, order, ticks_per_second)
    raise UnreadableCaptureError(_NO_PACKETS)


def _section_byte_order(stream: BinaryIO) -> str:
    byte_order_magic = stream.read(4)
    return "<" if byte_order_magic == _LITTLE_ENDIAN_SECTION_MAGIC else ">"


def _interface_ticks_per_second(body: bytes, order: str) -> int:
    options = body[8:]
    while len(options) >= 4:  # noqa: PLR2004 - an option header is a code and a length, 16 bits each
        code, length = struct.unpack(f"{order}HH", options[:4])
        if code == _OPTION_END:
            break
        if code == _OPTION_TIMESTAMP_RESOLUTION and length == 1 and len(options) > 4:  # noqa: PLR2004
            return _ticks_of(options[4])
        options = options[4 + length + (-length % 4) :]
    return _DEFAULT_TICKS_PER_SECOND


def _ticks_of(resolution: int) -> int:
    exponent = resolution & 0x7F
    return 1 << exponent if resolution & 0x80 else 10**exponent


def _enhanced_packet_time(body: bytes, order: str, ticks_per_second: list[int]) -> datetime:
    if len(body) < 12:  # noqa: PLR2004 - interface id and the two timestamp halves
        raise UnreadableCaptureError(_NO_PACKETS)
    interface, high, low = struct.unpack(f"{order}III", body[:12])
    rate = ticks_per_second[interface] if interface < len(ticks_per_second) else _MICROSECONDS
    return _moment((high << 32) | low, rate)


def _moment(ticks: int, ticks_per_second: int) -> datetime:
    seconds, remainder = divmod(ticks, ticks_per_second)
    try:
        return datetime.fromtimestamp(seconds, UTC).replace(
            microsecond=remainder * _MICROSECONDS // ticks_per_second
        )
    except (OverflowError, OSError, ValueError):
        raise UnreadableCaptureError("The first packet has no valid time") from None
