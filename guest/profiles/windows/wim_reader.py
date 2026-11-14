"""Reads the metadata of a Windows install image straight out of a disc image.

Run by the guest engine's media scan inside its short-lived, unprivileged child process, which has
the disc open (the inspector hands this file to `context.read_inside`). The disc is untrusted, so
every size and offset below is checked against the file before it is used. Format: wimlib's
`wim_native.h`; the XML data resource describes every image.

Only the standard library may be imported here: the child is started with `python3 -I`.
"""

import struct
from typing import Any, BinaryIO
from xml.etree import ElementTree

INSTALL_IMAGES = ("install.wim", "install.esd")
BOOT_IMAGE = "boot.wim"

HEADER_SIZE = 208
MAGIC = b"MSWIM\x00\x00\x00"
IMAGE_COUNT_OFFSET = 44
XML_RESOURCE_OFFSET = 72
MAX_XML_BYTES = 4 << 20

HEADER_FLAG_COMPRESSION = 0x2
HEADER_FLAG_XPRESS = 0x20000
HEADER_FLAG_LZX = 0x40000
HEADER_FLAG_LZMS = 0x80000
HEADER_FLAG_XPRESS2 = 0x200000
COMPRESSION_BY_FLAG = (
    (HEADER_FLAG_XPRESS | HEADER_FLAG_XPRESS2, "XPRESS"),
    (HEADER_FLAG_LZX, "LZX"),
    (HEADER_FLAG_LZMS, "LZMS"),
)

RESOURCE_FLAG_COMPRESSED = 0x04
RESOURCE_FLAG_SOLID = 0x10
STORED_SIZE_MASK = (1 << 56) - 1

# What Windows' answer file calls the numbers of `<ARCH>`.
ARCHITECTURES = {0: "x86", 5: "arm", 6: "ia64", 9: "amd64", 12: "arm64"}

# The failure codes the inspector turns into messages: the file is not a WIM, it ends too soon
# (still being copied), it contradicts itself, or its XML is stored in a way this reader declines.
NOT_A_WIM = "not_a_wim"
INCOMPLETE = "incomplete"
DAMAGED = "damaged"
UNREADABLE = "unreadable"


class ImageFailure(Exception):  # noqa: N818 - a code for the inspector, not a program error
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def read(image: Any) -> dict[str, Any]:
    """Describes the install image of the disc: `{file, compression, images}`, `{file, failure}`
    when it cannot be read, or `{file: None, boot_wim}` when the disc has none."""
    for name in INSTALL_IMAGES:
        found = image.open("sources", name)
        if found is not None:
            return {"file": name, **_describe(found)}
    return {"file": None, "boot_wim": image.exists("sources", BOOT_IMAGE)}


def _describe(wim: BinaryIO) -> dict[str, Any]:
    try:
        header = _read_header(wim)
        return {
            "compression": _compression(header),
            "images": images_from_xml(_read_xml(wim, header)),
        }
    except ImageFailure as failure:
        return {"failure": failure.code}


def _read_header(wim: BinaryIO) -> bytes:
    header = wim.read(HEADER_SIZE)
    if header[: len(MAGIC)] != MAGIC:
        raise ImageFailure(NOT_A_WIM)
    if len(header) < HEADER_SIZE:
        raise ImageFailure(INCOMPLETE)
    (declared_size,) = struct.unpack_from("<I", header, 8)
    if declared_size != HEADER_SIZE:
        raise ImageFailure(NOT_A_WIM)
    return header


def _compression(header: bytes) -> str:
    (flags,) = struct.unpack_from("<I", header, 16)
    if not flags & HEADER_FLAG_COMPRESSION:
        return "None"
    return next((name for bit, name in COMPRESSION_BY_FLAG if flags & bit), "None")


def _read_xml(wim: BinaryIO, header: bytes) -> str:
    packed, offset, original_size = struct.unpack_from("<QQQ", header, XML_RESOURCE_OFFSET)
    size, flags = packed & STORED_SIZE_MASK, packed >> 56
    if flags & (RESOURCE_FLAG_COMPRESSED | RESOURCE_FLAG_SOLID):
        raise ImageFailure(UNREADABLE)
    if not 0 < size <= MAX_XML_BYTES or size != original_size:
        raise ImageFailure(DAMAGED)
    if offset + size > wim.seek(0, 2):
        raise ImageFailure(INCOMPLETE)
    wim.seek(offset)
    data = wim.read(size)
    if len(data) != size:
        raise ImageFailure(INCOMPLETE)
    return _decode_utf16(data)


def _decode_utf16(data: bytes) -> str:
    try:
        return data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-16-le")
    except UnicodeDecodeError:
        raise ImageFailure(DAMAGED) from None


def images_from_xml(text: str) -> list[dict[str, Any]]:
    """The `<IMAGE>` elements of the WIM's XML data, with the fields the inspector lists."""
    # XML is case-sensitive, but a reader that stays out of declarations altogether has no
    # entity expansion to worry about, so any spelling is refused.
    if "<!doctype" in text.lower() or "<!entity" in text.lower():
        raise ImageFailure(DAMAGED)
    try:
        # Declarations are refused above and the size is capped, so no entity can expand.
        root = ElementTree.fromstring(text)  # noqa: S314
        return [_image(element) for element in root.iterfind("IMAGE")]
    except (ElementTree.ParseError, ValueError):
        raise ImageFailure(DAMAGED) from None


def _image(element: ElementTree.Element) -> dict[str, Any]:
    windows = element.find("WINDOWS")
    if windows is None:
        windows = ElementTree.Element("WINDOWS")
    major, minor, build = (
        _text(windows, f"VERSION/{part}") for part in ("MAJOR", "MINOR", "BUILD")
    )
    return {
        "index": int(element.get("INDEX", "")),
        "name": _text(element, "NAME"),
        "edition_id": _text(windows, "EDITIONID"),
        "arch": _architecture(_text(windows, "ARCH")),
        "languages": [language.text or "" for language in windows.iterfind("LANGUAGES/LANGUAGE")],
        "default_language": _text(windows, "LANGUAGES/DEFAULT"),
        "build": int(build) if build else None,
        "version": f"{major}.{minor}.{build}" if major and minor and build else None,
        "installation_type": _text(windows, "INSTALLATIONTYPE"),
    }


def _text(parent: ElementTree.Element, path: str) -> str | None:
    found = parent.findtext(path)
    return found.strip() if found is not None else None


def _architecture(code: str | None) -> str | None:
    if code is None:
        return None
    number = int(code)
    return ARCHITECTURES.get(number, f"unknown ({number})")
