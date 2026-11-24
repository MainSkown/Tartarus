"""The `lan-sim` source inside the ingester: off changes nothing, on adds events and flags."""

import json
import shutil
from pathlib import Path
from typing import Any

from app.ingest.capemon import CapemonNormalizer
from app.ingest.ingester import ReportIngester, default_normalizers
from app.ingest.lan_sim import LanSimNormalizer
from app.views.network import shape_network
from tests.ingest.conftest import ANALYSIS_ID, FULL_REPORT
from tests.ingest.fake_index import FakeIndex
from tests.ingest.lan_sim_cases import (
    FILE_SERVER,
    LAN_HOSTS,
    context_of,
    file_write,
    login,
    session_end,
    write_log,
)

Event = dict[str, Any]


def analysis_with_flows_to_the_fake_host(root: Path) -> Path:
    report = json.loads(FULL_REPORT.read_text())
    report["network"]["tcp"].append(
        {"src": "192.168.150.10", "sport": 50123, "dst": FILE_SERVER, "dport": 445, "time": 2.0}
    )
    reports = root / "reports"
    reports.mkdir(parents=True)
    path = reports / "report.json"
    path.write_text(json.dumps(report))
    return path


async def ingest(report_path: Path, **options: Any) -> list[Event]:
    index = FakeIndex()
    await ReportIngester(index).ingest(ANALYSIS_ID, report_path, **options)
    return index.events


def test_the_ingester_runs_the_lan_sim_source_among_the_others() -> None:
    assert [n.source for n in default_normalizers()].count("lan-sim") == 1
    assert any(isinstance(n, LanSimNormalizer) for n in default_normalizers())


async def test_a_run_without_the_fake_lan_is_ingested_exactly_as_before() -> None:
    before = FakeIndex()
    others = [n for n in default_normalizers() if not isinstance(n, LanSimNormalizer)]
    await ReportIngester(before, normalizers=others).ingest(ANALYSIS_ID, FULL_REPORT)

    assert await ingest(FULL_REPORT) == before.events


async def test_a_run_whose_log_is_missing_is_ingested_exactly_as_before(tmp_path: Path) -> None:
    before = FakeIndex()
    others = [n for n in default_normalizers() if not isinstance(n, LanSimNormalizer)]
    report_path = tmp_path / "reports" / "report.json"
    report_path.parent.mkdir()
    shutil.copy(FULL_REPORT, report_path)
    await ReportIngester(before, normalizers=others).ingest(ANALYSIS_ID, report_path)

    assert await ingest(report_path, lan_hosts=LAN_HOSTS) == before.events


async def test_a_log_without_fake_hosts_is_ignored(tmp_path: Path) -> None:
    report_path = analysis_with_flows_to_the_fake_host(tmp_path)
    plain = await ingest(report_path)
    write_log(tmp_path, [login(), file_write()])

    assert await ingest(report_path) == plain
    assert await ingest(report_path, lan_hosts={}) == plain


async def test_the_log_adds_lan_events_and_flags_the_flow_without_adding_a_flow_row(
    tmp_path: Path,
) -> None:
    report_path = analysis_with_flows_to_the_fake_host(tmp_path)
    without_log = await ingest(report_path, lan_hosts=LAN_HOSTS)
    write_log(tmp_path, [login(), file_write(), login(user="root")])

    with_log = await ingest(report_path, lan_hosts=LAN_HOSTS)

    added = [e for e in with_log if e["event"]["module"] == "lan-sim"]
    assert [e["event"]["action"] for e in added] == [
        "lan-login-attempt",
        "lan-file-write",
        "lan-login-attempt",
    ]
    assert len(with_log) == len(without_log) + 3
    assert flow_rows(with_log) == flow_rows(without_log)
    [flagged] = [
        e
        for e in with_log
        if e.get("tartarus", {}).get("lan", {}).get("host") and e["event"]["module"] == "cape"
    ]
    assert flagged["destination"]["ip"] == FILE_SERVER


def flow_rows(events: list[Event]) -> int:
    return shape_network(events, simulated=False, limit=10000).flows.total


async def test_sequences_stay_unique_and_increasing_with_the_new_source(tmp_path: Path) -> None:
    report_path = analysis_with_flows_to_the_fake_host(tmp_path)
    write_log(tmp_path, [login()])

    events = await ingest(report_path, lan_hosts=LAN_HOSTS)

    assert [e["event"]["sequence"] for e in events] == list(range(len(events)))
    assert len({e["event"]["id"] for e in events}) == len(events)


def test_capemon_is_untouched_by_the_fake_hosts() -> None:
    report = json.loads(FULL_REPORT.read_text())

    assert list(CapemonNormalizer().normalise(report, context_of(None))) == list(
        CapemonNormalizer().normalise(report, context_of(None, {}))
    )


async def summarised(report_path: Path, **options: Any) -> Any:
    return await ReportIngester(FakeIndex()).ingest(ANALYSIS_ID, report_path, **options)


async def test_a_run_without_the_fake_lan_has_no_lan_summary(tmp_path: Path) -> None:
    report_path = analysis_with_flows_to_the_fake_host(tmp_path)
    write_log(tmp_path, [login()])

    assert (await summarised(report_path)).lan is None
    assert (await summarised(report_path, lan_hosts={})).lan is None


async def test_the_result_carries_the_lan_summary_of_the_events_it_indexed(tmp_path: Path) -> None:
    report_path = analysis_with_flows_to_the_fake_host(tmp_path)
    write_log(tmp_path, [login(), file_write(), session_end(log_truncated=True)])

    lan = (await summarised(report_path, lan_hosts=LAN_HOSTS)).lan

    assert lan is not None
    [host] = lan.hosts
    assert host.address == FILE_SERVER
    assert [(s.service, s.port, s.attempts) for s in host.services] == [("smb", 445, 2)]
    assert [c.user for c in host.credentials] == ["Administrator"]
    assert len(host.files) == 1
    assert lan.truncated is True


async def test_a_run_whose_log_is_missing_still_summarises_the_flows(tmp_path: Path) -> None:
    report_path = analysis_with_flows_to_the_fake_host(tmp_path)

    lan = (await summarised(report_path, lan_hosts=LAN_HOSTS)).lan

    assert lan is not None
    assert [h.fqdn for h in lan.hosts] == ["fs01.corp.local"]
    assert lan.truncated is False


async def test_a_run_on_the_lan_that_did_nothing_has_a_summary_without_hosts() -> None:
    lan = (await summarised(FULL_REPORT, lan_hosts=LAN_HOSTS)).lan

    assert lan is not None
    assert lan.hosts == []
