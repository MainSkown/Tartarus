"""The information classes a Windows client asks for: file, file system and directory entries."""

import fnmatch
import struct
from collections.abc import Sequence
from typing import NamedTuple

from lan_sim.services.smb_store import Node

ATTRIBUTE_DIRECTORY = 0x10
ATTRIBUTE_ARCHIVE = 0x20
ALLOCATION_UNIT = 4096
SECTOR_BYTES = 512
TOTAL_UNITS = 25_000_000
FREE_UNITS = 18_000_000
ENTRY_ALIGNMENT = 8
FILE_ALL_ACCESS = 0x001F01FF
FILE_DEVICE_DISK = 7
FILE_CASE_PRESERVED_AND_UNICODE_AND_ACLS = 0x0000000F | 0x00000100
MAX_COMPONENT_NAME = 255
PATTERN_LIMIT = 255

FILE_BASIC, FILE_STANDARD, FILE_INTERNAL, FILE_EA, FILE_ACCESS = 4, 5, 6, 7, 8
FILE_NAME, FILE_POSITION, FILE_MODE, FILE_ALIGNMENT, FILE_ALL = 9, 14, 16, 17, 18
FILE_STREAM, FILE_NETWORK_OPEN, FILE_ATTRIBUTE_TAG = 22, 34, 35
FS_VOLUME, FS_SIZE, FS_DEVICE, FS_ATTRIBUTE, FS_FULL_SIZE = 1, 3, 4, 5, 7
DIR_DIRECTORY, DIR_FULL, DIR_BOTH, DIR_NAMES = 1, 2, 3, 12
DIR_ID_BOTH, DIR_ID_FULL = 37, 38
INFO_FILE, INFO_FILESYSTEM = 1, 2

_VOLUME_SERIAL = 0x5E1A0C3D
_VOLUME_LABEL = "System"
_FS_NAME = "NTFS"
NAME_ELEMENT_OFFSETS = {
    DIR_DIRECTORY: 64,
    DIR_FULL: 68,
    DIR_BOTH: 94,
    DIR_NAMES: 12,
    DIR_ID_BOTH: 104,
    DIR_ID_FULL: 80,
}


class DirectoryEntry(NamedTuple):
    name: str
    node: Node


def attributes_of(node: Node) -> int:
    return ATTRIBUTE_DIRECTORY if node.is_dir else ATTRIBUTE_ARCHIVE


def size_of(node: Node) -> int:
    return 0 if node.is_dir else len(node.data)


def allocation_of(node: Node) -> int:
    return -size_of(node) // ALLOCATION_UNIT * -ALLOCATION_UNIT


def times_of(node: Node) -> tuple[int, int, int, int]:
    return (node.created, node.modified, node.modified, node.modified)


def file_info(info_class: int, node: Node, path: str, file_number: int) -> bytes | None:
    """The FILE_*_INFORMATION structure for `info_class`, or None when it is not supported."""
    builders = {
        FILE_BASIC: lambda: _basic(node),
        FILE_STANDARD: lambda: _standard(node),
        FILE_INTERNAL: lambda: struct.pack("<Q", file_number),
        FILE_EA: lambda: struct.pack("<I", 0),
        FILE_ACCESS: lambda: struct.pack("<I", FILE_ALL_ACCESS),
        FILE_POSITION: lambda: struct.pack("<Q", 0),
        FILE_MODE: lambda: struct.pack("<I", 0),
        FILE_ALIGNMENT: lambda: struct.pack("<I", 0),
        FILE_NAME: lambda: _name_info(path),
        FILE_NETWORK_OPEN: lambda: _network_open(node),
        FILE_ATTRIBUTE_TAG: lambda: struct.pack("<II", attributes_of(node), 0),
        FILE_STREAM: lambda: _streams(node),
        FILE_ALL: lambda: _all(node, path, file_number),
    }
    build = builders.get(info_class)
    return build() if build else None


def filesystem_info(info_class: int) -> bytes | None:
    label = _VOLUME_LABEL.encode("utf-16le")
    name = _FS_NAME.encode("utf-16le")
    builders = {
        FS_VOLUME: lambda: struct.pack("<QIIBB", 0, _VOLUME_SERIAL, len(label), 0, 0) + label,
        FS_SIZE: lambda: struct.pack("<QQII", TOTAL_UNITS, FREE_UNITS, 8, SECTOR_BYTES),
        FS_DEVICE: lambda: struct.pack("<II", FILE_DEVICE_DISK, 0x20),
        FS_ATTRIBUTE: lambda: (
            struct.pack(
                "<III", FILE_CASE_PRESERVED_AND_UNICODE_AND_ACLS, MAX_COMPONENT_NAME, len(name)
            )
            + name
        ),
        FS_FULL_SIZE: lambda: struct.pack(
            "<QQQII", TOTAL_UNITS, FREE_UNITS, FREE_UNITS, 8, SECTOR_BYTES
        ),
    }
    build = builders.get(info_class)
    return build() if build else None


def matches(pattern: str, name: str) -> bool:
    """DOS wildcard matching, case-insensitive; `*` and an empty pattern match everything."""
    if len(pattern) > PATTERN_LIMIT:
        return False
    translated = pattern.replace("<", "*").replace(">", "?").replace('"', ".")
    if translated in ("", "*"):
        return True
    return fnmatch.fnmatchcase(name.casefold(), translated.casefold())


def pack_directory_entries(
    info_class: int, entries: Sequence[DirectoryEntry], limit: int
) -> tuple[bytes, int]:
    """As many entries as fit in `limit` bytes; the bytes and how many were used."""
    packed: list[bytes] = []
    used = 0
    for index, entry in enumerate(entries):
        raw = _directory_entry(info_class, entry, index)
        padded = raw + bytes(-len(raw) % ENTRY_ALIGNMENT)
        if used + len(padded) > limit:
            break
        packed.append(padded)
        used += len(padded)
    if not packed:
        return b"", 0
    chained = [struct.pack("<I", len(part)) + part[4:] for part in packed[:-1]] + [packed[-1]]
    return b"".join(chained), len(packed)


def _basic(node: Node) -> bytes:
    return struct.pack("<4QII", *times_of(node), attributes_of(node), 0)


def _standard(node: Node) -> bytes:
    return struct.pack("<QQIBBH", allocation_of(node), size_of(node), 1, 0, int(node.is_dir), 0)


def _name_info(path: str) -> bytes:
    name = ("\\" + path).encode("utf-16le")
    return struct.pack("<I", len(name)) + name


def _network_open(node: Node) -> bytes:
    return struct.pack(
        "<4QQQII", *times_of(node), allocation_of(node), size_of(node), attributes_of(node), 0
    )


def _streams(node: Node) -> bytes:
    if node.is_dir:
        return b""
    name = "::$DATA".encode("utf-16le")
    return struct.pack("<IIQQ", 0, len(name), size_of(node), allocation_of(node)) + name


def _all(node: Node, path: str, file_number: int) -> bytes:
    return (
        _basic(node)
        + _standard(node)
        + struct.pack("<Q", file_number)
        + struct.pack("<II", 0, FILE_ALL_ACCESS)
        + struct.pack("<QII", 0, 0, 0)
        + _name_info(path)
    )


def _directory_entry(info_class: int, entry: DirectoryEntry, index: int) -> bytes:
    node = entry.node
    name = entry.name.encode("utf-16le")
    created, accessed, written, changed = times_of(node)
    if info_class == DIR_NAMES:
        return struct.pack("<III", 0, index, len(name)) + name
    head = struct.pack(
        "<II4QQQII",
        0,
        index,
        created,
        accessed,
        written,
        changed,
        size_of(node),
        allocation_of(node),
        attributes_of(node),
        len(name),
    )
    tail = {
        DIR_DIRECTORY: b"",
        DIR_FULL: struct.pack("<I", 0),
        DIR_BOTH: struct.pack("<IBB24s", 0, 0, 0, bytes(24)),
        DIR_ID_BOTH: struct.pack("<IBB24sHQ", 0, 0, 0, bytes(24), 0, index + 1),
        DIR_ID_FULL: struct.pack("<IIQ", 0, 0, index + 1),
    }[info_class]
    return head + tail + name


def supports_directory_class(info_class: int) -> bool:
    return info_class in NAME_ELEMENT_OFFSETS
