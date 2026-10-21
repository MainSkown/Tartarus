import shutil
from pathlib import Path

import pytest

from app.analyses.memory_disk import (
    CAPE_FREESPACE_FLOOR_MB,
    MemoryDumpRefusedError,
    StorageFreeSpace,
    check_room_for_dump,
    pending_dump_mb,
)
from tests.analyses.guest_fakes import guest_named

GB = 1024
GUEST_RAM_MB = 4096


def check(free_mb: int, *, block_gb: int = 20, warn_gb: int = 50, pending_mb: int = 0) -> list[str]:
    return check_room_for_dump(
        free_mb,
        ram_mb=GUEST_RAM_MB,
        disk_block_gb=block_gb,
        disk_warn_gb=warn_gb,
        pending_dump_mb=pending_mb,
    )


def test_cape_s_own_floor_is_50000_mb() -> None:
    assert CAPE_FREESPACE_FLOOR_MB == 50_000


def test_enough_room_is_accepted_without_a_warning() -> None:
    assert check(400 * GB) == []


def test_below_cape_s_floor_is_refused_with_the_numbers() -> None:
    with pytest.raises(MemoryDumpRefusedError) as refused:
        check(int(18.2 * GB))

    assert str(refused.value) == "A memory dump needs 48.8 GB free and 18.2 GB is available"


def test_a_block_threshold_above_cape_s_floor_decides_when_it_is_the_larger() -> None:
    with pytest.raises(MemoryDumpRefusedError) as refused:
        check(70 * GB, block_gb=100)

    assert "needs 104.0 GB free and 70.0 GB is available" in str(refused.value)


def test_exactly_the_required_room_is_accepted() -> None:
    check(CAPE_FREESPACE_FLOOR_MB)


def test_room_between_the_floor_and_the_warn_line_is_accepted_with_a_warning() -> None:
    warnings = check(52 * GB)

    assert warnings == [
        "Only 52.0 GB is free: a memory dump takes 4.0 GB, "
        "and the disk warning is at 50 GB free before the dump"
    ]


def test_room_at_the_warn_line_plus_the_dump_carries_no_warning() -> None:
    assert check(50 * GB + GUEST_RAM_MB) == []


def test_the_real_probe_reads_the_free_space_of_the_storage_volume(tmp_path: Path) -> None:
    free_mb = StorageFreeSpace(tmp_path).free_mb()

    assert abs(free_mb - shutil.disk_usage(tmp_path).free // (1024 * 1024)) < 100


def test_a_storage_that_cannot_be_read_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(MemoryDumpRefusedError, match="free space of the CAPE storage"):
        StorageFreeSpace(tmp_path / "not-mounted").free_mb()


def test_dumps_already_asked_for_raise_the_room_a_new_one_needs() -> None:
    with pytest.raises(MemoryDumpRefusedError) as refused:
        check(52 * GB, pending_mb=2 * GUEST_RAM_MB)

    assert str(refused.value) == (
        "A memory dump needs 56.8 GB free and 52.0 GB is available, "
        "counting 8.0 GB for the dumps already asked for"
    )


def test_a_dump_that_fits_alone_is_accepted_when_nothing_is_pending() -> None:
    check(52 * GB)


def test_dumps_already_asked_for_move_the_warning_line_too() -> None:
    warnings = check(57 * GB, pending_mb=GUEST_RAM_MB)

    assert len(warnings) == 1


def test_the_ram_of_pending_dumps_is_summed_per_analysis_from_the_guests() -> None:
    guests = [guest_named("lab1", ram_mb=4096), guest_named("lab2", ram_mb=8192)]

    assert pending_dump_mb(guests, ["lab1", "lab2", "lab1"]) == 4096 + 8192 + 4096


def test_a_pending_dump_of_a_guest_with_unknown_ram_or_gone_counts_nothing() -> None:
    guests = [guest_named("lab1", ram_mb=None)]

    assert pending_dump_mb(guests, ["lab1", "gone"]) == 0
