"""PE images built byte by byte for the tests of the kernel's PDB id (no third-party library).

One section and a debug directory with the entries a kernel has, the CodeView one being the one
that matters. The real `ntoskrnl.exe` of the S3 guest has ntkrnlmp.pdb, GUID
24DE61DB3A27C5B383DFF181CB51F7E1, age 1 (read with pefile in docs/plans/m8-spikes/S3-findings.md).
"""

import struct
import uuid

GUID = "24DE61DB3A27C5B383DFF181CB51F7E1"
SECTION_RVA, SECTION_FILE_OFFSET = 0x2000, 0x400
DEBUG_DIRECTORY_OFFSET = 0x10
POGO, CODEVIEW = 13, 2
DEBUG_ENTRY = struct.Struct("<IIHHIIII")


def codeview(guid: str = GUID, age: int = 1, name: str = r"ntkrnlmp.pdb") -> bytes:
    return b"RSDS" + uuid.UUID(guid).bytes_le + struct.pack("<I", age) + name.encode() + b"\0"


def debug_entry(kind: int, data_offset: int, size: int) -> bytes:
    return DEBUG_ENTRY.pack(0, 0, 0, 0, kind, size, SECTION_RVA + 0x100, data_offset)


def pe_image(
    *,
    entries: tuple[tuple[int, bytes], ...] = ((POGO, b"PGU\0" * 4), (CODEVIEW, codeview())),
    pe32_plus: bool = True,
    debug_directory_size: int | None = None,
) -> bytes:
    """A PE with one section, whose debug directory lists `entries` (type, data), data after it."""
    optional_size = 240 if pe32_plus else 224
    optional = bytearray(optional_size)
    struct.pack_into("<H", optional, 0, 0x20B if pe32_plus else 0x10B)
    directories = 112 if pe32_plus else 96
    struct.pack_into("<I", optional, directories - 4, 16)
    entry_table = b""
    data = b""
    data_start = SECTION_FILE_OFFSET + DEBUG_DIRECTORY_OFFSET + DEBUG_ENTRY.size * len(entries)
    for kind, payload in entries:
        entry_table += debug_entry(kind, data_start + len(data), len(payload))
        data += payload
    size = DEBUG_ENTRY.size * len(entries) if debug_directory_size is None else debug_directory_size
    struct.pack_into(
        "<II", optional, directories + 6 * 8, SECTION_RVA + DEBUG_DIRECTORY_OFFSET, size
    )
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, optional_size, 0x22)
    section = struct.pack(
        "<8sIIIIIIHHI", b".rdata", 0x1000, SECTION_RVA, 0x1000, SECTION_FILE_OFFSET, 0, 0, 0, 0, 0
    )
    dos = bytearray(0x80)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    headers = bytes(dos) + b"PE\0\0" + coff + bytes(optional) + section
    padding = b"\0" * (SECTION_FILE_OFFSET - len(headers))
    body = b"\0" * DEBUG_DIRECTORY_OFFSET + entry_table + data
    return headers + padding + body + b"\0" * 64
