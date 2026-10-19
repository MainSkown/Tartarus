import asyncio
import json
from pathlib import Path
from typing import Any

from app.analyses.defender import DefenderStatus
from app.ingest.ingester import ReportIngester
from app.ingest.sysmon import SysmonNormalizer
from tests.ingest.defender_cases import (
    EICAR_STARTED,
    EICAR_TASK,
    copy_export,
)
from tests.ingest.defender_cases import report_of as defender_report_of
from tests.ingest.fake_index import FakeIndex
from tests.ingest.sysmon_cases import WIDE_REPORT, analysis_with_fixture
from tests.ingest.sysmon_cases import context_of as sysmon_context_of

EICAR_REPORT = defender_report_of(EICAR_TASK, EICAR_STARTED, images=())
SYSMON_REPORT = {**WIDE_REPORT, "info": {**WIDE_REPORT["info"], "id": EICAR_TASK}}


def analysis_on_disk(
    root: Path, report: dict[str, Any], *, defender: bool = False, sysmon: bool = False
) -> Path:
    """CAPE's layout: `<root>/reports/report.json` beside the `aux/` and `sysmon/` exports."""
    reports = root / "reports"
    reports.mkdir(parents=True)
    report_path = reports / "report.json"
    report_path.write_text(json.dumps(report))
    if defender:
        copy_export(root, "defender-eicar-sample.xml")
    if sysmon:
        analysis_with_fixture(root)
    return report_path


def sysmon_noise_counts(report: dict[str, Any], root: Path) -> dict[str, int]:
    normalizer = SysmonNormalizer()
    list(normalizer.normalise(report, sysmon_context_of(root)))
    return dict(normalizer.dropped)


class GatedIndex(FakeIndex):
    """Holds the first bulk index open after its events were read, so a second ingest can run."""

    def __init__(self) -> None:
        super().__init__()
        self.first_events_read = asyncio.Event()
        self.release_first = asyncio.Event()
        self._gated = False

    async def bulk_index(self, analysis_id: int, events: Any, chunk_size: int = 1000) -> int:
        count = await super().bulk_index(analysis_id, events, chunk_size)
        if not self._gated:
            self._gated = True
            self.first_events_read.set()
            await self.release_first.wait()
        return count


async def test_the_defender_verdict_comes_from_the_same_run_as_the_events(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path, EICAR_REPORT, defender=True)

    result = await ReportIngester(FakeIndex()).ingest(1, report_path)

    assert result.defender is not None
    assert result.defender.status is DefenderStatus.REMOVED
    assert result.defender.sample_removed is True


async def test_a_sample_removed_with_no_process_in_the_report_was_blocked_before_it_ran(
    tmp_path: Path,
) -> None:
    report_path = analysis_on_disk(tmp_path, EICAR_REPORT, defender=True)

    result = await ReportIngester(FakeIndex()).ingest(1, report_path)

    assert result.defender is not None
    assert result.defender.blocked_before_run is True


async def test_a_sample_removed_after_it_started_a_process_was_not_blocked_before_it_ran(
    tmp_path: Path,
) -> None:
    report = defender_report_of(EICAR_TASK, EICAR_STARTED)
    report_path = analysis_on_disk(tmp_path, report, defender=True)

    result = await ReportIngester(FakeIndex()).ingest(1, report_path)

    assert result.defender is not None
    assert result.defender.sample_removed is True
    assert result.defender.blocked_before_run is False


async def test_no_defender_export_is_a_no_export_verdict_not_a_missing_one(
    tmp_path: Path,
) -> None:
    report_path = analysis_on_disk(tmp_path, EICAR_REPORT)

    result = await ReportIngester(FakeIndex()).ingest(1, report_path)

    assert result.defender is not None
    assert result.defender.status is DefenderStatus.NO_EXPORT


async def test_the_sysmon_noise_that_was_hidden_is_counted_by_reason(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path, SYSMON_REPORT, sysmon=True)

    result = await ReportIngester(FakeIndex()).ingest(1, report_path)

    assert result.hidden_events
    assert result.hidden_events == sysmon_noise_counts(SYSMON_REPORT, tmp_path)


async def test_no_sysmon_file_hides_nothing(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path, SYSMON_REPORT)

    result = await ReportIngester(FakeIndex()).ingest(1, report_path)

    assert result.hidden_events == {}


async def test_an_ingester_without_the_two_sources_reports_neither(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path, SYSMON_REPORT, defender=True, sysmon=True)

    result = await ReportIngester(FakeIndex(), normalizers=[]).ingest(1, report_path)

    assert result.defender is None
    assert result.hidden_events == {}


async def test_an_injected_sysmon_normaliser_is_the_one_whose_counts_are_reported(
    tmp_path: Path,
) -> None:
    report_path = analysis_on_disk(tmp_path, SYSMON_REPORT, sysmon=True)
    injected = SysmonNormalizer()

    result = await ReportIngester(FakeIndex(), normalizers=[injected]).ingest(1, report_path)

    assert result.hidden_events == dict(injected.dropped)
    assert result.hidden_events


async def test_two_interleaved_ingests_on_one_ingester_do_not_mix_their_findings(
    tmp_path: Path,
) -> None:
    noisy_path = analysis_on_disk(tmp_path / "noisy", SYSMON_REPORT, defender=True, sysmon=True)
    quiet_path = analysis_on_disk(tmp_path / "quiet", EICAR_REPORT)
    index = GatedIndex()
    ingester = ReportIngester(index)

    noisy = asyncio.create_task(ingester.ingest(1, noisy_path))
    await index.first_events_read.wait()
    quiet_result = await ingester.ingest(2, quiet_path)
    index.release_first.set()
    noisy_result = await noisy

    assert quiet_result.hidden_events == {}
    assert quiet_result.defender is not None
    assert quiet_result.defender.status is DefenderStatus.NO_EXPORT
    assert noisy_result.hidden_events == sysmon_noise_counts(SYSMON_REPORT, tmp_path / "noisy")
    assert noisy_result.defender is not None
    assert noisy_result.defender.status is DefenderStatus.REMOVED
