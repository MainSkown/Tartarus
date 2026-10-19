#!/usr/bin/python3
"""Reads the PDB name, GUID and age out of a PE image's debug directory: `pdb_id.py FILE`.

The symbol server and Volatility3 find a kernel's symbols by exactly these three. The file is the
guest's own `ntoskrnl.exe`, which is the guest's data and so read defensively: every offset is
checked against the file and nothing it says is trusted past its size. Only the standard library is
used, because the steps run in the image's system python, which has no pefile.

Prints `<pdb name> <GUID, 32 upper-case hex digits> <age, decimal>` on one line, or the reason on
stderr and exit status 1.
"""

import re
import struct
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

DOS_MAGIC = b"MZ"
PE_SIGNATURE = b"PE\0\0"
PE32_MAGIC, PE32_PLUS_MAGIC = 0x10B, 0x20B
DATA_DIRECTORIES_OFFSET = {PE32_MAGIC: 96, PE32_PLUS_MAGIC: 112}
DEBUG_DIRECTORY_INDEX = 6
SIZE_OF_HEADERS_OFFSET = 60
SECTION_HEADER_SIZE = 40
DEBUG_ENTRY_SIZE = 28
DEBUG_TYPE_CODEVIEW = 2
RSDS = b"RSDS"
MAX_NAME_BYTES = 260
PDB_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class PdbIdError(Exception):
    """The image has no readable PDB id; the message says why."""


@dataclass(frozen=True)
class PdbId:
    name: str
    guid: str
    age: int


@dataclass(frozen=True)
class Section:
    virtual_address: int
    extent: int
    file_offset: int


def read_pdb_id(image: bytes) -> PdbId:
    if image[:2] != DOS_MAGIC:
        raise PdbIdError("not a PE image")
    try:
        return _read(image)
    except struct.error as cut:
        raise PdbIdError("the image is truncated") from cut


def _read(image: bytes) -> PdbId:
    (pe_offset,) = struct.unpack_from("<I", image, 0x3C)
    (signature,) = struct.unpack_from("<4s", image, pe_offset)
    if signature != PE_SIGNATURE:
        raise PdbIdError("not a PE image")
    section_count, optional_size = struct.unpack_from("<2xH12xH", image, pe_offset + 4)
    optional = pe_offset + 4 + 20
    (magic,) = struct.unpack_from("<H", image, optional)
    if magic not in DATA_DIRECTORIES_OFFSET:
        raise PdbIdError("not a PE image")
    directories = optional + DATA_DIRECTORIES_OFFSET[magic]
    (header_size,) = struct.unpack_from("<I", image, optional + SIZE_OF_HEADERS_OFFSET)
    (directory_count,) = struct.unpack_from("<I", image, directories - 4)
    if directory_count <= DEBUG_DIRECTORY_INDEX:
        raise PdbIdError("the image has no debug directory")
    rva, size = struct.unpack_from("<II", image, directories + DEBUG_DIRECTORY_INDEX * 8)
    if size == 0:
        raise PdbIdError("the image has no debug directory")
    sections = _sections(image, optional + optional_size, section_count)
    start = _file_offset(rva, sections, header_size)
    if start + size > len(image):
        raise PdbIdError("the image is truncated")
    for index in range(size // DEBUG_ENTRY_SIZE):
        kind, data_size, data_offset = _debug_entry(image, start + index * DEBUG_ENTRY_SIZE)
        if kind == DEBUG_TYPE_CODEVIEW and image[data_offset : data_offset + 4] == RSDS:
            return _codeview(image, data_offset, data_size)
    raise PdbIdError("the image has no CodeView debug entry")


def _sections(image: bytes, table: int, count: int) -> list[Section]:
    sections = []
    for index in range(count):
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<4xIIII", image, table + index * SECTION_HEADER_SIZE + 4
        )
        sections.append(Section(virtual_address, max(virtual_size, raw_size), raw_offset))
    return sections


def _file_offset(rva: int, sections: list[Section], header_size: int) -> int:
    if rva < header_size:
        return rva
    for section in sections:
        if section.virtual_address <= rva < section.virtual_address + section.extent:
            return rva - section.virtual_address + section.file_offset
    raise PdbIdError("the debug directory is not inside any section of the image")


def _debug_entry(image: bytes, offset: int) -> tuple[int, int, int]:
    kind, data_size, _address, data_offset = struct.unpack_from("<12xIIII", image, offset)
    return kind, data_size, data_offset


def _codeview(image: bytes, offset: int, size: int) -> PdbId:
    raw_guid, age = struct.unpack_from("<16sI", image, offset + len(RSDS))
    name_start = offset + len(RSDS) + 20
    name_end = min(name_start + MAX_NAME_BYTES, offset + max(size, 0), len(image))
    raw_name = image[name_start:name_end].split(b"\0", 1)[0]
    name = raw_name.decode("ascii", errors="replace").rsplit("\\", 1)[-1]
    if not PDB_NAME.fullmatch(name):
        raise PdbIdError("the PDB name in the image is not a plain file name")
    return PdbId(name, uuid.UUID(bytes_le=raw_guid).hex.upper(), age)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: pdb_id.py FILE\n")
        return 2
    try:
        found = read_pdb_id(Path(argv[0]).read_bytes())
    except OSError as unreadable:
        sys.stderr.write(f"cannot read the image ({unreadable.strerror})\n")
        return 1
    except PdbIdError as unreadable_image:
        sys.stderr.write(f"{unreadable_image}\n")
        return 1
    sys.stdout.write(f"{found.name} {found.guid} {found.age}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
