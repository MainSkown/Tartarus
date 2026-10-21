from enum import StrEnum


class ImportKind(StrEnum):
    PCAP = "pcap"
    PCAPNG = "pcapng"
    MEMORY_IMAGE = "memory_image"
    UNSUPPORTED = "unsupported"


_PCAP_MAGICS = (
    bytes.fromhex("a1b2c3d4"),
    bytes.fromhex("d4c3b2a1"),
    bytes.fromhex("a1b23c4d"),
    bytes.fromhex("4d3cb2a1"),
)
_PCAPNG_MAGIC = bytes.fromhex("0a0d0d0a")
_ELF_MAGIC = b"\x7fELF"
_CRASH_DUMP_MAGICS = (b"PAGEDU64", b"PAGEDUMP")


def sniff_import(head: bytes) -> ImportKind:
    if head.startswith(_PCAP_MAGICS):
        return ImportKind.PCAP
    if head.startswith(_PCAPNG_MAGIC):
        return ImportKind.PCAPNG
    if head.startswith((_ELF_MAGIC, *_CRASH_DUMP_MAGICS)):
        return ImportKind.MEMORY_IMAGE
    return ImportKind.UNSUPPORTED
