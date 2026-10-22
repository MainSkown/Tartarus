import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.imports.packet_capture import MAX_LEADING_BLOCKS, UnreadableCaptureError, first_packet_time

FIXTURES = Path(__file__).resolve().parents[3] / "docs" / "plans" / "m9-spikes" / "fixtures"
FIXTURE_FIRST_PACKET = datetime(2026, 10, 21, 12, 52, 52, 871033, tzinfo=UTC)
MOMENT = datetime(2026, 10, 21, 12, 52, 52, 871033, tzinfo=UTC)
EPOCH_SECONDS = int(MOMENT.timestamp())

PCAPNG_SECTION_ORDER_MAGIC = 0x1A2B3C4D


def classic(magic: bytes, order: str, fraction: int, *, packets: int = 1) -> bytes:
    header = magic + struct.pack(f"{order}HHiIII", 2, 4, 0, 0, 65535, 1)
    record = struct.pack(f"{order}IIII", EPOCH_SECONDS, fraction, 4, 4) + b"\x00" * 4
    return header + record * packets


def block(order: str, kind: int, body: bytes) -> bytes:
    padded = body + b"\x00" * (-len(body) % 4)
    total = 12 + len(padded)
    return struct.pack(f"{order}II", kind, total) + padded + struct.pack(f"{order}I", total)


def section_header(order: str) -> bytes:
    return block(
        order, 0x0A0D0D0A, struct.pack(f"{order}IHHq", PCAPNG_SECTION_ORDER_MAGIC, 1, 0, -1)
    )


def interface(order: str, resolution_option: int | None = None) -> bytes:
    options = b""
    if resolution_option is not None:
        options = struct.pack(f"{order}HH", 9, 1) + bytes([resolution_option]) + b"\x00" * 3
        options += struct.pack(f"{order}HH", 0, 0)
    return block(order, 1, struct.pack(f"{order}HHI", 1, 0, 65535) + options)


def enhanced_packet(order: str, ticks: int) -> bytes:
    body = struct.pack(f"{order}IIIII", 0, ticks >> 32, ticks & 0xFFFFFFFF, 4, 4) + b"\x00" * 4
    return block(order, 6, body)


def write(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "upload"
    path.write_bytes(content)
    return path


def test_the_p1_fixture_starts_at_its_first_packet() -> None:
    assert first_packet_time(FIXTURES / "p9-run-370-dump.pcap") == FIXTURE_FIRST_PACKET


@pytest.mark.parametrize(
    ("magic", "order", "fraction", "expected_microsecond"),
    [
        (bytes.fromhex("d4c3b2a1"), "<", 871033, 871033),
        (bytes.fromhex("a1b2c3d4"), ">", 871033, 871033),
        (bytes.fromhex("4d3cb2a1"), "<", 871033000, 871033),
        (bytes.fromhex("a1b23c4d"), ">", 871033000, 871033),
    ],
)
def test_classic_pcap_in_each_byte_order_and_resolution(
    tmp_path: Path, magic: bytes, order: str, fraction: int, expected_microsecond: int
) -> None:
    started = first_packet_time(write(tmp_path, classic(magic, order, fraction, packets=2)))

    assert started == MOMENT.replace(microsecond=expected_microsecond)


@pytest.mark.parametrize("order", ["<", ">"])
def test_pcapng_defaults_to_microsecond_ticks(tmp_path: Path, order: str) -> None:
    ticks = EPOCH_SECONDS * 1_000_000 + 871033
    content = section_header(order) + interface(order) + enhanced_packet(order, ticks)

    assert first_packet_time(write(tmp_path, content)) == MOMENT


def test_pcapng_honours_the_interface_timestamp_resolution(tmp_path: Path) -> None:
    nanoseconds = EPOCH_SECONDS * 1_000_000_000 + 871033000
    content = section_header("<") + interface("<", resolution_option=9)
    content += enhanced_packet("<", nanoseconds)

    assert first_packet_time(write(tmp_path, content)) == MOMENT


def test_pcapng_skips_blocks_that_carry_no_packet_before_the_first_one(tmp_path: Path) -> None:
    statistics = block("<", 5, struct.pack("<III", 0, 0, 0))
    ticks = EPOCH_SECONDS * 1_000_000 + 871033
    content = section_header("<") + interface("<") + statistics + enhanced_packet("<", ticks)

    assert first_packet_time(write(tmp_path, content)) == MOMENT


def test_pcapng_gives_up_after_the_leading_blocks_the_walk_allows(tmp_path: Path) -> None:
    filler = block("<", 5, struct.pack("<III", 0, 0, 0))
    ticks = EPOCH_SECONDS * 1_000_000 + 871033
    content = section_header("<") + filler * MAX_LEADING_BLOCKS + enhanced_packet("<", ticks)

    with pytest.raises(UnreadableCaptureError, match="no packet"):
        first_packet_time(write(tmp_path, content))


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", "not a packet capture"),
        (b"just some text, not a capture", "not a packet capture"),
        (classic(bytes.fromhex("d4c3b2a1"), "<", 0, packets=0), "no packets"),
        (classic(bytes.fromhex("d4c3b2a1"), "<", 0)[:30], "no packets"),
        (section_header("<") + interface("<"), "no packets"),
        (section_header("<")[:10], "no packets"),
    ],
)
def test_a_file_with_no_first_packet_is_refused_with_a_reason(
    tmp_path: Path, content: bytes, reason: str
) -> None:
    with pytest.raises(UnreadableCaptureError, match=reason):
        first_packet_time(write(tmp_path, content))
