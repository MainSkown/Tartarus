from collections.abc import Iterable
from typing import Any

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
