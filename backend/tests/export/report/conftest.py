from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis
from app.export.report import gather
from app.export.report.gather import ProgressCallback, ReportSources, gather_report
from app.export.report.model import ReportInclude, ReportModel
from app.views.artifacts import AnalysisFiles, build_catalog
from app.views.attack_table import load_attack_table
from tests.export.report.fakes import DOCS, FakeIndex
from tests.export.report.fixtures import (
    JPEG_BYTES,
    PNG_BYTES,
    make_attack,
    make_detections,
    make_iocs,
    make_network,
    make_tree,
)
from tests.test_analysis_repository import seeded_analysis
from tests.test_annotation_repository import session  # noqa: F401 -- the SQLite session fixture

GENERATED_AT = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


@dataclass
class Gathering:
    """A seeded analysis, a fake index and the views to gather a report from."""

    analysis: Analysis
    session: AsyncSession
    index: FakeIndex
    storage_root: Path
    screenshots: list[Path]
    calls: dict[str, list[Any]]

    async def run(
        self,
        include: ReportInclude | None = None,
        progress: ProgressCallback = gather.ignore_progress,
    ) -> ReportModel:
        sources = ReportSources(
            session=self.session,
            index=self.index,  # type: ignore[arg-type]
            storage_root=self.storage_root,
            attack_table=load_attack_table(),
        )
        return await gather_report(
            self.analysis,
            sources,
            include or ReportInclude(),
            progress,
            clock=lambda: GENERATED_AT,
        )


@pytest.fixture
async def gathering(
    session: AsyncSession,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Gathering:
    """The views the gatherer calls are replaced by fakes that record how they were called."""
    first, second = tmp_path / "0001.png", tmp_path / "0002.jpg"
    first.write_bytes(PNG_BYTES)
    second.write_bytes(JPEG_BYTES)
    calls: dict[str, list[Any]] = {
        name: [] for name in ("tree", "detections", "attack", "network", "iocs", "files")
    }

    async def tree(index: object, analysis_id: int) -> object:
        calls["tree"].append(analysis_id)
        return make_tree()

    async def detections(index: object, analysis_id: int) -> object:
        calls["detections"].append(analysis_id)
        return make_detections()

    async def attack(index: object, analysis_id: int, table: object) -> object:
        calls["attack"].append(analysis_id)
        return make_attack()

    async def network(index: object, analysis_id: int, *, simulated: bool, limit: int) -> object:
        calls["network"].append((analysis_id, simulated, limit))
        return make_network()

    async def iocs(index: object, analysis: Analysis, files: AnalysisFiles) -> object:
        calls["iocs"].append(files)
        return make_iocs()

    def read_files(storage_root: Path, cape_task_id: int | None) -> AnalysisFiles:
        calls["files"].append((storage_root, cape_task_id))
        catalog = replace(build_catalog(None, None), screenshots=(first, second))
        return AnalysisFiles(None, catalog)

    monkeypatch.setattr(gather, "process_tree", tree)
    monkeypatch.setattr(gather, "list_detections", detections)
    monkeypatch.setattr(gather, "attack_matrix", attack)
    monkeypatch.setattr(gather, "network_view", network)
    monkeypatch.setattr(gather, "collect_iocs", iocs)
    monkeypatch.setattr(gather, "read_analysis_files", read_files)
    analysis = await seeded_analysis(session, filename="invoice.exe")
    return Gathering(analysis, session, FakeIndex(DOCS), tmp_path, [first, second], calls)
