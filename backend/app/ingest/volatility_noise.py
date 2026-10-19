"""The one noise rule for memory findings: the capemon monitor's own pages.

CAPE's monitor (capemon) keeps RWX pages inside every process it watches. In the S3 spike (one
guest, 4 runs) they were 8 of the 10 malfind rows of the sample's processes, at the same three
addresses in every process and every run, untagged. The addresses are not what identifies them:
the first eight bytes of each page are a little-endian pointer to the page itself (a header the
monitor writes), which injected code, a PE image or shellcode has no reason to carry. Judging by
that content keeps working when the monitor is rebuilt and its pages move, and a real finding
that happens to land on a known monitor address is not dropped.

A row that cannot be judged (no start address, no readable preview) is kept: a dropped real
injection costs more than a noisy row. Not tested beyond the S3 sample.
"""

from collections.abc import Mapping
from typing import Any

from app.ingest.reading import text_or_none, to_int

POINTER_BYTES = 8
MONITOR_PAGE = "monitor-page"


def is_monitor_page(row: Mapping[str, Any]) -> bool:
    start = to_int(row.get("Start VPN"))
    first_bytes = _leading_bytes(row.get("Hexdump"))
    return (
        start is not None
        and first_bytes is not None
        and int.from_bytes(first_bytes, "little") == start
    )


def _leading_bytes(hexdump: object) -> bytes | None:
    text = text_or_none(hexdump)
    tokens = text.split()[:POINTER_BYTES] if text else []
    try:
        pointer = bytes(int(token, 16) for token in tokens)
    except ValueError:
        return None
    return pointer if len(pointer) == POINTER_BYTES else None
