"""Tiny disc images and Windows images for the media tests, built with pycdlib itself."""

import io
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pycdlib

WIM_MAGIC = b"MSWIM\x00\x00\x00"
WIM_HEADER_SIZE = 208
HEADER_FLAG_COMPRESSION = 0x2
HEADER_FLAG_LZX = 0x40000
RESOURCE_FLAG_METADATA = 0x02
RESOURCE_FLAG_COMPRESSED = 0x04


def disc_image(path: Path, files: Mapping[str, bytes], filesystem: str = "udf") -> Path:
    """Writes an ISO whose tree holds `files` (relative paths, `/` separated) and returns `path`.

    `filesystem` is "udf" (ISO 9660 plus UDF, as Microsoft's images are), "joliet" or "iso9660".
    """
    iso = pycdlib.PyCdlib()
    options: dict[str, Any] = {"interchange_level": 3}
    if filesystem == "udf":
        options["udf"] = "2.60"
    if filesystem == "joliet":
        options["joliet"] = 3
    iso.new(**options)
    made: set[str] = set()
    for name, content in files.items():
        parts = name.split("/")
        for depth in range(1, len(parts)):
            directory = "/".join(parts[:depth])
            if directory not in made:
                made.add(directory)
                iso.add_directory(**_paths("/" + directory, filesystem, file=False))
        iso.add_fp(io.BytesIO(content), len(content), **_paths("/" + name, filesystem, file=True))
    iso.write(str(path))
    iso.close()
    return path


def _paths(path: str, filesystem: str, *, file: bool) -> dict[str, str]:
    iso_path = path.upper() + (";1" if file else "")
    if filesystem == "udf":
        return {"iso_path": iso_path, "udf_path": path}
    if filesystem == "joliet":
        return {"iso_path": iso_path, "joliet_path": path}
    return {"iso_path": iso_path}


def windows_image_xml(*images: Mapping[str, Any]) -> str:
    """The XML data of a WIM with one `<IMAGE>` per mapping; the keys it understands are those of
    `WINDOWS_PRO` and every one is optional."""
    return (
        "<WIM><TOTALBYTES>1</TOTALBYTES>"
        + "".join(_image_xml(image) for image in images)
        + "</WIM>"
    )


def _image_xml(image: Mapping[str, Any]) -> str:
    languages = "".join(f"<LANGUAGE>{code}</LANGUAGE>" for code in image.get("languages", ()))
    default = image.get("default_language")
    if default:
        languages += f"<DEFAULT>{default}</DEFAULT>"
    version = "".join(
        f"<{tag}>{image[key]}</{tag}>"
        for key, tag in (("major", "MAJOR"), ("minor", "MINOR"), ("build", "BUILD"))
        if key in image
    )
    windows = "".join(
        f"<{tag}>{image[key]}</{tag}>"
        for key, tag in (
            ("arch", "ARCH"),
            ("edition_id", "EDITIONID"),
            ("installation_type", "INSTALLATIONTYPE"),
        )
        if key in image
    )
    windows += f"<LANGUAGES>{languages}</LANGUAGES><VERSION>{version}</VERSION>"
    name = f"<NAME>{image['name']}</NAME>" if "name" in image else ""
    return f'<IMAGE INDEX="{image["index"]}"><WINDOWS>{windows}</WINDOWS>{name}</IMAGE>'


WINDOWS_PRO: dict[str, Any] = {
    "index": 1,
    "name": "Windows 11 Pro",
    "arch": 9,
    "edition_id": "Professional",
    "installation_type": "Client",
    "major": 10,
    "minor": 0,
    "build": 26200,
    "languages": ["pl-PL"],
    "default_language": "pl-PL",
}
WINDOWS_HOME = {**WINDOWS_PRO, "index": 2, "name": "Windows 11 Home", "edition_id": "Core"}


def wim_file(  # noqa: PLR0913 - one keyword per header field a test may falsify
    xml: str | bytes,
    *,
    header_flags: int = HEADER_FLAG_COMPRESSION | HEADER_FLAG_LZX,
    resource_flags: int = RESOURCE_FLAG_METADATA,
    image_count: int = 1,
    xml_offset: int | None = None,
    stored_size: int | None = None,
    original_size: int | None = None,
) -> bytes:
    """A WIM that is only its 208-byte header and the XML data behind it, which is all the
    scan reads. The keyword arguments let a test lie in one header field."""
    data = xml if isinstance(xml, bytes) else b"\xff\xfe" + xml.encode("utf-16-le")
    offset = WIM_HEADER_SIZE if xml_offset is None else xml_offset
    stored = len(data) if stored_size is None else stored_size
    original = len(data) if original_size is None else original_size
    header = bytearray(WIM_HEADER_SIZE)
    struct.pack_into("<8sIIII", header, 0, WIM_MAGIC, WIM_HEADER_SIZE, 0x10D00, header_flags, 32768)
    struct.pack_into("<HHI", header, 40, 1, 1, image_count)
    struct.pack_into("<QQQ", header, 72, stored | resource_flags << 56, offset, original)
    return bytes(header) + data


def windows_media(path: Path, wim: bytes, *, name: str = "install.wim", **kwargs: Any) -> Path:
    """A UDF image holding `sources/<name>` and a boot image beside it, as Windows media does."""
    return disc_image(path, {f"sources/{name}": wim, "sources/boot.wim": b"boot"}, **kwargs)
