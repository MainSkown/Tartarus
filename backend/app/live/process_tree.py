from typing import Any

from app.live.messages import LiveProcess, ProcessData

PROCESS_TERMINATED = "process-terminated"
_DETAIL_FIELDS = ("ppid", "name", "executable", "command_line", "start")


class ProcessTree:
    """The processes of one running analysis, learned from the `process` section of its events."""

    def __init__(self) -> None:
        self.nodes: dict[int, LiveProcess] = {}

    def snapshot(self) -> list[LiveProcess]:
        return [self.nodes[pid] for pid in sorted(self.nodes)]

    def observe(self, event: dict[str, Any]) -> list[ProcessData]:
        seen = _process_of(event)
        if seen is None:
            return []
        deltas = self._add_or_update(seen)
        if event.get("event", {}).get("action") == PROCESS_TERMINATED:
            deltas += self._end(seen.pid, str(event.get("@timestamp")))
        return deltas

    def _add_or_update(self, seen: LiveProcess) -> list[ProcessData]:
        known = self.nodes.get(seen.pid)
        if known is None or _is_another_process(known, seen):
            self.nodes[seen.pid] = seen
            return [ProcessData(op="add", node=seen)]
        learned = {
            field: getattr(seen, field)
            for field in _DETAIL_FIELDS
            if getattr(seen, field) is not None and getattr(seen, field) != getattr(known, field)
        }
        if not learned:
            return []
        self.nodes[seen.pid] = known.model_copy(update=learned)
        return [ProcessData(op="update", node=self.nodes[seen.pid])]

    def _end(self, pid: int, at: str) -> list[ProcessData]:
        node = self.nodes[pid]
        if node.end is not None:
            return []
        self.nodes[pid] = node.model_copy(update={"end": at})
        return [ProcessData(op="end", node=self.nodes[pid])]


def _is_another_process(known: LiveProcess, seen: LiveProcess) -> bool:
    return known.start is not None and seen.start is not None and known.start != seen.start


def _process_of(event: dict[str, Any]) -> LiveProcess | None:
    process = event.get("process")
    if not isinstance(process, dict) or not isinstance(pid := process.get("pid"), int):
        return None
    parent = process.get("parent")
    return LiveProcess(
        pid=pid,
        ppid=parent.get("pid") if isinstance(parent, dict) else None,
        name=process.get("name"),
        executable=process.get("executable"),
        command_line=process.get("command_line"),
        start=process.get("start"),
    )
