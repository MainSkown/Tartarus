"""Whether the CAPE storage has room for a memory dump, worked out before an analysis is queued.

A dump is the size of the guest's RAM (4 GiB for a 4096 MB guest). CAPE itself skips the dump,
silently and still reporting success, when the storage has less than its own floor free.
"""

import shutil
from pathlib import Path
from typing import Protocol

MB_PER_GB = 1024
BYTES_PER_MB = 1024 * 1024
# `cuckoo.conf [cuckoo] freespace` (default), in MB: below it CAPE logs "Could not dump ram".
CAPE_FREESPACE_FLOOR_MB = 50_000


class MemoryDumpRefusedError(Exception):
    """The dump cannot be accepted; the message says why, with the numbers."""


class FreeSpaceProbe(Protocol):
    """Free space on the volume CAPE writes its analyses to."""

    def free_mb(self) -> int:
        """Raises `MemoryDumpRefusedError` when the volume cannot be read."""


class StorageFreeSpace:
    """Reads the volume of the CAPE storage the backend mounts read-only."""

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path

    def free_mb(self) -> int:
        try:
            return shutil.disk_usage(self._storage_path).free // BYTES_PER_MB
        except OSError:
            raise MemoryDumpRefusedError(
                "The free space of the CAPE storage cannot be read, "
                "so a memory dump cannot be accepted"
            ) from None


def check_room_for_dump(
    free_mb: int, *, ram_mb: int, disk_block_gb: int, disk_warn_gb: int
) -> list[str]:
    """Raises `MemoryDumpRefusedError` below the room the dump needs; else the warnings to show."""
    required_mb = max(CAPE_FREESPACE_FLOOR_MB, disk_block_gb * MB_PER_GB + ram_mb)
    if free_mb < required_mb:
        raise MemoryDumpRefusedError(
            f"A memory dump needs {_gb(required_mb)} free and {_gb(free_mb)} is available"
        )
    if free_mb < disk_warn_gb * MB_PER_GB + ram_mb:
        return [
            f"Only {_gb(free_mb)} is free: a memory dump takes {_gb(ram_mb)}, "
            f"and the disk warning is at {disk_warn_gb} GB free before the dump"
        ]
    return []


def _gb(megabytes: int) -> str:
    return f"{megabytes / MB_PER_GB:.1f} GB"
