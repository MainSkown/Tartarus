from pathlib import Path

from app.imports.sniff import ImportKind, sniff_import

FIXTURES = Path(__file__).resolve().parents[3] / "docs" / "history" / "m9-spikes" / "fixtures"


def test_classic_pcap_fixture_is_pcap() -> None:
    head = (FIXTURES / "p9-run-370-dump.pcap").read_bytes()[:24]

    assert sniff_import(head) is ImportKind.PCAP


def test_pcap_magics_in_both_byte_orders_and_timestamp_resolutions_are_pcap() -> None:
    for magic in (
        bytes.fromhex("a1b2c3d4"),
        bytes.fromhex("d4c3b2a1"),
        bytes.fromhex("a1b23c4d"),
        bytes.fromhex("4d3cb2a1"),
    ):
        assert sniff_import(magic + b"\x02\x00\x04\x00" + b"\x00" * 16) is ImportKind.PCAP


def test_pcapng_section_header_is_pcapng() -> None:
    section_header = bytes.fromhex("0a0d0d0a") + b"\x1c\x00\x00\x00" + b"\x4d\x3c\x2b\x1a"

    assert sniff_import(section_header) is ImportKind.PCAPNG


def test_elf_core_is_memory_image() -> None:
    elf_core = b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 9 + b"\x04\x00"

    assert sniff_import(elf_core) is ImportKind.MEMORY_IMAGE


def test_windows_crash_dump_64_bit_is_memory_image() -> None:
    assert sniff_import(b"PAGEDU64" + b"\x00" * 24) is ImportKind.MEMORY_IMAGE


def test_windows_crash_dump_32_bit_is_memory_image() -> None:
    assert sniff_import(b"PAGEDUMP" + b"\x00" * 24) is ImportKind.MEMORY_IMAGE


def test_garbage_is_unsupported() -> None:
    assert sniff_import(b"this is not a capture at all") is ImportKind.UNSUPPORTED


def test_raw_memory_image_without_magic_is_unsupported() -> None:
    assert sniff_import(bytes(range(256))) is ImportKind.UNSUPPORTED


def test_empty_head_is_unsupported() -> None:
    assert sniff_import(b"") is ImportKind.UNSUPPORTED


def test_truncated_magic_is_unsupported() -> None:
    assert sniff_import(b"\x7fEL") is ImportKind.UNSUPPORTED
