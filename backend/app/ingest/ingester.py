import asyncio
import contextlib
import logging
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from itertools import chain
from pathlib import Path
from typing import Any, Protocol

from app.analyses.defender import DefenderVerdict
from app.analyses.ports import IngestFailedError, IngestResult, ReportUnreadableError
from app.analyses.summary import load_report, process_count_of
from app.ingest.cape_network import CapeNetworkNormalizer
from app.ingest.cape_signatures import CapeSignaturesNormalizer
from app.ingest.capemon import CapemonNormalizer
from app.ingest.clock import (
    analysis_dir_of,
    analysis_started,
    read_host_registrations,
    task_log_of,
)
from app.ingest.defender import DefenderNormalizer
from app.ingest.defender_verdict import verdict_of_export
from app.ingest.protocol import IngestContext, Normalizer
from app.ingest.sigma import RulesProvider, can_match_a_rule, final_detections, no_rules
from app.ingest.sysmon import SysmonNormalizer
from app.ingest.volatility import VolatilityNormalizer
from app.rules.rule import Rule
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
    return [
        CapemonNormalizer(),
        CapeNetworkNormalizer(),
        CapeSignaturesNormalizer(),
        SysmonNormalizer(),
        DefenderNormalizer(),
        VolatilityNormalizer(),
    ]


class ReportIngester:
    """Indexes the events of a CAPE `report.json` into the analysis's own index.

    Satisfies `app.analyses.ports.EventIngester`.

    `rules` is asked for the Sigma rules to run once per ingest, so a rule switched off since
    the last ingest is not applied. The detections are matched over the complete, time-ordered
    event set after the normalisers are done and indexed after the other events, numbered
    with them. Only the events a rule could apply to are held back for that (a small part of
    a report, which is mostly API calls); the rest is streamed into the index as before.

    Without injected normalisers every ingest builds its own, because a normaliser keeps what it
    counted in itself and ingests of different analyses run at the same time.
    """

    def __init__(
        self,
        index: EventStore,
        normalizers: Sequence[Normalizer] | None = None,
        *,
        rules: RulesProvider = no_rules,
    ) -> None:
        self._index = index
        self._injected_normalizers = normalizers
        self._rules = rules

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
        injected = self._injected_normalizers
        normalizers = injected if injected is not None else default_normalizers()
        lane_counts: Counter[str] = Counter()
        events = self._numbered(self._with_detections(normalizers, report, context), lane_counts)
        event_count = await self._index.bulk_index(analysis_id, events)
        await self._index.set_refresh_interval(analysis_id, SETTLED_REFRESH_INTERVAL)
        await self._index.refresh(analysis_id)
        return IngestResult(
            event_count=event_count,
            lane_counts=dict(lane_counts),
            defender=_defender_verdict(normalizers, report),
            hidden_events=_hidden_events(normalizers),
        )

    def _with_detections(
        self, normalizers: Iterable[Normalizer], report: dict[str, Any], context: IngestContext
    ) -> Iterator[dict[str, Any]]:
        """The sources' events as they come, then the Sigma alerts over all of them."""
        merged = chain.from_iterable(n.normalise(report, context) for n in normalizers)
        rules = list(self._rules())
        if not rules:
            return merged
        matchable: list[dict[str, Any]] = []
        return chain(_remembering(merged, matchable), _detections(rules, context, matchable))

    @staticmethod
    def _numbered(
        events: Iterable[dict[str, Any]], lane_counts: Counter[str]
    ) -> Iterator[dict[str, Any]]:
        """Numbers events in stream order and counts them per lane.

        Each normaliser numbers its own events from zero, so the numbers only become unique
        across sources here.
        """
        for sequence, event in enumerate(events):
            event["event"]["sequence"] = sequence
            lane_counts[event["tartarus"]["lane"]] += 1
            yield event

    async def _discard_partial_index(self, analysis_id: int) -> None:
        with contextlib.suppress(Exception):
            await self._index.drop(analysis_id)


def _first_of[N: Normalizer](normalizers: Iterable[Normalizer], kind: type[N]) -> N | None:
    return next((n for n in normalizers if isinstance(n, kind)), None)


def _defender_verdict(
    normalizers: Iterable[Normalizer], report: dict[str, Any]
) -> DefenderVerdict | None:
    defender = _first_of(normalizers, DefenderNormalizer)
    if defender is None:
        return None
    return verdict_of_export(defender.export, process_count_of(report))


def _hidden_events(normalizers: Iterable[Normalizer]) -> dict[str, int]:
    sysmon = _first_of(normalizers, SysmonNormalizer)
    return {} if sysmon is None else dict(sysmon.dropped)


def _remembering(
    events: Iterable[dict[str, Any]], matchable: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    for event in events:
        if can_match_a_rule(event):
            matchable.append(event)
        yield event


def _detections(
    rules: Sequence[Rule], context: IngestContext, matchable: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    # A generator, so this runs only when the stream before it is spent and `matchable` is whole.
    yield from final_detections(rules, context, matchable)


def _read(analysis_id: int, report_path: Path) -> tuple[IngestContext, dict[str, Any]]:
    try:
        report = load_report(report_path)
    except ReportUnreadableError as unreadable:
        raise IngestFailedError(str(unreadable)) from None
    started_at = analysis_started(report)
    if started_at is None:
        raise IngestFailedError(f"report {report_path.name} has no analysis start time")
    registrations = read_host_registrations(task_log_of(report_path))
    context = IngestContext(
        analysis_id,
        started_at,
        host_registrations=registrations,
        analysis_dir=analysis_dir_of(report_path),
    )
    return context, report


def _reason(error: Exception) -> str:
    if isinstance(error, IndexingError):
        return f"Indexing the events failed: {error}"
    # Client errors can carry the cluster's address; the type is enough for the analyst.
    logger.exception("Indexing failed unexpectedly")
    return f"Indexing the events failed ({type(error).__name__})"
