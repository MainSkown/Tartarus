import shutil
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from opensearchpy import AsyncOpenSearch
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analyses.ports import IngestFailedError
from app.analyses.runner import Runner, RunnerConfig
from app.analyses.summary import read_report
from app.api.analyses import router as analyses_router
from app.api.dependencies import (
    get_cape,
    get_event_index,
    get_exports_path,
    get_guest_control,
    get_imports_dir,
    get_runner,
    get_sample_store,
)
from app.api.operation_ids import generate_operation_id
from app.db import analysis_repository as repository
from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus
from app.errors import install_error_handlers
from app.ingest.ingester import ReportIngester
from app.ingest.protocol import IngestContext
from app.rules.loader import load_rules
from app.samples.store import SampleStore
from app.search.client import create_opensearch_client
from app.search.index import EventIndex, index_name
from tests.analyses.fakes import FakeCape, FakeSamples
from tests.analyses.guest_fakes import ScriptedGuestControl
from tests.ingest.conftest import FULL_REPORT
from tests.rules.support import TARTARUS_RULESET
from tests.test_analysis_repository import OPTIONS, SHA_A, make_sample

pytestmark = pytest.mark.integration

FIRST_CAPE_TASK = 100


class StubCape(FakeCape):
    async def delete_task(self, task_id: int, task_status: str | None = None) -> None:
        self.calls.append(("delete", task_id))


class IdleRunner:
    def nudge(self) -> None:
        return None


@dataclass
class Stack:
    runner: Runner
    client: httpx.AsyncClient
    factory: async_sessionmaker[AsyncSession]
    opensearch: AsyncOpenSearch
    index: EventIndex
    analysis_id: int

    async def run_until_done(self) -> None:
        for _ in range(10):
            await self.runner.run_once()
            if (await self.status()) is AnalysisStatus.DONE:
                return
        raise AssertionError(f"analysis ended as {await self.status()}")

    async def status(self) -> AnalysisStatus:
        return (await self.analysis()).status

    async def analysis(self) -> Analysis:
        async with self.factory() as session:
            analysis = await repository.get_analysis(session, self.analysis_id)
        assert analysis is not None
        return analysis

    async def document_count(self) -> int:
        response = await self.opensearch.count(index=index_name(self.analysis_id))
        return int(response["count"])

    async def documents_per_lane(self) -> dict[str, int]:
        response = await self.opensearch.search(
            index=index_name(self.analysis_id),
            body={"size": 0, "aggs": {"lanes": {"terms": {"field": "tartarus.lane"}}}},
        )
        buckets = response["aggregations"]["lanes"]["buckets"]
        return {bucket["key"]: bucket["doc_count"] for bucket in buckets}

    async def index_names(self) -> list[str]:
        response = await self.opensearch.indices.get(index=index_name(self.analysis_id))
        return sorted(response)


@pytest.fixture
async def opensearch(opensearch_url: str) -> AsyncIterator[AsyncOpenSearch]:
    client = create_opensearch_client(opensearch_url)
    yield client
    await client.close()


@pytest.fixture
async def stack(
    session_factory: async_sessionmaker[AsyncSession],
    opensearch: AsyncOpenSearch,
    make_client: Callable[[FastAPI], httpx.AsyncClient],
    tmp_path: Path,
) -> AsyncIterator[Stack]:
    reports_dir = tmp_path / "storage" / "analyses" / str(FIRST_CAPE_TASK) / "reports"
    reports_dir.mkdir(parents=True)
    shutil.copy(FULL_REPORT, reports_dir / "report.json")
    plain = tmp_path / "plain"
    plain.mkdir()
    cape = StubCape()
    cape.script_for_new_tasks = ["reported"]
    index = EventIndex(opensearch)
    runner = Runner(
        session_factory,
        cape,
        FakeSamples(plain),
        read_report,
        ReportIngester(index),
        ScriptedGuestControl(),
        RunnerConfig(
            cape_storage_path=tmp_path / "storage",
            poll_interval=3600.0,
            unreachable_grace=120.0,
        ),
    )
    async with session_factory() as session:
        await repository.add_sample_if_new(session, make_sample())
        created = await repository.create_analysis(
            session,
            sample_sha256=SHA_A,
            filename="benign.exe",
            options={**OPTIONS, "guest": "win"},
        )

    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.state.session_factory = session_factory
    app.include_router(analyses_router, prefix="/api")
    app.dependency_overrides[get_cape] = lambda: cape
    app.dependency_overrides[get_event_index] = lambda: index
    guests = ScriptedGuestControl()
    app.dependency_overrides[get_guest_control] = lambda: guests
    app.dependency_overrides[get_runner] = IdleRunner
    app.dependency_overrides[get_exports_path] = lambda: tmp_path / "exports"
    app.dependency_overrides[get_imports_dir] = lambda: tmp_path / "imports"
    app.dependency_overrides[get_sample_store] = lambda: SampleStore(tmp_path / "samples")
    async with make_client(app) as client:
        yield Stack(runner, client, session_factory, opensearch, index, created.id)
    await index.drop(created.id)


async def test_the_fixture_report_is_indexed_and_counted_by_lane(stack: Stack) -> None:
    await stack.run_until_done()

    done = await stack.analysis()
    assert done.event_count > 0
    assert await stack.document_count() == done.event_count
    lane_counts = done.summary["lane_counts"]
    assert lane_counts == await stack.documents_per_lane()
    assert sum(lane_counts.values()) == done.event_count
    assert {"api", "network", "process"} <= lane_counts.keys()


async def test_every_event_has_a_unique_sequence(stack: Stack) -> None:
    await stack.run_until_done()

    response = await stack.opensearch.search(
        index=index_name(stack.analysis_id),
        body={"size": 0, "aggs": {"sequences": {"cardinality": {"field": "event.sequence"}}}},
    )
    assert response["aggregations"]["sequences"]["value"] == await stack.document_count()


async def test_ingesting_twice_leaves_one_index_with_the_same_documents(stack: Stack) -> None:
    await stack.run_until_done()
    first = await stack.analysis()

    reingested = await stack.client.post(f"/api/analyses/{stack.analysis_id}/reingest")
    assert reingested.status_code == 200
    await stack.run_until_done()

    second = await stack.analysis()
    assert await stack.index_names() == [index_name(stack.analysis_id)]
    assert await stack.document_count() == first.event_count == second.event_count
    assert second.summary["lane_counts"] == first.summary["lane_counts"]


async def test_deleting_the_analysis_drops_its_index(stack: Stack) -> None:
    await stack.run_until_done()

    response = await stack.client.delete(f"/api/analyses/{stack.analysis_id}")

    assert response.status_code == 204
    assert not await stack.opensearch.indices.exists(index=index_name(stack.analysis_id))


async def test_deleting_an_analysis_that_was_never_indexed_is_fine(stack: Stack) -> None:
    async with stack.factory() as session:
        await repository.update_analysis(session, stack.analysis_id, status=AnalysisStatus.FAILED)

    response = await stack.client.delete(f"/api/analyses/{stack.analysis_id}")

    assert response.status_code == 204


class ExplodingNormalizer:
    """Yields one valid event, then one OpenSearch rejects: a date that is not a date."""

    source = "exploding"

    def __init__(self, bad_event: Mapping[str, Any]) -> None:
        self._bad_event = dict(bad_event)

    def normalise(
        self, report: Mapping[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        for number, extra in enumerate([{}, self._bad_event]):
            yield {
                "@timestamp": "2026-10-13T12:12:18Z",
                "event": {"id": f"exploding-{number}", "kind": "event", "sequence": number},
                "tartarus": {"analysis_id": context.analysis_id, "lane": "process"},
            } | extra


async def test_events_opensearch_rejects_leave_no_index_behind(
    stack: Stack, opensearch: AsyncOpenSearch
) -> None:
    bad = ExplodingNormalizer({"@timestamp": "not-a-date"})
    ingester = ReportIngester(stack.index, normalizers=[bad])
    report = FULL_REPORT

    with pytest.raises(IngestFailedError, match="rejected"):
        await ingester.ingest(stack.analysis_id, report)

    assert not await opensearch.indices.exists(index=index_name(stack.analysis_id))


async def test_a_failed_reingest_replaces_the_old_index_with_nothing(stack: Stack) -> None:
    await stack.run_until_done()
    bad = ExplodingNormalizer({"@timestamp": "not-a-date"})

    with pytest.raises(IngestFailedError):
        await ReportIngester(stack.index, normalizers=[bad]).ingest(stack.analysis_id, FULL_REPORT)

    assert not await stack.opensearch.indices.exists(index=index_name(stack.analysis_id))


async def test_the_final_ingest_indexes_the_sigma_alerts_with_the_other_events(
    stack: Stack,
) -> None:
    rules = load_rules(TARTARUS_RULESET)

    result = await ReportIngester(stack.index, rules=lambda: rules).ingest(
        stack.analysis_id, FULL_REPORT
    )

    assert await stack.document_count() == result.event_count
    found = await stack.opensearch.search(
        index=index_name(stack.analysis_id),
        body={"query": {"bool": {"filter": [{"term": {"rule.ruleset": "sigma"}}]}}},
    )
    [alert] = [hit["_source"] for hit in found["hits"]["hits"]]
    assert alert["event"]["kind"] == "alert"
    assert alert["rule"]["id"] == "6c17e2ec-0203-4f72-8760-b1b2a72336db"
    assert alert["tartarus"]["phase"] == "final"
