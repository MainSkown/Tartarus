import json
from pathlib import Path

from app.ingest.ingester import ReportIngester
from tests.ingest.fake_index import FakeIndex
from tests.ingest.sysmon_cases import (
    BENIGN,
    analysis_with,
    event_xml,
    guid,
    monitored,
    report_with,
)

STARTED_AT = "2026-10-18 20:43:49.000"
BENIGN_SHA256 = "4b322b00" * 8


def sample_started(sha256: str | None = BENIGN_SHA256) -> str:
    hashes = {} if sha256 is None else {"Hashes": f"SHA1=AAAA,SHA256={sha256.upper()}"}
    return event_xml(
        1,
        1,
        STARTED_AT,
        {
            "UtcTime": STARTED_AT,
            "ProcessGuid": guid(1),
            "ProcessId": 500,
            "Image": BENIGN,
            "CommandLine": BENIGN,
            "ParentProcessGuid": guid(99),
            "ParentProcessId": 4,
            "ParentImage": "System",
            "ParentCommandLine": "System",
            **hashes,
        },
    )


def analysis_on_disk(root: Path, *sysmon_events: str) -> Path:
    reports = root / "reports"
    reports.mkdir(parents=True)
    report_path = reports / "report.json"
    report_path.write_text(json.dumps(report_with(monitored(500, BENIGN))))
    if sysmon_events:
        analysis_with(root, *sysmon_events)
    return report_path


async def test_an_archive_entry_gets_the_hash_of_the_process_started_from_it(
    tmp_path: Path,
) -> None:
    index = FakeIndex()
    report_path = analysis_on_disk(tmp_path, sample_started())

    result = await ReportIngester(index).ingest(1, report_path, archive_entry="benign.exe")

    assert result.entry_sha256 == BENIGN_SHA256
    assert any(event["event"]["action"] == "process-created" for event in index.events)


async def test_without_an_archive_entry_the_result_has_no_entry_hash(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path, sample_started())

    result = await ReportIngester(FakeIndex()).ingest(1, report_path)

    assert result.entry_sha256 is None


async def test_an_entry_no_process_was_started_from_has_no_hash(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path, sample_started())

    result = await ReportIngester(FakeIndex()).ingest(1, report_path, archive_entry="other.exe")

    assert result.entry_sha256 is None


async def test_a_process_creation_without_a_sha256_gives_no_entry_hash(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path, sample_started(sha256=None))

    result = await ReportIngester(FakeIndex()).ingest(1, report_path, archive_entry="benign.exe")

    assert result.entry_sha256 is None


async def test_a_run_without_a_sysmon_export_has_no_entry_hash(tmp_path: Path) -> None:
    report_path = analysis_on_disk(tmp_path)

    result = await ReportIngester(FakeIndex()).ingest(1, report_path, archive_entry="benign.exe")

    assert result.entry_sha256 is None
