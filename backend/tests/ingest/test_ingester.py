import copy
import json
import shutil
import threading
from collections import Counter
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.analyses.ports import IngestFailedError
from app.ingest import ingester as ingester_module
from app.ingest.ingester import ReportIngester
from app.ingest.protocol import IngestContext
from app.rules.loader import load_rule_file
from app.rules.rule import Rule
from app.search.index import IndexingError
from tests.ingest.conftest import ANALYSIS_ID, FULL_REPORT
from tests.ingest.fake_index import FakeIndex
from tests.rules.support import process_event, rule_yaml, simple_detection

Event = dict[str, Any]
TASK_6_LOG = Path(__file__).parent.parent / "fixtures" / "cape" / "clock" / "task_6.cuckoo.log"


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


class _ContextRecorder:
    source = "recorder"

    def __init__(self) -> None:
        self.contexts: list[IngestContext] = []

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        self.contexts.append(context)
        return iter(())


async def test_normalisers_are_told_the_analysis_folder_the_report_sits_in(
    index: FakeIndex, tmp_path: Path
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    shutil.copy(FULL_REPORT, reports / "report.json")
    recorder = _ContextRecorder()

    await ReportIngester(index, [recorder]).ingest(ANALYSIS_ID, reports / "report.json")

    assert [context.analysis_dir for context in recorder.contexts] == [tmp_path]


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


def storage_of_task_6(tmp_path: Path, *, with_log: bool) -> Path:
    reports = tmp_path / "analyses" / "6" / "reports"
    reports.mkdir(parents=True)
    shutil.copy(FULL_REPORT, reports / "report.json")
    if with_log:
        shutil.copy(TASK_6_LOG, reports.parent / "cuckoo.log")
    return reports / "report.json"


def selftest_moments(events: list[Event]) -> dict[str, datetime]:
    return {
        event["event"]["module"]: datetime.fromisoformat(event["@timestamp"])
        for event in events
        if event["event"]["action"] == "dns-query"
        and event["dns"]["question"]["name"] == "tartarus-selftest.example"
    }


async def test_the_task_log_beside_the_report_anchors_capemon_on_the_hosts_clock(
    ingester: ReportIngester, index: FakeIndex, tmp_path: Path
) -> None:
    await ingester.ingest(ANALYSIS_ID, storage_of_task_6(tmp_path, with_log=True))

    moments = selftest_moments(index.events)
    assert abs(moments["capemon"] - moments["cape"]) < timedelta(seconds=1)


async def test_without_a_task_log_the_ingest_still_works_on_the_rounded_offset(
    ingester: ReportIngester, index: FakeIndex, tmp_path: Path
) -> None:
    await ingester.ingest(ANALYSIS_ID, storage_of_task_6(tmp_path, with_log=False))

    moments = selftest_moments(index.events)
    assert timedelta(seconds=4) < abs(moments["capemon"] - moments["cape"]) < timedelta(seconds=8)


CMD_VER = "cmd.exe /c ver"


def rule_matching(tmp_path: Path, needle: str = "/c ver") -> Rule:
    path = tmp_path / "rule.yml"
    path.write_text(
        rule_yaml(simple_detection(f"CommandLine|contains: {needle}"), title="Ver"),
        encoding="utf-8",
    )
    return load_rule_file(path)


def sigma_alerts(events: list[Event]) -> list[Event]:
    return [e for e in events if e.get("rule", {}).get("ruleset") == "sigma"]


class ScriptedNormalizer:
    """Yields the given events as they are, in the given order."""

    source = "scripted"

    def __init__(self, *events: Event) -> None:
        self._events = events

    def normalise(self, report: Mapping[str, Any], context: IngestContext) -> Iterator[Event]:
        return iter(copy.deepcopy(list(self._events)))


async def test_without_rules_there_are_no_sigma_alerts(
    ingester: ReportIngester, index: FakeIndex
) -> None:
    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert sigma_alerts(index.events) == []


async def test_a_rule_matching_an_event_of_the_report_is_indexed_as_an_alert(
    index: FakeIndex, tmp_path: Path
) -> None:
    ingester = ReportIngester(index, rules=lambda: [rule_matching(tmp_path)])

    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    [alert] = sigma_alerts(index.events)
    [trigger] = [e for e in index.events if e["event"]["action"] == "process-created"]
    assert trigger["process"]["command_line"] == CMD_VER
    assert alert["event"]["kind"] == "alert"
    assert alert["related"]["events"] == [trigger["event"]["id"]]
    assert alert["tartarus"]["analysis_id"] == ANALYSIS_ID
    assert alert["tartarus"]["phase"] == "final"


async def test_the_alerts_are_numbered_and_counted_with_the_other_events(
    index: FakeIndex, tmp_path: Path
) -> None:
    plain = ReportIngester(index)
    plain_result = await plain.ingest(ANALYSIS_ID, FULL_REPORT)
    plain_count = len(index.events)

    ingester = ReportIngester(index, rules=lambda: [rule_matching(tmp_path)])
    result = await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    assert len(index.events) == plain_count + 1
    assert result.event_count == plain_result.event_count + 1
    sequences = [event["event"]["sequence"] for event in index.events]
    assert sequences == list(range(len(index.events)))
    expected = Counter(event["tartarus"]["lane"] for event in index.events)
    assert result.lane_counts == dict(expected)


async def test_events_not_in_time_order_are_matched_in_time_order(
    index: FakeIndex, tmp_path: Path
) -> None:
    later = process_event("later", "2026-10-13T10:00:30.000Z", command_line=CMD_VER)
    earlier = process_event("earlier", "2026-10-13T10:00:05.000Z", command_line=CMD_VER)
    ingester = ReportIngester(
        index, [ScriptedNormalizer(later, earlier)], rules=lambda: [rule_matching(tmp_path)]
    )

    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    [alert] = sigma_alerts(index.events)
    assert alert["related"]["events"] == ["earlier"]
    assert alert["tartarus"]["detection"]["repeated"] == 1
    assert [e["event"]["id"] for e in index.events if e["event"]["kind"] == "event"] == [
        "later",
        "earlier",
    ]


async def test_a_match_far_from_the_last_one_is_its_own_alert(
    index: FakeIndex, tmp_path: Path
) -> None:
    first = process_event("first", "2026-10-13T10:00:00.000Z", command_line=CMD_VER)
    second = process_event("second", "2026-10-13T10:02:00.000Z", command_line=CMD_VER)
    ingester = ReportIngester(
        index, [ScriptedNormalizer(second, first)], rules=lambda: [rule_matching(tmp_path)]
    )

    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)

    alerts = sigma_alerts(index.events)
    assert sorted(a["related"]["events"][0] for a in alerts) == ["first", "second"]
    assert all("repeated" not in a["tartarus"].get("detection", {}) for a in alerts)


async def test_the_rules_are_asked_for_on_every_ingest(index: FakeIndex, tmp_path: Path) -> None:
    active: list[Rule] = []
    ingester = ReportIngester(index, rules=lambda: active)

    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)
    assert sigma_alerts(index.events) == []

    active.append(rule_matching(tmp_path))
    await ingester.ingest(ANALYSIS_ID, FULL_REPORT)
    assert len(sigma_alerts(index.events)) == 1
