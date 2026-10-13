import asyncio
import contextlib
import logging
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from itertools import chain
from pathlib import Path
from typing import Any, Protocol

from app.analyses.ports import IngestFailedError, IngestResult, ReportUnreadableError
from app.analyses.summary import load_report
from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.cape_signatures import CapeSignaturesNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.clock import analysis_started
from app.ingest.protocol import IngestContext, Normalizer
from app.search.index import IndexingError

logger = logging.getLogger(__name__)

SETTLED_REFRESH_INTERVAL = "30s"


class EventStore(Protocol):
    """The part of `EventIndex` the ingester uses."""

    async def ensure_template(self) -> None: ...

    async def drop(self, analysis_id: int) -> None: ...

    async def create(self, analysis_id: int) -> None: ...

    async def bulk_index(self, analysis_id: int, events: Iterable[dict[str, Any]]) -> int: ...

    async def set_refresh_interval(self, analysis_id: int, interval: str) -> None: ...

    async def refresh(self, analysis_id: int) -> None: ...


def default_normalizers() -> list[Normalizer]:
    return [CapemonNormalizer(), CapeNetworkNormalizer(), CapeSignaturesNormalizer()]


class ReportIngester:
    """Indexes the events of a CAPE `report.json` into the analysis's own index.

    Satisfies `app.analyses.ports.EventIngester`.
    """

    def __init__(self, index: EventStore, normalizers: Sequence[Normalizer] | None = None) -> None:
        self._index = index
        self._normalizers = normalizers if normalizers is not None else default_normalizers()

    async def ingest(self, analysis_id: int, report_path: Path) -> IngestResult:
        try:
            return await self._rebuild(analysis_id, report_path)
        except IngestFailedError:
            raise
        except Exception as error:
            raise IngestFailedError(_reason(error)) from error

    async def _rebuild(self, analysis_id: int, report_path: Path) -> IngestResult:
        await self._index.ensure_template()
        await self._index.drop(analysis_id)
        context, report = await asyncio.to_thread(_read, analysis_id, report_path)
        try:
            await self._index.create(analysis_id)
            return await self._fill(analysis_id, report, context)
        except BaseException:
            await self._discard_partial_index(analysis_id)
            raise

    async def _fill(
        self, analysis_id: int, report: dict[str, Any], context: IngestContext
    ) -> IngestResult:
        lane_counts: Counter[str] = Counter()
        events = self._numbered(report, context, lane_counts)
        event_count = await self._index.bulk_index(analysis_id, events)
        await self._index.set_refresh_interval(analysis_id, SETTLED_REFRESH_INTERVAL)
        await self._index.refresh(analysis_id)
        return IngestResult(event_count=event_count, lane_counts=dict(lane_counts))

    def _numbered(
        self, report: dict[str, Any], context: IngestContext, lane_counts: Counter[str]
    ) -> Iterator[dict[str, Any]]:
        """Merges the sources, numbering events in stream order and counting them per lane.

        Each normaliser numbers its own events from zero, so the numbers only become unique
        across sources here.
        """
        merged = chain.from_iterable(n.normalise(report, context) for n in self._normalizers)
        for sequence, event in enumerate(merged):
            event["event"]["sequence"] = sequence
            lane_counts[event["tartarus"]["lane"]] += 1
            yield event

    async def _discard_partial_index(self, analysis_id: int) -> None:
        with contextlib.suppress(Exception):
            await self._index.drop(analysis_id)


def _read(analysis_id: int, report_path: Path) -> tuple[IngestContext, dict[str, Any]]:
    try:
        report = load_report(report_path)
    except ReportUnreadableError as unreadable:
        raise IngestFailedError(str(unreadable)) from None
    started_at = analysis_started(report)
    if started_at is None:
        raise IngestFailedError(f"report {report_path.name} has no analysis start time")
    return IngestContext(analysis_id=analysis_id, started_at=started_at), report


def _reason(error: Exception) -> str:
    if isinstance(error, IndexingError):
        return f"Indexing the events failed: {error}"
    # Client errors can carry the cluster's address; the type is enough for the analyst.
    logger.exception("Indexing failed unexpectedly")
    return f"Indexing the events failed ({type(error).__name__})"
