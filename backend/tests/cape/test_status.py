import pytest

from app.cape.status import CAPE_STATUS_PROGRESS, CapeProgress, progress_for

# Every TASK_* constant in CAPE's lib/cuckoo/core/data/task.py (ALL_DB_STATUSES), read from
# the image tartarus-cape. Not in database.py: this CAPE version moved them.
ALL_CAPE_STATUSES = {
    "banned": CapeProgress.FAILED,
    "pending": CapeProgress.STARTING,
    "running": CapeProgress.RUNNING,
    "distributed": CapeProgress.STARTING,
    "completed": CapeProgress.PROCESSING,
    "recovered": CapeProgress.FAILED,
    "reported": CapeProgress.INGESTING,
    "failed_analysis": CapeProgress.FAILED,
    "failed_processing": CapeProgress.FAILED,
    "failed_reporting": CapeProgress.REPORT_FAILED,
    "distributed_completed": CapeProgress.PROCESSING,
}


@pytest.mark.parametrize(("cape_status", "expected"), ALL_CAPE_STATUSES.items())
def test_every_cape_status_maps_to_its_analysis_progress(
    cape_status: str, expected: CapeProgress
) -> None:
    assert progress_for(cape_status) is expected


def test_the_mapping_table_holds_exactly_the_statuses_cape_defines() -> None:
    assert set(CAPE_STATUS_PROGRESS) == set(ALL_CAPE_STATUSES)


@pytest.mark.parametrize("cape_status", ["", "teleporting", "REPORTED", "Running"])
def test_a_status_cape_does_not_define_is_unknown(cape_status: str) -> None:
    assert progress_for(cape_status) is CapeProgress.UNKNOWN


def test_unknown_is_not_a_progress_any_known_status_maps_to() -> None:
    assert CapeProgress.UNKNOWN not in CAPE_STATUS_PROGRESS.values()
