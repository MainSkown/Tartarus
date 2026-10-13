from typing import Any

Event = dict[str, Any]

_counter = 0


def make_event(  # noqa: PLR0913 - a test builder: each argument is one thing a test varies
    lane: str = "file",
    *,
    pid: int = 100,
    action: str | None = None,
    severity: int = 0,
    timestamp: str = "2026-10-13T11:00:00.000Z",
    name: str | None = "sample.exe",
    executable: str | None = "C:\\Temp\\sample.exe",
    command_line: str | None = "sample.exe",
    start: str | None = "2026-10-13T10:59:00.000Z",
    parent_pid: int | None = 4,
    raw: bool = True,
) -> Event:
    global _counter  # noqa: PLW0603 - unique ids across a test run
    _counter += 1
    details = {
        "name": name,
        "executable": executable,
        "command_line": command_line,
        "start": start,
    }
    process: dict[str, Any] = {"pid": pid, **{k: v for k, v in details.items() if v is not None}}
    if parent_pid is not None:
        process["parent"] = {"pid": parent_pid}
    event: Event = {
        "@timestamp": timestamp,
        "event": {
            "id": f"event-{_counter}",
            "sequence": _counter,
            "action": action or f"{lane}-thing",
            "severity": severity,
        },
        "tartarus": {"analysis_id": 1, "lane": lane, "phase": "live", "summary": "something"},
        "process": process,
    }
    if raw:
        event["tartarus"]["raw"] = {"api": "NtSomething"}
    return event
