import asyncio
import contextlib
import itertools
import logging
import os
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.ingest.live_capemon import LiveCapemon
from app.ingest.protocol import IngestContext
from app.ingest.sigma import RulesProvider, no_rules
from app.live.bson_log import BsonLogParser, LogFormatError, LogRecord, UnknownRecord
from app.live.detections import LiveDetections
from app.live.messages import LIVE_INDEX_FAILED, LOG_FORMAT

logger = logging.getLogger(__name__)

Event = dict[str, Any]

LOG_SUFFIX = ".bson"
UNKNOWN_LOG_EVERY = 100


class LiveEventStore(Protocol):
    """The part of `EventIndex` the collector writes through."""

    async def ensure_template(self) -> None: ...

    async def ensure_index(self, analysis_id: int) -> None: ...

    async def bulk_index(self, analysis_id: int, events: Iterable[Event]) -> int: ...


class LiveSink(Protocol):
    """Where published events and problems go; the live hub."""

    def publish(self, analysis_id: int, events: list[Event]) -> None: ...

    def report_error(self, analysis_id: int, code: str, message: str) -> None: ...


@dataclass
class _LogFile:
    parser: BsonLogParser = field(default_factory=BsonLogParser)
    offset: int = 0
    dead: bool = False


@dataclass
class _Scan:
    events: list[Event] = field(default_factory=list)
    updated: list[Event] = field(default_factory=list)
    broken: list[tuple[str, LogFormatError]] = field(default_factory=list)
    unknown: list[tuple[str, UnknownRecord]] = field(default_factory=list)


class LiveCollector:
    """Tails the `logs/*.bson` of one running analysis and turns them into live events.

    It keeps no checkpoint: a collector started on logs that already hold data reads them from
    byte 0, and the index upserts by event id, so a restart repeats work and loses nothing.
    Events go to the sink first, so the stream is not held up by the index, which is best effort
    (its failure is reported once and never stops the collector).

    Each batch is normalised, derived, matched against the Sigma rules and then enqueued, so an
    alert reaches the sink and the index in the batch of the event that triggered it. The rules
    are those active when the collector is built, i.e. when the run starts; a rule switched on
    or off during the run applies from the next one. A repeat of an alert from an earlier batch
    only updates the index (see `LiveDetections`); the hub is not sent the alert twice.

    `stop()` reads whatever is still unread, releases the events the live front-end held back,
    and ends; call it once the guest has stopped writing.
    """

    def __init__(  # noqa: PLR0913 - one collector is configured by all of these
        self,
        *,
        analysis_id: int,
        logs_dir: Path,
        started_at: datetime,
        store: LiveEventStore,
        sink: LiveSink,
        poll_interval_s: float,
        rules: RulesProvider = no_rules,
    ) -> None:
        self._analysis_id = analysis_id
        self._logs_dir = logs_dir
        self._store = store
        self._sink = sink
        self._poll_interval_s = poll_interval_s
        # No host registrations: CAPE keeps the task's cuckoo.log in a write buffer until the task
        # ends, so the clock stays on the rounded offset live and the final ingest anchors it.
        context = IngestContext(analysis_id, started_at)
        self._live = LiveCapemon(context)
        self._detections = LiveDetections(rules(), context)
        self._sequence = itertools.count()
        self._files: dict[str, _LogFile] = {}
        self._unknown_seen: Counter[str] = Counter()
        self._index_ready = False
        self._index_failures = 0
        self._halt = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(), name=f"live-collector-{self._analysis_id}"
            )

    async def stop(self) -> None:
        """Does the final drain; safe to call again, and to abandon (it then still finishes)."""
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._drain_and_end())
        await asyncio.shield(self._shutdown_task)

    async def _run(self) -> None:
        while not self._halt.is_set():
            await self._poll()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._halt.wait(), self._poll_interval_s)

    async def _drain_and_end(self) -> None:
        self._halt.set()
        if self._task is not None:
            await self._task
        await self._poll()
        await self._deliver_guarded(await asyncio.to_thread(self._release_held))

    async def _poll(self) -> None:
        try:
            scan = await asyncio.to_thread(self._scan)
        except Exception:
            logger.exception("Reading the logs of analysis %s failed", self._analysis_id)
            return
        self._report_problems(scan)
        await self._deliver_guarded(scan)

    async def _deliver_guarded(self, scan: _Scan) -> None:
        if not scan.events:  # an update always comes with the event that repeated the alert
            return
        try:
            self._sink.publish(self._analysis_id, scan.events)
        except Exception:
            logger.exception("Publishing live events of analysis %s failed", self._analysis_id)
        await self._index(scan.events + scan.updated)

    async def _index(self, events: list[Event]) -> None:
        try:
            if not self._index_ready:
                await self._store.ensure_template()
                await self._store.ensure_index(self._analysis_id)
                self._index_ready = True
            await self._store.bulk_index(self._analysis_id, events)
        except Exception as error:  # noqa: BLE001 - best effort: nothing may stop the collector
            self._index_failures += 1
            logger.warning(
                "Live indexing of analysis %s failed (%d so far): %s",
                self._analysis_id,
                self._index_failures,
                error,
            )
            if self._index_failures == 1:
                self._sink.report_error(
                    self._analysis_id,
                    LIVE_INDEX_FAILED,
                    "Live events are not being indexed; the final ingest will still complete",
                )

    def _report_problems(self, scan: _Scan) -> None:
        for name, error in scan.broken:
            logger.warning(
                "Analysis %s: %s is not a readable log: %s", self._analysis_id, name, error
            )
            self._sink.report_error(
                self._analysis_id, LOG_FORMAT, f"{name} stopped being readable: {error.reason}"
            )
        for name, record in scan.unknown:
            self._note_unknown(name, record)

    def _note_unknown(self, name: str, record: UnknownRecord) -> None:
        self._unknown_seen[record.kind] += 1
        seen = self._unknown_seen[record.kind]
        if seen == 1 or seen % UNKNOWN_LOG_EVERY == 0:
            logger.warning(
                "Analysis %s: %s has a %r record that was not understood (%s); %d so far",
                self._analysis_id,
                name,
                record.kind,
                record.reason,
                seen,
            )

    def _scan(self) -> _Scan:
        """Reads the new bytes of every log and turns them into events; runs on a worker thread."""
        scan = _Scan()
        for name, path in _log_files(self._logs_dir):
            log = self._files.setdefault(name, _LogFile())
            if log.dead:
                continue
            try:
                chunk = _read_from(path, log.offset)
            except OSError as error:
                logger.warning("Analysis %s: cannot read %s: %s", self._analysis_id, name, error)
                continue
            log.offset += len(chunk)
            records = self._parse(name, log, chunk, scan)
            scan.unknown += [(name, r) for r in records if isinstance(r, UnknownRecord)]
            known = [r for r in records if not isinstance(r, UnknownRecord)]
            scan.events += self._live.update(name, known)
        self._detect(scan)
        return scan

    def _release_held(self) -> _Scan:
        scan = _Scan(events=self._live.flush())
        self._detect(scan)
        return scan

    def _detect(self, scan: _Scan) -> None:
        """Appends the batch's alerts after its events and numbers them all in one sequence.

        Each source numbers its own events, so the numbers only become unique across sources here.
        """
        detected = self._detections.process(scan.events)
        scan.events += detected.alerts
        scan.updated = detected.updates
        for event in scan.events:
            event["event"]["sequence"] = next(self._sequence)

    @staticmethod
    def _parse(name: str, log: _LogFile, chunk: bytes, scan: _Scan) -> list[LogRecord]:
        try:
            return log.parser.feed(chunk)
        except LogFormatError as error:
            log.dead = True
            scan.broken.append((name, error))
            return error.parsed


def _log_files(logs_dir: Path) -> list[tuple[str, Path]]:
    try:
        with os.scandir(logs_dir) as entries:
            found = [e for e in entries if e.name.endswith(LOG_SUFFIX) and e.is_file()]
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted((entry.name, Path(entry.path)) for entry in found)


def _read_from(path: Path, offset: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read()
