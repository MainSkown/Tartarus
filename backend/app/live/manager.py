import asyncio
import logging
from datetime import datetime
from pathlib import Path

from app.live.collector import LiveCollector, LiveEventStore
from app.live.hub import LiveHub
from app.live.utc import as_utc

logger = logging.getLogger(__name__)


class LiveCollectionManager:
    """Owns the live collector of each running analysis; the runner's `LiveCollection`."""

    def __init__(
        self, *, storage_path: Path, poll_interval_s: float, store: LiveEventStore, hub: LiveHub
    ) -> None:
        self._storage_path = storage_path
        self._poll_interval_s = poll_interval_s
        self._store = store
        self._hub = hub
        self._collectors: dict[int, LiveCollector] = {}

    def start(self, analysis_id: int, cape_task_id: int, started_at: datetime) -> None:
        if analysis_id in self._collectors:
            return
        collector = LiveCollector(
            analysis_id=analysis_id,
            logs_dir=self._storage_path / "analyses" / str(cape_task_id) / "logs",
            started_at=as_utc(started_at),
            store=self._store,
            sink=self._hub,
            poll_interval_s=self._poll_interval_s,
        )
        self._collectors[analysis_id] = collector
        self._hub.open(analysis_id)
        collector.start()

    async def stop(self, analysis_id: int) -> None:
        collector = self._collectors.pop(analysis_id, None)
        if collector is None:
            return
        try:
            await collector.stop()
        finally:
            self._hub.close(analysis_id)

    async def aclose(self) -> None:
        results = await asyncio.gather(
            *(self.stop(analysis_id) for analysis_id in list(self._collectors)),
            return_exceptions=True,
        )
        for failure in (r for r in results if isinstance(r, BaseException)):
            logger.error("Stopping a live collector at shutdown failed", exc_info=failure)
