from datetime import UTC, datetime
from pathlib import Path

from app.ingest.ingester import ReportIngester
from tests.ingest.fake_index import FakeIndex
from tests.ingest.volatility_cases import P9_INJECTED_PID, write_p9_image_memory

IMPORTED_AT = datetime(2026, 10, 22, 8, 0, 0, tzinfo=UTC)


async def test_the_findings_of_an_image_without_a_report_become_memory_events(
    tmp_path: Path,
) -> None:
    index = FakeIndex()
    write_p9_image_memory(tmp_path)

    result = await ReportIngester(index).ingest_memory_image(3, tmp_path, started_at=IMPORTED_AT)

    assert result.lane_counts == {"memory": 26}
    assert result.event_count == 26
    assert {event["tartarus"]["lane"] for event in index.events} == {"memory"}


async def test_the_injected_process_of_an_image_raises_a_high_severity_detection(
    tmp_path: Path,
) -> None:
    index = FakeIndex()
    write_p9_image_memory(tmp_path)

    await ReportIngester(index).ingest_memory_image(3, tmp_path, started_at=IMPORTED_AT)

    alerts = [event for event in index.events if event["event"]["kind"] == "alert"]
    injected = [alert for alert in alerts if alert["process"]["pid"] == P9_INJECTED_PID]
    assert [alert["process"]["name"] for alert in injected] == ["PING.EXE"]
    assert injected[0]["event"]["severity"] == 3
    assert injected[0]["rule"]["ruleset"] == "volatility"


async def test_the_findings_of_an_image_sit_at_the_given_start(tmp_path: Path) -> None:
    index = FakeIndex()
    write_p9_image_memory(tmp_path)

    await ReportIngester(index).ingest_memory_image(3, tmp_path, started_at=IMPORTED_AT)

    assert {event["@timestamp"] for event in index.events} == {"2026-10-22T08:00:00.000Z"}


async def test_an_image_with_no_findings_folder_gives_an_empty_index(tmp_path: Path) -> None:
    index = FakeIndex()

    result = await ReportIngester(index).ingest_memory_image(3, tmp_path, started_at=IMPORTED_AT)

    assert (result.event_count, index.calls[:2]) == (0, ["ensure_template", "drop"])
