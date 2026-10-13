import json
import threading
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from app.analyses.ports import IngestFailedError
from app.ingest import ingester as ingester_module
from app.ingest.ingester import ReportIngester
from app.search.index import IndexingError
from tests.ingest.conftest import ANALYSIS_ID, FULL_REPORT

Event = dict[str, Any]


class FakeIndex:
    """Records every call in order; `failures` maps a method name to the error it raises."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.events: list[Event] = []
        self.failures: dict[str, Exception] = {}
        self.bulk_thread_ids: list[int] = []

    def _record(self, call: str) -> None:
        self.calls.append(call)
        method = call.split(":", maxsplit=1)[0]
        before_index_exists = method == "drop" and "create" not in self.calls
        if method in self.failures and not before_index_exists:
            raise self.failures[method]

    async def ensure_template(self) -> None:
        self._record("ensure_template")

    async def drop(self, analysis_id: int) -> None:
        self._record("drop")

    async def create(self, analysis_id: int) -> None:
        self._record("create")

    async def bulk_index(
        self, analysis_id: int, events: Iterable[Event], chunk_size: int = 1000
    ) -> int:
        self._record("bulk_index")
        self.events = list(events)
        return len(self.events)

    async def set_refresh_interval(self, analysis_id: int, interval: str) -> None:
        self._record(f"set_refresh_interval:{interval}")

    async def refresh(self, analysis_id: int) -> None:
        self._record("refresh")


@pytest.fixture
def index() -> FakeIndex:
    return FakeIndex()


@pytest.fixture
def ingester(index: FakeIndex) -> ReportIngester:
    return ReportIngester(index)


async def test_the_index_is_rebuilt_in_order_and_left_refreshing_slowly(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert index.calls == [
        "ensure_template",
        "drop",
        "create",
        "bulk_index",
        "set_refresh_interval:30s",
        "refresh",
    ]


async def test_the_template_is_ensured_on_every_ingest(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)
    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert index.calls.count("ensure_template") == 2


async def test_sequence_is_unique_and_increasing_across_the_three_sources(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    sequences = [event["event"]["sequence"] for event in index.events]
    assert sequences == list(range(len(index.events)))
    kinds = {event["event"]["kind"] for event in index.events}
    datasets = {event["event"]["dataset"] for event in index.events}
    assert "alert" in kinds
    assert "capemon.api" in datasets
    assert any("network" in dataset or "dns" in dataset for dataset in datasets)


async def test_the_result_counts_events_and_lanes_as_indexed(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    result = await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    expected = Counter(event["tartarus"]["lane"] for event in index.events)
    assert result.lane_counts == dict(expected)
    assert result.event_count == len(index.events) == sum(expected.values())
    assert result.event_count > 0


async def test_events_belong_to_the_analysis_being_ingested(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert {event["tartarus"]["analysis_id"] for event in index.events} == {ANALYSIS_ID}


@pytest.mark.parametrize("failing", ["create", "bulk_index", "set_refresh_interval", "refresh"])
async def test_a_failure_after_the_index_exists_drops_it_and_says_why(
    ingester: ReportIngester, index: FakeIndex, failing: str
) -> None:
    index.failures[failing] = IndexingError("3 events rejected: boom")

    with pytest.raises(IngestFailedError, match="3 events rejected: boom"):
        await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert index.calls[-1] == "drop"
    assert index.calls.count("drop") == 2


async def test_an_unexpected_error_is_named_in_the_message(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    index.failures["bulk_index"] = ConnectionError("secret-host:9200 refused")

    with pytest.raises(IngestFailedError, match="ConnectionError") as raised:
        await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert "secret-host" not in str(raised.value)


async def test_a_failed_cleanup_does_not_hide_the_original_failure(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    index.failures["bulk_index"] = IndexingError("rejected")
    index.failures["drop"] = ConnectionError("down")

    with pytest.raises(IngestFailedError, match="rejected"):
        await ingester.ingest(ANALYSIS_ID, FULL_REPORT)


async def test_opensearch_being_down_when_the_template_is_ensured_fails_the_ingest(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    index.failures["ensure_template"] = ConnectionError("down")

    with pytest.raises(IngestFailedError, match="ConnectionError"):
        await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert index.calls == ["ensure_template"]


async def test_a_missing_report_fails_before_any_index_is_created(
    ingester: ReportIngester, index: FakeIndex, tmp_path: Path
) -> None:
    with pytest.raises(IngestFailedError, match=r"report\.json"):
        await ingester.ingest(ANALYSIS_ID, tmp_path / "report.json")

    assert "create" not in index.calls


@pytest.mark.parametrize(
    "content",
    [b"{not json", b"[]", json.dumps({"info": {}}).encode()],
    ids=["invalid-json", "not-an-object", "no-start-time"],
)
async def test_a_report_that_cannot_be_indexed_fails_before_any_index_is_created(
    ingester: ReportIngester, index: FakeIndex, tmp_path: Path, content: bytes
) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(content)

    with pytest.raises(IngestFailedError):
        await ingester.ingest(ANALYSIS_ID, report)

    assert "create" not in index.calls


async def test_the_report_is_parsed_off_the_event_loop(
    ingester: ReportIngester, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[int] = []
    real_load = ingester_module.load_report

    def spy(path: Path) -> dict[str, Any]:
        threads.append(threading.get_ident())
        return real_load(path)

    monkeypatch.setattr(ingester_module, "load_report", spy)

    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert threads
    assert threading.get_ident() not in threads
