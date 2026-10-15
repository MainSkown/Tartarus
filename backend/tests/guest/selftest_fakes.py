"""The parts around the self-test runner: an index with canned counts and an analysis pipeline."""

import asyncio
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import analysis_repository as repository
from app.db.models import Analysis
from app.db.models.analysis import AnalysisStatus

PIPELINE_STEP_S = 0.002


class CannedIndex:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.searched: list[tuple[int, dict[str, Any]]] = []

    async def search(self, analysis_id: int, body: dict[str, Any]) -> dict[str, Any]:
        self.searched.append((analysis_id, body))
        return self.response


def aggregations(
    *, processes: int = 3, files: int = 4, registry: int = 2, lookup: int = 2, answered: int = 1
) -> dict[str, Any]:
    return {
        "aggregations": {
            "processes": {"value": processes},
            "lanes": {
                "buckets": [
                    {"key": "network", "doc_count": 9},
                    *([{"key": "file", "doc_count": files}] if files else []),
                    *([{"key": "registry", "doc_count": registry}] if registry else []),
                ]
            },
            "lookup": {"doc_count": lookup, "answered": {"doc_count": answered}},
        }
    }


class FakePipeline:
    """Stands in for the analysis runner: when woken, walks the newest queued analysis through
    `statuses` and leaves it in the last one, with a summary when it ends `done`."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        statuses: Sequence[AnalysisStatus] = (
            AnalysisStatus.STARTING,
            AnalysisStatus.RUNNING,
            AnalysisStatus.PROCESSING,
            AnalysisStatus.INGESTING,
            AnalysisStatus.DONE,
        ),
        error: str | None = None,
    ) -> None:
        self._factory = factory
        self.statuses = list(statuses)
        self.error = error
        self.nudges = 0
        self._walks: list[asyncio.Task[None]] = []

    def nudge(self) -> None:
        self.nudges += 1
        self._walks.append(asyncio.create_task(self._walk()))

    async def stop(self) -> None:
        for walk in self._walks:
            walk.cancel()
        await asyncio.gather(*self._walks, return_exceptions=True)

    async def _walk(self) -> None:
        async with self._factory() as session:
            newest = await session.scalar(select(func.max(Analysis.id)))
        assert newest is not None
        for status in self.statuses:
            await asyncio.sleep(PIPELINE_STEP_S)
            async with self._factory() as session:
                summary = {"process_count": 3} if status is AnalysisStatus.DONE else None
                await repository.update_analysis(
                    session, newest, status=status, summary=summary, error=self.error
                )
