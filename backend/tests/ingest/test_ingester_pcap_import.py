import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.ingest.ingester import ReportIngester
from tests.ingest.fake_index import FakeIndex

FIXTURES = Path(__file__).resolve().parents[3] / "docs" / "history" / "m9-spikes" / "fixtures"
FIRST_PACKET = datetime(2026, 10, 21, 12, 52, 52, 871033, tzinfo=UTC)
IMPORT_MOMENT = "2026-10-22 08:00:00"


def pcap_task_report(tmp_path: Path) -> Path:
    network = json.loads((FIXTURES / "p9-dpkt-network-section.json").read_text())
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"info": {"started": IMPORT_MOMENT}, "network": network}))
    return report


async def test_the_network_of_an_imported_capture_gives_the_events_of_the_run_it_came_from(
    tmp_path: Path,
) -> None:
    index = FakeIndex()

    result = await ReportIngester(index).ingest(
        1, pcap_task_report(tmp_path), started_at=FIRST_PACKET
    )

    actions = Counter(event["event"]["action"] for event in index.events)
    assert actions == {"network-connection": 187, "dns-query": 5, "http-request": 4}
    assert result.event_count == 196
    assert not any("process" in event for event in index.events)


async def test_the_timeline_of_an_imported_capture_starts_at_its_first_packet(
    tmp_path: Path,
) -> None:
    index = FakeIndex()

    await ReportIngester(index).ingest(1, pcap_task_report(tmp_path), started_at=FIRST_PACKET)

    stamps = [datetime.fromisoformat(event["@timestamp"]) for event in index.events]
    assert min(stamps) >= FIRST_PACKET
    assert max(stamps) < FIRST_PACKET.replace(minute=59)


async def test_without_a_given_start_the_reports_own_start_is_used(tmp_path: Path) -> None:
    index = FakeIndex()

    await ReportIngester(index).ingest(1, pcap_task_report(tmp_path))

    first_flow = min(
        datetime.fromisoformat(event["@timestamp"])
        for event in index.events
        if event["event"]["action"] == "network-connection"
    )
    assert first_flow.date().isoformat() == "2026-10-22"
